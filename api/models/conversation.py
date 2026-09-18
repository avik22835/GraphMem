from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class Conversation(BaseModel):
    conversation_id: str
    metadata: dict
    node_count: int
    last_topic_recompute: Optional[datetime]
    created_at: datetime
