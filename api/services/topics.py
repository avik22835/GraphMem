import json
import uuid
import numpy as np
from groq import AsyncGroq
from api.config import settings
from api.db.postgres import get_pool
from api.exceptions import ConversationNotFound
from api.models import MemoryNodeWithScore, TopicRetrievalResult
from api.services.embedding import embed_query
from api.services.tokens import count_node_tokens
from api.services.sqs import push_topic_job
from fastapi import HTTPException

_groq: AsyncGroq | None = None


def _get_groq() -> AsyncGroq:
    global _groq
    if _groq is None:
        _groq = AsyncGroq(api_key=settings.groq_api_key)
    return _groq


# ── list_topics ───────────────────────────────────────────────────────────────

async def list_topics(conversation_id: str, status: str | None = None) -> list[dict]:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE conversation_id = $1", conv_uuid
        )
        if not exists:
            raise ConversationNotFound(conversation_id)

        if status:
            rows = await conn.fetch(
                """SELECT topic_id, conversation_id, label, description, summary,
                          coherence, is_mixed, sub_themes, status, message_ids,
                          louvain_resolution, recompute_count, last_active,
                          created_at, updated_at,
                          jsonb_array_length(message_ids) AS message_count
                   FROM topics
                   WHERE conversation_id = $1 AND status = $2
                   ORDER BY last_active DESC""",
                conv_uuid, status,
            )
        else:
            rows = await conn.fetch(
                """SELECT topic_id, conversation_id, label, description, summary,
                          coherence, is_mixed, sub_themes, status, message_ids,
                          louvain_resolution, recompute_count, last_active,
                          created_at, updated_at,
                          jsonb_array_length(message_ids) AS message_count
                   FROM topics
                   WHERE conversation_id = $1
                   ORDER BY last_active DESC""",
                conv_uuid,
            )

    return [_serialize_topic(r) for r in rows]


# ── topic_info ────────────────────────────────────────────────────────────────

async def topic_info(topic_id: str) -> dict:
    pool = get_pool()
    t_uuid = _parse_uuid(topic_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT t.topic_id, t.conversation_id, t.label, t.description, t.summary,
                      t.coherence, t.is_mixed, t.sub_themes, t.status, t.message_ids,
                      t.louvain_resolution, t.recompute_count, t.last_active,
                      t.created_at, t.updated_at,
                      jsonb_array_length(t.message_ids) AS message_count,
                      (c.dirty_topics @> to_jsonb(t.topic_id::text)) AS is_dirty
               FROM topics t
               JOIN conversations c ON c.conversation_id = t.conversation_id
               WHERE t.topic_id = $1""",
            t_uuid,
        )

    if not row:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")

    result = _serialize_topic(row)
    result["is_dirty"] = row["is_dirty"] or False
    return result


# ── topic_summary ─────────────────────────────────────────────────────────────

async def topic_summary(topic_id: str) -> dict:
    pool = get_pool()
    t_uuid = _parse_uuid(topic_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT topic_id, summary FROM topics WHERE topic_id = $1", t_uuid
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    return {"topic_id": str(row["topic_id"]), "summary": row["summary"]}


# ── topic_status ──────────────────────────────────────────────────────────────

async def topic_status(topic_id: str) -> dict:
    pool = get_pool()
    t_uuid = _parse_uuid(topic_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT topic_id, status FROM topics WHERE topic_id = $1", t_uuid
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    return {"topic_id": str(row["topic_id"]), "status": row["status"]}


# ── topic_relevance ───────────────────────────────────────────────────────────

async def topic_relevance(
    conversation_id: str,
    query: str,
    top_n: int = 3,
) -> list[dict]:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)

    q_emb = await embed_query(query)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT topic_id, label,
                      1 - (centroid <=> $1) AS score
               FROM topics
               WHERE conversation_id = $2 AND centroid IS NOT NULL
               ORDER BY centroid <=> $1
               LIMIT $3""",
            q_emb, conv_uuid, top_n,
        )

    return [
        {"topic_id": str(r["topic_id"]), "label": r["label"], "score": round(float(r["score"]), 4)}
        for r in rows
    ]


