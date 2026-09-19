from typing import Optional, Literal
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from api.services import topics as topic_svc
from api.models import TopicRetrievalResult

router = APIRouter()


# ── Request schemas ───────────────────────────────────────────────────────────

class RetrieveByTopicsRequest(BaseModel):
    conversation_id: str
    query: str
    top_n: int = Field(3, ge=1, le=20)
    max_tokens: Optional[int] = Field(None, ge=1)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_topics(
    conversation_id: str = Query(...),
    status: Optional[Literal["active", "dormant", "resolved"]] = Query(None),
):
    return await topic_svc.list_topics(conversation_id, status=status)


@router.get("/current")
async def current_topic(
    conversation_id: str = Query(...),
    mode: Literal["centroid", "hybrid", "llm"] = Query("centroid"),
):
    result = await topic_svc.current_topic(conversation_id, mode=mode)
    if result is None:
        return {"message": "No topics found — conversation may be in cold start"}
    return result


@router.get("/relevance")
async def topic_relevance(
    conversation_id: str = Query(...),
    query: str = Query(...),
    top_n: int = Query(3, ge=1, le=20),
):
    return await topic_svc.topic_relevance(conversation_id, query, top_n=top_n)


@router.post("/retrieve", response_model=TopicRetrievalResult)
async def retrieve_by_topics(body: RetrieveByTopicsRequest):
    return await topic_svc.retrieve_by_topics(
        conversation_id=body.conversation_id,
        query=body.query,
        top_n=body.top_n,
        max_tokens=body.max_tokens,
    )


@router.post("/recompute", status_code=202)
async def recompute_topics(conversation_id: str = Query(...)):
    await topic_svc.recompute_topics(conversation_id)
    return {"status": "accepted", "message": "Topic recompute queued"}


@router.get("/{topic_id}")
async def topic_info(topic_id: str):
    return await topic_svc.topic_info(topic_id)


@router.get("/{topic_id}/summary")
async def topic_summary(topic_id: str):
    return await topic_svc.topic_summary(topic_id)


@router.get("/{topic_id}/status")
async def topic_status(topic_id: str):
    return await topic_svc.topic_status(topic_id)


@router.get("/{topic_id}/messages", response_model=TopicRetrievalResult)
async def retrieve_by_topic(
    topic_id: str,
    conversation_id: str = Query(...),
    query: Optional[str] = Query(None),
    max_tokens: Optional[int] = Query(None, ge=1),
):
    return await topic_svc.retrieve_by_topic(
        conversation_id=conversation_id,
        topic_id=topic_id,
        query=query,
        max_tokens=max_tokens,
    )
