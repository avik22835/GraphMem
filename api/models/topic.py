from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SubTheme(BaseModel):
    label: str
    message_ids: list[str]


class Topic(BaseModel):
    topic_id: str
    conversation_id: str
    label: Optional[str]
    description: Optional[str]
    summary: Optional[str]
    coherence: Optional[float]
    is_mixed: bool
    sub_themes: list[SubTheme]
    status: str                     # "active" | "dormant" | "resolved"
    message_ids: list[str]
    message_count: int
    last_active: datetime
    created_at: datetime
    updated_at: datetime
    louvain_resolution: float
    recompute_count: int


class TopicInfo(Topic):
    is_dirty: bool                  # true if any of this topic's nodes were deleted since last recompute