# ── current_topic ─────────────────────────────────────────────────────────────

async def current_topic(conversation_id: str, mode: str = "centroid") -> dict | None:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)

    async with pool.acquire() as conn:
        # Fetch most recent complete node with embedding
        recent = await conn.fetchrow(
            """SELECT memory_id, prompt, response, embedding
               FROM memory_nodes
               WHERE conversation_id = $1 AND status = 'complete' AND embedding IS NOT NULL
               ORDER BY timestamp_prompt DESC
               LIMIT 1""",
            conv_uuid,
        )
        if not recent:
            return None

        recent_emb = np.array(recent["embedding"], dtype=np.float32)

        # Centroid step — used by both centroid and hybrid modes
        top_row = await conn.fetchrow(
            """SELECT topic_id, label, summary,
                      1 - (centroid <=> $1) AS score
               FROM topics
               WHERE conversation_id = $2 AND centroid IS NOT NULL
               ORDER BY centroid <=> $1
               LIMIT 1""",
            recent_emb, conv_uuid,
        )

        if not top_row:
            return None

        if mode == "centroid":
            return {
                "topic_id": str(top_row["topic_id"]),
                "label":    top_row["label"],
                "score":    round(float(top_row["score"]), 4),
                "mode":     "centroid",
            }

        # For hybrid and llm — fetch all topics with summaries
        all_topics = await conn.fetch(
            """SELECT topic_id, label, summary
               FROM topics
               WHERE conversation_id = $1 AND summary IS NOT NULL AND summary != ''
               ORDER BY last_active DESC""",
            conv_uuid,
        )

    if not all_topics:
        # Fall back to centroid result if no summaries exist yet
        return {
            "topic_id": str(top_row["topic_id"]),
            "label":    top_row["label"],
            "score":    round(float(top_row["score"]), 4),
            "mode":     "centroid_fallback",
        }

    topics_list = "\n".join(
        f"- {r['topic_id']}: {r['label']} — {r['summary']}" for r in all_topics
    )
    prompt_text = recent["prompt"] or ""
    response_text = (recent["response"] or "").strip()

    if mode == "hybrid":
        prompt = f"""The centroid similarity analysis suggests this conversation is currently about:
Topic: "{top_row['label']}" (similarity score: {float(top_row['score']):.2f})
Topic summary: {top_row['summary']}

Most recent message:
USER: {prompt_text}
ASSISTANT: {response_text}

All available topics:
{topics_list}

Confirm if the centroid result is correct, or select the most appropriate topic.
Output valid JSON only: {{"topic_id": string, "confirmed": boolean}}"""

    else:  # llm mode
        prompt = f"""Based on the most recent message in this conversation, determine which topic it currently belongs to.

Most recent message:
USER: {prompt_text}
ASSISTANT: {response_text}

Available topics:
{topics_list}

Output valid JSON only: {{"topic_id": string, "score": float}}"""

    try:
        resp = await _get_groq().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        result = json.loads(resp.choices[0].message.content)
        chosen_id = result.get("topic_id", str(top_row["topic_id"]))
        score = result.get("score", float(top_row["score"]))
        # Find label for the chosen topic
        label = next((r["label"] for r in all_topics if str(r["topic_id"]) == chosen_id), top_row["label"])
        return {
            "topic_id": chosen_id,
            "label":    label,
            "score":    round(float(score), 4),
            "mode":     mode,
        }
    except Exception as e:
        # Fall back to centroid result on Groq failure
        return {
            "topic_id": str(top_row["topic_id"]),
            "label":    top_row["label"],
            "score":    round(float(top_row["score"]), 4),
            "mode":     "centroid_fallback",
        }


