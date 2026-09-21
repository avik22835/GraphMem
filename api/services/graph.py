import json
import math
import uuid
import asyncio
import httpx
import networkx as nx
import numpy as np
from datetime import datetime, timezone
from api.config import settings
from api.db.postgres import get_pool
from api.exceptions import ConversationNotFound
from api.models import MemoryNodeWithScore, RecallResult
from api.services.embedding import embed_query
from api.services.tokens import count_node_tokens


# ── Public entrypoint ─────────────────────────────────────────────────────────

async def recall(
    conversation_id: str,
    query: str,
    k: int | None = None,
    threshold: float | None = None,
    strategy: str = "semantic",
    recency_alpha: float = 0.7,
    recency_half_life: float | None = None,
    always_include_recent: int = 0,
    max_tokens: int | None = None,
) -> RecallResult:

    _k         = k         or settings.default_k
    _threshold = threshold or settings.default_threshold
    _max_tok   = max_tokens or settings.default_max_tokens
    _half_life = recency_half_life or settings.default_recency_half_life
    conv_uuid  = uuid.UUID(conversation_id)

    pool = get_pool()
    async with pool.acquire() as conn:

        # ── Cold start check ──────────────────────────────────────────────────
        node_count = await conn.fetchval(
            "SELECT node_count FROM conversations WHERE conversation_id = $1",
            conv_uuid,
        )
        if node_count is None:
            raise ConversationNotFound(conversation_id)

        if node_count < settings.cold_start_min_nodes:
            return await _cold_start(conn, conv_uuid, _max_tok, conversation_id)

        # ── Embed query synchronously ─────────────────────────────────────────
        q_emb = await embed_query(query)

        # ── Set B ─────────────────────────────────────────────────────────────
        if strategy == "semantic_recency":
            b_rows = await _set_b_recency(conn, conv_uuid, q_emb, _k, recency_alpha, _half_life)
        else:
            b_rows = await _set_b_semantic(conn, conv_uuid, q_emb, _k)

        b_ids    = {str(r["memory_id"]) for r in b_rows}
        b_scores = {str(r["memory_id"]): float(r["cosine_score"]) for r in b_rows}

        # ── Set A' ───────────────────────────────────────────────────────────
        a_rows   = await _set_a_prime(conn, conv_uuid, q_emb, _threshold, b_ids)
        a_ids    = {str(r["memory_id"]) for r in a_rows}
        a_scores = {str(r["memory_id"]): float(r["cosine_score"]) for r in a_rows}

        # ── Set C via PPR (sync → thread) ────────────────────────────────
        ppr_scores = await asyncio.to_thread(
            _set_c_ppr, list(b_ids), conversation_id
        )
        # ppr_scores: {memory_id → ppr_score}, already excludes seed ids
        c_ids = set(ppr_scores.keys()) - a_ids

        c_rows = await _fetch_with_embeddings(conn, list(c_ids)) if c_ids else []

        # ── Set R ────────────────────────────────────────────────────────────
        r_rows = []
        if always_include_recent > 0:
            r_rows = await _last_m(conn, conv_uuid, always_include_recent)
        r_ids = {str(r["memory_id"]) for r in r_rows}

        # ── Build candidates = A' ∪ B ∪ C, excluding R ───────────────────────
        candidates = []
        seen = set()

        for row in [*b_rows, *a_rows]:
            mid = str(row["memory_id"])
            if mid not in r_ids and mid not in seen:
                seen.add(mid)
                score = b_scores.get(mid) or a_scores.get(mid, 0.0)
                candidates.append(_to_candidate(row, score))

        for row in c_rows:
            mid = str(row["memory_id"])
            if mid not in r_ids and mid not in seen:
                seen.add(mid)
                node_emb = np.array(row["embedding"], dtype=np.float32)
                cos_sim = float(np.dot(q_emb, node_emb))
                ppr = ppr_scores.get(mid, 0.0)
                # PPR × cosine: structural graph relevance × semantic match
                combined = ppr * cos_sim
                candidates.append(_to_candidate(row, combined))

        # ── Token budgeting (R exempt) ────────────────────────────────────────
        r_tokens = sum(count_node_tokens(r["prompt"], r["response"]) for r in r_rows)
        survivors = _budget_cut(candidates, _max_tok - r_tokens)

        # ── Merge survivors + R, sort by timestamp ────────────────────────────
        r_candidates = [_to_candidate(r, 0.0) for r in r_rows]
        merged = {c["memory_id"]: c for c in [*survivors, *r_candidates]}
        sorted_nodes = sorted(merged.values(), key=lambda x: x["timestamp_prompt"])

        return _build_result(sorted_nodes, strategy, conversation_id)


