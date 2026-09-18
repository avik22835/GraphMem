from datetime import datetime
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from api.services import memory as memory_svc
from api.services.sqs import push_node_job

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class AddPromptRequest(BaseModel):
    conversation_id: str
    content: str
    timestamp: Optional[datetime] = None
    metadata: Optional[dict] = {}

class AddPromptResponse(BaseModel):
    memory_id: str

class AddResponseRequest(BaseModel):
    conversation_id: str
    content: str
    timestamp: Optional[datetime] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/prompt", response_model=AddPromptResponse, status_code=201)
async def add_prompt(body: AddPromptRequest):
    memory_id = await memory_svc.create_pending_node(
        conversation_id=body.conversation_id,
        content=body.content,
        timestamp=body.timestamp,
        metadata=body.metadata or {},
    )
    return AddPromptResponse(memory_id=memory_id)


@router.post("/{memory_id}/response", status_code=200)
async def add_response(memory_id: str, body: AddResponseRequest):
    await memory_svc.attach_response(
        memory_id=memory_id,
        conversation_id=body.conversation_id,
        content=body.content,
        timestamp=body.timestamp,
    )
    # Node is complete — push to SQS for async embedding + graph insertion
    push_node_job(memory_id=memory_id, conversation_id=body.conversation_id)
    return {"status": "queued", "memory_id": memory_id}


# Block 4: recall()
# Block 5: get, delete, neighbourhood, stats, export, add_batch, count_tokens
