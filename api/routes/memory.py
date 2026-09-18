from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter
from pydantic import BaseModel, Field
from api.services import memory as memory_svc
from api.services.sqs import push_node_job
from api.services.graph import recall as graph_recall
from api.models import RecallResult

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

class RecallRequest(BaseModel):
    conversation_id: str
    query: str
    k: Optional[int] = Field(None, ge=1, le=50)
    threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    strategy: Literal["semantic", "semantic_recency"] = "semantic"
    recency_alpha: float = Field(0.7, ge=0.0, le=1.0)
    recency_half_life: Optional[float] = Field(None, gt=0)
    always_include_recent: int = Field(0, ge=0, le=20)
    max_tokens: Optional[int] = Field(None, ge=1)


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
    push_node_job(memory_id=memory_id, conversation_id=body.conversation_id)
    return {"status": "queued", "memory_id": memory_id}


@router.post("/recall", response_model=RecallResult)
async def recall(body: RecallRequest):
    return await graph_recall(
        conversation_id=body.conversation_id,
        query=body.query,
        k=body.k,
        threshold=body.threshold,
        strategy=body.strategy,
        recency_alpha=body.recency_alpha,
        recency_half_life=body.recency_half_life,
        always_include_recent=body.always_include_recent,
        max_tokens=body.max_tokens,
    )


# Block 5: get, delete, neighbourhood, stats, export, add_batch, count_tokens
