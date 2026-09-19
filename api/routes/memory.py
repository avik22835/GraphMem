from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter
from pydantic import BaseModel, Field
from api.services import memory as memory_svc
from api.services.sqs import push_node_job
from api.services.graph import recall as graph_recall
from api.models import RecallResult

router = APIRouter()

def _serialize_node(row: dict) -> dict:
    return {
        "memory_id": str(row["memory_id"]),
        "conversation_id": str(row["conversation_id"]),
        "index": row["index"],
        "prompt": row["prompt"],
        "response": row["response"],
        "timestamp_prompt": row["timestamp_prompt"].isoformat() if row.get("timestamp_prompt") else None,
        "timestamp_response": row["timestamp_response"].isoformat() if row.get("timestamp_response") else None,
        "status": row["status"],
        "metadata": dict(row["metadata"]) if row.get("metadata") else {},
    }


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


@router.get("/{memory_id}")
async def get_node(memory_id: str):
    row = await memory_svc.get_node(memory_id)
    return _serialize_node(row)


@router.delete("/{memory_id}", status_code=204)
async def delete_node(memory_id: str):
    await memory_svc.delete_node(memory_id)


@router.get("/{memory_id}/neighbours")
async def get_neighbourhood(memory_id: str):
    neighbours = await memory_svc.get_neighbourhood(memory_id)
    return [
        {**_serialize_node(n), "edge_weight": n["edge_weight"]}
        for n in neighbours
    ]


class BatchItem(BaseModel):
    conversation_id: str
    prompt: str
    response: str
    timestamp_prompt: Optional[datetime] = None
    timestamp_response: Optional[datetime] = None
    metadata: Optional[dict] = {}

class AddBatchRequest(BaseModel):
    items: list[BatchItem] = Field(..., min_length=1, max_length=100)

@router.post("/batch", status_code=201)
async def add_batch(body: AddBatchRequest):
    items = [i.model_dump() for i in body.items]
    memory_ids = await memory_svc.add_batch(items)
    # Push SQS job for each complete node
    for idx, mem_id in enumerate(memory_ids):
        push_node_job(memory_id=mem_id, conversation_id=items[idx]["conversation_id"])
    return {"memory_ids": memory_ids, "count": len(memory_ids)}
