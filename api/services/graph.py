import json
import math
import uuid
import asyncio
import numpy as np
from datetime import datetime, timezone
from api.config import settings
from api.db.postgres import get_pool
from api.db.neptune import get_traversal
from api.exceptions import ConversationNotFound
from api.models import MemoryNodeWithScore, RecallResult
from api.services.embedding import embed_query
from api.services.tokens import count_node_tokens
from gremlin_python.process.traversal import P


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
            return await _cold_start(conn, conv_uuid, _max_tok)

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

        # ── Set C via Neptune (sync → thread) ────────────────────────────────
        c_raw_ids = await asyncio.to_thread(
            _set_c_neptune, list(b_ids), conversation_id, _threshold
        )
        c_ids = c_raw_ids - b_ids - a_ids

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
                score = float(np.dot(q_emb, node_emb))
                candidates.append(_to_candidate(row, score))

        # ── Token budgeting (R exempt) ────────────────────────────────────────
        r_tokens = sum(count_node_tokens(r["prompt"], r["response"]) for r in r_rows)
        survivors = _budget_cut(candidates, _max_tok - r_tokens)

        # ── Merge survivors + R, sort by timestamp ────────────────────────────
        r_candidates = [_to_candidate(r, 0.0) for r in r_rows]
        merged = {c["memory_id"]: c for c in [*survivors, *r_candidates]}
        sorted_nodes = sorted(merged.values(), key=lambda x: x["timestamp_prompt"])

        return _build_result(sorted_nodes, strategy)


# ── Cold start ────────────────────────────────────────────────────────────────

async def _cold_start(conn, conv_uuid: uuid.UUID, max_tokens: int) -> RecallResult:
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

    return _build_result(nodes, "cold_start")


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


# ── Set C via Neptune ─────────────────────────────────────────────────────────

def _set_c_neptune(b_id_list: list[str], conversation_id: str, threshold: float) -> set[str]:
    if not b_id_list:
        return set()
    g = get_traversal()
    result = (
        g.V()
        .has("memory_node", "memory_id", P.within(b_id_list))
        .outE("similar_to")
        .has("weight", P.gte(threshold))          # defensive: re-check weight
        .has("conversation_id", conversation_id)
        .inV()
        .values("memory_id")
        .to_list()
    )
    return set(result) - set(b_id_list)


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

def _build_result(nodes: list[dict], strategy_used: str) -> RecallResult:
    messages, text_list, total = [], [], 0
    for node in nodes:
        tc = count_node_tokens(node["prompt"], node["response"])
        total += tc
        messages.append(MemoryNodeWithScore(
            memory_id=str(node["memory_id"]),
            conversation_id=str(node.get("conversation_id", "")),
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
