from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}, ...]
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    demo: bool = False
    session_id: str


class ChatStreamRequest(BaseModel):
    messages: list[dict]
    session_id: Optional[str] = None


class SessionSummary(BaseModel):
    id: str
    preview: str
    created_at: str
