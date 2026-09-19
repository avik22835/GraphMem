import asyncio
import json
import uuid
from datetime import datetime, timezone
from api.db.postgres import get_pool
from api.db.neptune import get_traversal
from api.exceptions import (
    ConversationNotFound,
    MemoryNodeNotFound,
    ConversationMismatch,
    NodeAlreadyComplete,
)


async def create_pending_node(
    conversation_id: str,
    content: str,
    timestamp: datetime | None,
    metadata: dict,
) -> str:
    pool = get_pool()
    conv_uuid = _parse_uuid(conversation_id)
    ts = timestamp or datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            conv = await conn.fetchrow(
                "SELECT conversation_id FROM conversations WHERE conversation_id = $1",
                conv_uuid,
            )
            if not conv:
                raise ConversationNotFound(conversation_id)

            # Atomic index increment — safe under concurrent add_prompt calls
            row = await conn.fetchrow(
                """UPDATE conversations
                   SET next_index = next_index + 1
                   WHERE conversation_id = $1
                   RETURNING next_index""",
                conv_uuid,
            )

            memory_id = await conn.fetchval(
                """INSERT INTO memory_nodes
                       (conversation_id, index, prompt, timestamp_prompt, metadata, status)
                   VALUES ($1, $2, $3, $4, $5, 'pending')
                   RETURNING memory_id""",
                conv_uuid,
                row["next_index"],
                content,
                ts,
                metadata,
            )

    return str(memory_id)


async def attach_response(
    memory_id: str,
    conversation_id: str,
    content: str,
    timestamp: datetime | None,
) -> None:
    pool = get_pool()
    mem_uuid = _parse_uuid(memory_id)
    ts = timestamp or datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        node = await conn.fetchrow(
            "SELECT conversation_id, status FROM memory_nodes WHERE memory_id = $1",
            mem_uuid,
        )
        if not node:
            raise MemoryNodeNotFound(memory_id)
        if str(node["conversation_id"]) != conversation_id:
            raise ConversationMismatch()
        if node["status"] == "complete":
            raise NodeAlreadyComplete(memory_id)

        await conn.execute(
            """UPDATE memory_nodes
               SET response = $1, timestamp_response = $2, status = 'complete'
               WHERE memory_id = $3""",
            content,
            ts,
            mem_uuid,
        )


