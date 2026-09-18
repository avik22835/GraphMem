import uuid
from datetime import datetime, timezone
from api.db.postgres import get_pool
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


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Invalid UUID: '{value}'")