# ── Cold start ────────────────────────────────────────────────────────────────

async def _cold_start(conn, conv_uuid: uuid.UUID, max_tokens: int, conversation_id: str) -> RecallResult:
    rows = await conn.fetch(
        """SELECT memory_id, prompt, response, timestamp_prompt, timestamp_response,
                  status, metadata, index
           FROM memory_nodes
           WHERE conversation_id = $1 AND status = 'complete'
           ORDER BY timestamp_prompt ASC""",
        conv_uuid,
    )
    nodes, total = [], 0
    for row in rows:
        t = count_node_tokens(row["prompt"], row["response"])
        if total + t > max_tokens:
            break
        nodes.append(_to_candidate(row, 0.0))
        total += t

    return _build_result(nodes, "cold_start", conversation_id)


# ── Set B ─────────────────────────────────────────────────────────────────────

async def _set_b_semantic(conn, conv_uuid, q_emb, k):
    return await conn.fetch(
        """SELECT memory_id, prompt, response, timestamp_prompt,
                  timestamp_response, metadata, status, index,
                  1 - (embedding <=> $1) AS cosine_score
           FROM memory_nodes
           WHERE conversation_id = $2 AND status = 'complete'
           ORDER BY embedding <=> $1
           LIMIT $3""",
        q_emb, conv_uuid, k,
    )


async def _set_b_recency(conn, conv_uuid, q_emb, k, alpha, half_life):
    # Fetch 3×K candidates by cosine, re-rank by blended score in Python
    rows = await conn.fetch(
        """SELECT memory_id, prompt, response, timestamp_prompt,
                  timestamp_response, metadata, status, index,
                  1 - (embedding <=> $1) AS cosine_score
           FROM memory_nodes
           WHERE conversation_id = $2 AND status = 'complete'
           ORDER BY embedding <=> $1
           LIMIT $3""",
        q_emb, conv_uuid, k * 3,
    )
    now = datetime.now(timezone.utc)
    lam = math.log(2) / half_life

    def blended(row):
        age = (now - row["timestamp_prompt"].replace(tzinfo=timezone.utc)).total_seconds()
        recency = math.exp(-lam * age)
        return alpha * float(row["cosine_score"]) + (1 - alpha) * recency

    ranked = sorted(rows, key=blended, reverse=True)
    return ranked[:k]


# ── Set A' ───────────────────────────────────────────────────────────────────

async def _set_a_prime(conn, conv_uuid, q_emb, threshold, b_ids: set):
    b_uuid_list = [uuid.UUID(i) for i in b_ids] if b_ids else []
    return await conn.fetch(
        """SELECT memory_id, prompt, response, timestamp_prompt,
                  timestamp_response, metadata, status, index,
                  1 - (embedding <=> $1) AS cosine_score
           FROM memory_nodes
           WHERE conversation_id = $2
             AND status = 'complete'
             AND NOT (memory_id = ANY($3::uuid[]))
             AND embedding <=> $1 <= $4""",
        q_emb, conv_uuid, b_uuid_list, 1 - threshold,
    )


# ── Set C via Personalized PageRank ──────────────────────────────────────────

def _parse_gmap(item: dict) -> dict:
    vals = item.get("@value", [])
    out = {}
    for i in range(0, len(vals), 2):
        k = vals[i]
        v = vals[i + 1]
        if isinstance(v, dict) and "@value" in v:
            v = v["@value"]
        out[k] = v
    return out