# ── retrieve_by_topic ─────────────────────────────────────────────────────────

async def retrieve_by_topic(
    conversation_id: str,
    topic_id: str,
    query: str | None = None,
    max_tokens: int | None = None,
) -> TopicRetrievalResult:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)
    t_uuid    = _parse_uuid(topic_id)
    _max_tok  = max_tokens or settings.default_max_tokens

    async with pool.acquire() as conn:
        topic = await conn.fetchrow(
            "SELECT conversation_id, message_ids FROM topics WHERE topic_id = $1",
            t_uuid,
        )
        if not topic:
            raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
        if str(topic["conversation_id"]) != conversation_id:
            raise HTTPException(status_code=403, detail="topic_id does not belong to this conversation")

        message_ids = json.loads(topic["message_ids"]) if isinstance(topic["message_ids"], str) else topic["message_ids"]
        if not message_ids:
            return TopicRetrievalResult(messages=[], text="[]", total_tokens=0, topics_used=[topic_id], strategy_used="retrieve_by_topic")

        uuid_list = [uuid.UUID(mid) for mid in message_ids]
        rows = await conn.fetch(
            """SELECT memory_id, conversation_id, index, prompt, response,
                      timestamp_prompt, timestamp_response, status, metadata, embedding
               FROM memory_nodes
               WHERE memory_id = ANY($1::uuid[]) AND status = 'complete'""",
            uuid_list,
        )

    if not rows:
        return TopicRetrievalResult(messages=[], text="[]", total_tokens=0, topics_used=[topic_id], strategy_used="retrieve_by_topic")

    nodes = [dict(r) for r in rows]

    if query:
        q_emb = await embed_query(query)
        for node in nodes:
            emb = node.get("embedding")
            if emb is not None:
                node["_score"] = float(np.dot(q_emb, np.array(emb, dtype=np.float32)))
            else:
                node["_score"] = 0.0
        # Sort by score descending → greedy budget fill → re-sort by timestamp
        nodes.sort(key=lambda n: n["_score"], reverse=True)
    else:
        nodes.sort(key=lambda n: n["timestamp_prompt"])
        for node in nodes:
            node["_score"] = 0.0

    selected, total = [], 0
    for node in nodes:
        t = count_node_tokens(node["prompt"], node["response"])
        if total + t > _max_tok:
            continue
        selected.append(node)
        total += t

    selected.sort(key=lambda n: n["timestamp_prompt"])
    return _build_topic_result(selected, [topic_id], "retrieve_by_topic")


# ── retrieve_by_topics ────────────────────────────────────────────────────────

