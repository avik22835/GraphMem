import asyncio
import json
import uuid
from datetime import datetime, timezone
from api.db.postgres import get_pool
from api.db.neptune import get_traversal
from api.exceptions import ConversationNotFound


# ── Create ────────────────────────────────────────────────────────────────────

async def create_conversation(metadata: dict) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        conv_id = await conn.fetchval(
            """INSERT INTO conversations (metadata) VALUES ($1) RETURNING conversation_id""",
            metadata,
        )
    return str(conv_id)


# ── List ──────────────────────────────────────────────────────────────────────

async def list_conversations() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT conversation_id, metadata, node_count, last_topic_recompute, created_at
               FROM conversations
               ORDER BY created_at DESC""",
        )
    return [dict(r) for r in rows]


# ── Delete ────────────────────────────────────────────────────────────────────

async def delete_conversation(conversation_id: str) -> None:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE conversation_id = $1", conv_uuid
        )
        if not exists:
            raise ConversationNotFound(conversation_id)

    # Drop all Neptune vertices (cascades their edges)
    await asyncio.to_thread(_drop_conversation_vertices, conversation_id)

    # Cascade-delete everything in Postgres: topics + memory_nodes + conversation
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM topics WHERE conversation_id = $1", conv_uuid
            )
            await conn.execute(
                "DELETE FROM memory_nodes WHERE conversation_id = $1", conv_uuid
            )
            await conn.execute(
                "DELETE FROM conversations WHERE conversation_id = $1", conv_uuid
            )


# ── Stats ─────────────────────────────────────────────────────────────────────

async def get_stats(conversation_id: str) -> dict:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)

    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            """SELECT node_count, created_at, last_topic_recompute,
                      jsonb_array_length(dirty_topics) AS dirty_topics_count
               FROM conversations WHERE conversation_id = $1""",
            conv_uuid,
        )
        if not conv:
            raise ConversationNotFound(conversation_id)

        counts = await conn.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE status = 'complete') AS complete_count,
                 COUNT(*) FILTER (WHERE status = 'pending')  AS pending_count,
                 MAX(timestamp_prompt) AS last_activity
               FROM memory_nodes
               WHERE conversation_id = $1""",
            conv_uuid,
        )
        topic_count = await conn.fetchval(
            "SELECT COUNT(*) FROM topics WHERE conversation_id = $1", conv_uuid
        )

    raw_edge_count = await asyncio.to_thread(_count_edges, conversation_id)
    edge_count     = raw_edge_count // 2
    node_count     = conv["node_count"]
    avg_degree     = round((2 * edge_count) / node_count, 4) if node_count > 0 else 0.0
    graph_density  = round((2 * edge_count) / (node_count * (node_count - 1)), 4) if node_count > 1 else 0.0

    return {
        "conversation_id":      conversation_id,
        "node_count":           node_count,
        "complete_count":       counts["complete_count"],
        "pending_count":        counts["pending_count"],
        "topic_count":          topic_count,
        "edge_count":           edge_count,
        "avg_degree":           avg_degree,
        "graph_density":        graph_density,
        "dirty_topics_count":   conv["dirty_topics_count"],
        "last_topic_recompute": conv["last_topic_recompute"],
        "last_activity":        counts["last_activity"],
        "created_at":           conv["created_at"],
    }


# ── Export ────────────────────────────────────────────────────────────────────

async def export_conversation(conversation_id: str) -> list[dict]:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE conversation_id = $1", conv_uuid
        )
        if not exists:
            raise ConversationNotFound(conversation_id)

        rows = await conn.fetch(
            """SELECT memory_id, index, prompt, response, timestamp_prompt,
                      timestamp_response, status, metadata
               FROM memory_nodes
               WHERE conversation_id = $1
               ORDER BY index ASC""",
            conv_uuid,
        )

    return [
        {
            "memory_id": str(r["memory_id"]),
            "index": r["index"],
            "prompt": r["prompt"],
            "response": r["response"],
            "timestamp_prompt": r["timestamp_prompt"].isoformat() if r["timestamp_prompt"] else None,
            "timestamp_response": r["timestamp_response"].isoformat() if r["timestamp_response"] else None,
            "status": r["status"],
            "metadata": dict(r["metadata"]) if r["metadata"] else {},
        }
        for r in rows
    ]


# ── Neptune sync helpers ──────────────────────────────────────────────────────

def _drop_conversation_vertices(conversation_id: str) -> None:
    g = get_traversal()
    g.V().has("memory_node", "conversation_id", conversation_id).drop().iterate()


def _count_edges(conversation_id: str) -> int:
    g = get_traversal()
    return (
        g.V()
        .has("memory_node", "conversation_id", conversation_id)
        .outE("similar_to")
        .count()
        .next()
    )


# ── Shared helper ─────────────────────────────────────────────────────────────

def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Invalid UUID: '{value}'")