def _set_c_ppr(b_ids: list[str], conversation_id: str, ppr_threshold: float = 0.005) -> dict[str, float]:
    """Pull all conv edges from Neptune, run PPR seeded on b_ids.
    Returns {memory_id: ppr_score} for nodes above threshold, excluding seeds."""
    if not b_ids:
        return {}

    neptune_url = f"https://{settings.neptune_endpoint}:{settings.neptune_port}/gremlin"
    query = (
        f"g.V().has('memory_node','conversation_id','{conversation_id}')"
        ".outE('similar_to')"
        ".project('src','dst','weight')"
        ".by(outV().values('memory_id'))"
        ".by(inV().values('memory_id'))"
        ".by('weight')"
    )

    try:
        resp = httpx.post(neptune_url, json={"gremlin": query}, timeout=30.0)
        if not resp.is_success:
            return {}
        data = resp.json().get("result", {}).get("data", {})
        raw_edges = data.get("@value", []) if isinstance(data, dict) else []
    except Exception:
        return {}

    if not raw_edges:
        return {}

    G = nx.DiGraph()
    for item in raw_edges:
        e = _parse_gmap(item) if isinstance(item, dict) and "@value" in item else item
        src, dst, w = e.get("src"), e.get("dst"), float(e.get("weight", 1.0))
        if src and dst:
            G.add_edge(src, dst, weight=w)

    if not G.nodes:
        return {}

    valid_seeds = [sid for sid in b_ids if sid in G.nodes]
    if not valid_seeds:
        return {}

    personalization = {n: 0.0 for n in G.nodes}
    for sid in valid_seeds:
        personalization[sid] = 1.0 / len(valid_seeds)

    try:
        ppr = nx.pagerank(G, alpha=0.85, personalization=personalization, weight="weight", max_iter=100)
    except Exception:
        return {}

    b_set = set(b_ids)
    return {nid: score for nid, score in ppr.items() if score >= ppr_threshold and nid not in b_set}


# ── Fetch Set C nodes with embeddings for Python-side scoring ─────────────────

async def _fetch_with_embeddings(conn, ids: list[str]):
    uuid_list = [uuid.UUID(i) for i in ids]
    return await conn.fetch(
        """SELECT memory_id, prompt, response, timestamp_prompt,
                  timestamp_response, metadata, status, index, embedding
           FROM memory_nodes
           WHERE memory_id = ANY($1::uuid[]) AND status = 'complete'""",
        uuid_list,
    )


# ── Set R ─────────────────────────────────────────────────────────────────────

async def _last_m(conn, conv_uuid, m: int):
    return await conn.fetch(
        """SELECT memory_id, prompt, response, timestamp_prompt,
                  timestamp_response, metadata, status, index
           FROM memory_nodes
           WHERE conversation_id = $1 AND status = 'complete'
           ORDER BY timestamp_prompt DESC
           LIMIT $2""",
        conv_uuid, m,
    )


# ── Token budgeting ───────────────────────────────────────────────────────────

def _budget_cut(candidates: list[dict], budget: int) -> list[dict]:
    if budget <= 0:
        return []
    ranked = sorted(candidates, key=lambda x: x["cosine_score"], reverse=True)
    survivors, used = [], 0
    for node in ranked:
        t = count_node_tokens(node["prompt"], node["response"])
        if used + t > budget:
            continue
        survivors.append(node)
        used += t
    return survivors


# ── Build RecallResult ────────────────────────────────────────────────────────

def _build_result(nodes: list[dict], strategy_used: str, conversation_id: str = "") -> RecallResult:
    messages, text_list, total = [], [], 0
    for node in nodes:
        tc = count_node_tokens(node["prompt"], node["response"])
        total += tc
        messages.append(MemoryNodeWithScore(
            memory_id=str(node["memory_id"]),
            conversation_id=str(node.get("conversation_id") or conversation_id),
            index=node["index"],
            prompt=node["prompt"],
            response=node.get("response"),
            timestamp_prompt=node["timestamp_prompt"],
            timestamp_response=node.get("timestamp_response"),
            status=node["status"],
            metadata=dict(node["metadata"]) if node.get("metadata") else {},
            relevance_score=round(node["cosine_score"], 4),
            token_count=tc,
        ))
        text_list.append({"role": "user", "content": node["prompt"]})
        if node.get("response"):
            text_list.append({"role": "assistant", "content": node["response"]})

    return RecallResult(
        messages=messages,
        text=json.dumps(text_list),
        total_tokens=total,
        strategy_used=strategy_used,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_candidate(row, cosine_score: float) -> dict:
    d = dict(row)
    d["cosine_score"] = cosine_score
    return d
