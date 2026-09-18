from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class MemoryNode(BaseModel):
    memory_id: str
    conversation_id: str
    index: int
    prompt: str
    response: Optional[str]
    timestamp_prompt: datetime
    timestamp_response: Optional[datetime]
    status: str                 # "pending" | "complete"
    metadata: dict

    def count_tokens(self, tokenizer) -> int:
        text = (self.prompt or "") + " " + (self.response or "")
        return len(tokenizer.encode(text))


class MemoryNodeWithScore(MemoryNode):
    relevance_score: float
    token_count: int


class RecallResult(BaseModel):
    messages: list[MemoryNodeWithScore]
    text: str                   # formatted as [{"role": ..., "content": ...}] JSON — ready to inject
    total_tokens: int
    strategy_used: str          # "cold_start" | "semantic" | "semantic_recency"
