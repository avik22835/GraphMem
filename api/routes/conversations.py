from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from api.services import conversations as conv_svc
from api.models import Conversation
from api.auth.dependencies import require_write

router = APIRouter()


# ── Request schemas ───────────────────────────────────────────────────────────

class CreateConversationRequest(BaseModel):
    metadata: Optional[dict] = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_conversation(body: CreateConversationRequest, _: dict = Depends(require_write)):
    conv_id = await conv_svc.create_conversation(metadata=body.metadata or {})
    return {"conversation_id": conv_id}


@router.get("")
async def list_conversations():
    convs = await conv_svc.list_conversations()
    return [
        {
            "conversation_id": str(c["conversation_id"]),
            "metadata": dict(c["metadata"]) if c["metadata"] else {},
            "node_count": c["node_count"],
            "last_topic_recompute": c["last_topic_recompute"].isoformat() if c["last_topic_recompute"] else None,
            "created_at": c["created_at"].isoformat(),
        }
        for c in convs
    ]


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, _: dict = Depends(require_write)):
    await conv_svc.delete_conversation(conversation_id)


@router.get("/{conversation_id}/stats")
async def get_stats(conversation_id: str):
    return await conv_svc.get_stats(conversation_id)


@router.get("/{conversation_id}/export")
async def export_conversation(conversation_id: str):
    nodes = await conv_svc.export_conversation(conversation_id)
    return JSONResponse(content=nodes)