async def get_node(memory_id: str) -> dict:
    pool = get_pool()
    mem_uuid = _parse_uuid(memory_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT memory_id, conversation_id, index, prompt, response,
                      timestamp_prompt, timestamp_response, status, metadata
               FROM memory_nodes WHERE memory_id = $1""",
            mem_uuid,
        )
    if not row:
        raise MemoryNodeNotFound(memory_id)
    return dict(row)


async def delete_node(memory_id: str) -> None:
    pool = get_pool()
    mem_uuid = _parse_uuid(memory_id)

    async with pool.acquire() as conn:
        node = await conn.fetchrow(
            "SELECT conversation_id, status FROM memory_nodes WHERE memory_id = $1",
            mem_uuid,
        )
        if not node:
            raise MemoryNodeNotFound(memory_id)

        conv_uuid = node["conversation_id"]
        was_complete = node["status"] == "complete"

        # Find topics that contain this node — mark them dirty
        topic_rows = await conn.fetch(
            """SELECT topic_id FROM topics
               WHERE conversation_id = $1 AND message_ids @> $2::jsonb""",
            conv_uuid,
            json.dumps([memory_id]),
        )
        if topic_rows:
            dirty_ids = json.dumps([str(r["topic_id"]) for r in topic_rows])
            await conn.execute(
                """UPDATE conversations
                   SET dirty_topics = (
                       SELECT jsonb_agg(DISTINCT elem)
                       FROM jsonb_array_elements_text(dirty_topics || $1::jsonb) elem
                   )
                   WHERE conversation_id = $2""",
                dirty_ids,
                conv_uuid,
            )

        # Hard delete node from Postgres
        await conn.execute("DELETE FROM memory_nodes WHERE memory_id = $1", mem_uuid)

        # Decrement node_count only if the node was fully processed
        if was_complete:
            await conn.execute(
                "UPDATE conversations SET node_count = node_count - 1 WHERE conversation_id = $1",
                conv_uuid,
            )

    # Drop Neptune vertex (cascades incident edges)
    await asyncio.to_thread(_drop_vertex, memory_id)


async def get_neighbourhood(memory_id: str) -> list[dict]:
    pool = get_pool()
    mem_uuid = _parse_uuid(memory_id)

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM memory_nodes WHERE memory_id = $1", mem_uuid
        )
        if not exists:
            raise MemoryNodeNotFound(memory_id)

    # Fetch 1-hop neighbours + weights from Neptune (sync in thread)
    raw = await asyncio.to_thread(_get_neighbours_neptune, memory_id)
    if not raw:
        return []

    neighbour_ids = [r["neighbour_id"] for r in raw]
    weight_map = {r["neighbour_id"]: r["weight"] for r in raw}

    # Fetch full node data from Postgres
    uuid_list = [uuid.UUID(nid) for nid in neighbour_ids]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT memory_id, conversation_id, index, prompt, response,
                      timestamp_prompt, timestamp_response, status, metadata
               FROM memory_nodes
               WHERE memory_id = ANY($1::uuid[]) AND status = 'complete'""",
            uuid_list,
        )

    return [
        {**dict(r), "edge_weight": weight_map.get(str(r["memory_id"]), 0.0)}
        for r in rows
    ]


async def add_batch(items: list[dict]) -> list[str]:
    """Each item must have: conversation_id, prompt, response.
    Optional: timestamp_prompt, timestamp_response, metadata."""
    pool = get_pool()
    memory_ids = []

    async with pool.acquire() as conn:
        # Verify all unique conversation_ids exist up front
        unique_conv_ids = {item["conversation_id"] for item in items}
        for cid in unique_conv_ids:
            exists = await conn.fetchval(
                "SELECT 1 FROM conversations WHERE conversation_id = $1",
                uuid.UUID(cid),
            )
            if not exists:
                raise ConversationNotFound(cid)

        async with conn.transaction():
            for item in items:
                conv_uuid = uuid.UUID(item["conversation_id"])
                ts_prompt = item.get("timestamp_prompt") or datetime.now(timezone.utc)
                ts_response = item.get("timestamp_response") or datetime.now(timezone.utc)
                metadata = item.get("metadata") or {}

                # Atomic index increment
                row = await conn.fetchrow(
                    """UPDATE conversations
                       SET next_index = next_index + 1
                       WHERE conversation_id = $1
                       RETURNING next_index""",
                    conv_uuid,
                )

                mem_id = await conn.fetchval(
                    """INSERT INTO memory_nodes
                           (conversation_id, index, prompt, response,
                            timestamp_prompt, timestamp_response, metadata, status)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, 'complete')
                       RETURNING memory_id""",
                    conv_uuid,
                    row["next_index"],
                    item["prompt"],
                    item["response"],
                    ts_prompt,
                    ts_response,
                    metadata,
                )
                memory_ids.append(str(mem_id))

    return memory_ids


# ── Neptune sync helpers ──────────────────────────────────────────────────────

def _drop_vertex(memory_id: str) -> None:
    g = get_traversal()
    g.V().has("memory_node", "memory_id", memory_id).drop().iterate()


def _get_neighbours_neptune(memory_id: str) -> list[dict]:
    from gremlin_python.process.graph_traversal import __
    g = get_traversal()
    return (
        g.V()
        .has("memory_node", "memory_id", memory_id)
        .bothE("similar_to")
        .project("neighbour_id", "weight")
        .by(__.otherV().values("memory_id"))
        .by("weight")
        .to_list()
    )


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Invalid UUID: '{value}'")