async def retrieve_by_topics(
    conversation_id: str,
    query: str,
    top_n: int = 3,
    max_tokens: int | None = None,
) -> TopicRetrievalResult:
    pool     = get_pool()
    conv_uuid = _parse_uuid(conversation_id)
    _max_tok  = max_tokens or settings.default_max_tokens

    # Stage 1 — topic relevance (centroid mode, embed query once)
    q_emb = await embed_query(query)

    async with pool.acquire() as conn:
        topic_rows = await conn.fetch(
            """SELECT topic_id, message_ids,
                      1 - (centroid <=> $1) AS score
               FROM topics
               WHERE conversation_id = $2 AND centroid IS NOT NULL
               ORDER BY centroid <=> $1
               LIMIT $3""",
            q_emb, conv_uuid, top_n,
        )

        if not topic_rows:
            return TopicRetrievalResult(messages=[], text="[]", total_tokens=0, topics_used=[], strategy_used="retrieve_by_topics")

        # Collect all unique node IDs across top topics
        topics_used = [str(r["topic_id"]) for r in topic_rows]
        all_node_ids: set[str] = set()
        for r in topic_rows:
            mids = json.loads(r["message_ids"]) if isinstance(r["message_ids"], str) else r["message_ids"]
            all_node_ids.update(mids)

        uuid_list = [uuid.UUID(mid) for mid in all_node_ids]
        rows = await conn.fetch(
            """SELECT memory_id, conversation_id, index, prompt, response,
                      timestamp_prompt, timestamp_response, status, metadata, embedding
               FROM memory_nodes
               WHERE memory_id = ANY($1::uuid[]) AND status = 'complete'""",
            uuid_list,
        )

    nodes = [dict(r) for r in rows]

    # Score all nodes by cosine similarity to query
    for node in nodes:
        emb = node.get("embedding")
        if emb is not None:
            node["_score"] = float(np.dot(q_emb, np.array(emb, dtype=np.float32)))
        else:
            node["_score"] = 0.0

    # Layer 2 token budget algorithm (notes page 9):
    # Sort by timestamp → check budget → if over, re-sort by score, cut, re-sort by timestamp
    nodes.sort(key=lambda n: n["timestamp_prompt"])
    total = sum(count_node_tokens(n["prompt"], n["response"]) for n in nodes)

    if total <= _max_tok:
        selected = nodes
    else:
        nodes.sort(key=lambda n: n["_score"], reverse=True)
        selected, used = [], 0
        for node in nodes:
            t = count_node_tokens(node["prompt"], node["response"])
            if used + t > _max_tok:
                continue
            selected.append(node)
            used += t
        selected.sort(key=lambda n: n["timestamp_prompt"])

    return _build_topic_result(selected, topics_used, "retrieve_by_topics")


# ── recompute_topics ──────────────────────────────────────────────────────────

async def recompute_topics(conversation_id: str) -> None:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE conversation_id = $1", conv_uuid
        )
        if not exists:
            raise ConversationNotFound(conversation_id)

    push_topic_job(conversation_id)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_topic_result(nodes: list[dict], topics_used: list[str], strategy: str) -> TopicRetrievalResult:
    messages, text_list, total = [], [], 0
    for node in nodes:
        tc = count_node_tokens(node["prompt"], node["response"])
        total += tc
        messages.append(MemoryNodeWithScore(
            memory_id=str(node["memory_id"]),
            conversation_id=str(node["conversation_id"]),
            index=node["index"],
            prompt=node["prompt"],
            response=node.get("response"),
            timestamp_prompt=node["timestamp_prompt"],
            timestamp_response=node.get("timestamp_response"),
            status=node["status"],
            metadata=dict(node["metadata"]) if node.get("metadata") else {},
            relevance_score=round(node.get("_score", 0.0), 4),
            token_count=tc,
        ))
        text_list.append({"role": "user", "content": node["prompt"]})
        if node.get("response"):
            text_list.append({"role": "assistant", "content": node["response"]})

    return TopicRetrievalResult(
        messages=messages,
        text=json.dumps(text_list),
        total_tokens=total,
        topics_used=topics_used,
        strategy_used=strategy,
    )


def _serialize_topic(row) -> dict:
    return {
        "topic_id":           str(row["topic_id"]),
        "conversation_id":    str(row["conversation_id"]),
        "label":              row["label"],
        "description":        row["description"],
        "summary":            row["summary"],
        "coherence":          row["coherence"],
        "is_mixed":           row["is_mixed"],
        "sub_themes":         row["sub_themes"] if isinstance(row["sub_themes"], list) else json.loads(row["sub_themes"] or "[]"),
        "status":             row["status"],
        "message_ids":        row["message_ids"] if isinstance(row["message_ids"], list) else json.loads(row["message_ids"] or "[]"),
        "message_count":      row["message_count"],
        "last_active":        row["last_active"].isoformat() if row["last_active"] else None,
        "created_at":         row["created_at"].isoformat(),
        "updated_at":         row["updated_at"].isoformat(),
        "louvain_resolution": row["louvain_resolution"],
        "recompute_count":    row["recompute_count"],
    }


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: '{value}'")
