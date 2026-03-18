import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import Optional

from app.deps import get_current_user, get_data_source
from app.services.agent import run_agent, run_agent_stream
from app.services.chat_sessions import (
    create_session, load_session_messages, append_messages,
    list_sessions, delete_session,
)
from app.services.snowflake import get_credit_price
from app.database import db

router = APIRouter(tags=["chat"])
limiter = Limiter(key_func=get_remote_address)

MAX_MESSAGES = 50
MAX_MESSAGE_LENGTH = 10000


# ── Request / Response models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}, ...]
    session_id: Optional[str] = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v):
        if len(v) > MAX_MESSAGES:
            raise ValueError(f"Too many messages. Maximum is {MAX_MESSAGES}.")
        for i, msg in enumerate(v):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > MAX_MESSAGE_LENGTH:
                raise ValueError(
                    f"Message {i} exceeds maximum length of {MAX_MESSAGE_LENGTH} characters."
                )
        return v


class ChatResponse(BaseModel):
    response: str
    demo: bool = False
    session_id: str


class ChatStreamRequest(BaseModel):
    messages: list[dict]
    session_id: Optional[str] = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v):
        if len(v) > MAX_MESSAGES:
            raise ValueError(f"Too many messages. Maximum is {MAX_MESSAGES}.")
        for i, msg in enumerate(v):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > MAX_MESSAGE_LENGTH:
                raise ValueError(
                    f"Message {i} exceeds maximum length of {MAX_MESSAGE_LENGTH} characters."
                )
        return v


class SessionSummary(BaseModel):
    id: str
    preview: str
    created_at: str


# ── Non-streaming chat (backwards compatible, now with session support) ──────

@router.post("/api/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    user_id: str = Depends(get_current_user),
):
    if not body.messages:
        raise HTTPException(400, "Messages cannot be empty")

    source = await get_data_source(user_id)
    credit_price = 3.0
    if source:
        credit_price = await get_credit_price(source)

    # Session handling: load history or create new session
    session_id = body.session_id
    history_messages = []

    if session_id:
        history_messages = await load_session_messages(user_id, session_id)
        if history_messages is None:
            raise HTTPException(404, "Session not found")
    else:
        first_msg = ""
        for m in body.messages:
            if m.get("role") == "user":
                first_msg = m.get("content", "")[:100]
                break
        session_id = await create_session(user_id, first_msg)

    # Prepend history to the current messages
    combined_messages = history_messages + body.messages

    response = await run_agent(combined_messages, source, credit_price, user_id=user_id)

    # Save the new messages + assistant response to the session
    new_messages = []
    for m in body.messages:
        new_messages.append({"role": m["role"], "content": m["content"]})
    new_messages.append({"role": "assistant", "content": response})
    await append_messages(user_id, session_id, new_messages)

    return ChatResponse(response=response, demo=source is None, session_id=session_id)


# ── Streaming chat ───────────────────────────────────────────────────────────

@router.post("/api/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(
    request: Request,
    body: ChatStreamRequest,
    user_id: str = Depends(get_current_user),
):
    if not body.messages:
        raise HTTPException(400, "Messages cannot be empty")

    source = await get_data_source(user_id)
    credit_price = 3.0
    if source:
        credit_price = await get_credit_price(source)

    # Session handling
    session_id = body.session_id
    history_messages = []

    if session_id:
        history_messages = await load_session_messages(user_id, session_id)
        if history_messages is None:
            raise HTTPException(404, "Session not found")
    else:
        first_msg = ""
        for m in body.messages:
            if m.get("role") == "user":
                first_msg = m.get("content", "")[:100]
                break
        session_id = await create_session(user_id, first_msg)

    combined_messages = history_messages + body.messages

    async def event_generator():
        full_response = ""
        async for event in run_agent_stream(
            combined_messages, source, credit_price, user_id=user_id
        ):
            if event["type"] == "text":
                full_response += event["content"]
            yield f"data: {json.dumps(event)}\n\n"

        # Send done event with session_id
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        # Persist messages to session
        new_messages = []
        for m in body.messages:
            new_messages.append({"role": m["role"], "content": m["content"]})
        new_messages.append({"role": "assistant", "content": full_response})
        await append_messages(user_id, session_id, new_messages)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Session management ───────────────────────────────────────────────────────

@router.get("/api/chat/sessions")
async def get_sessions(user_id: str = Depends(get_current_user)):
    """List all chat sessions for the current user."""
    sessions = await list_sessions(user_id)
    return [
        SessionSummary(
            id=s["session_id"],
            preview=s.get("preview", ""),
            created_at=s.get("created_at", ""),
        )
        for s in sessions
    ]


@router.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a chat session."""
    deleted = await delete_session(user_id, session_id)
    if not deleted:
        raise HTTPException(404, "Session not found")
    return {"ok": True}


# ── Daily digest ─────────────────────────────────────────────────────────────

@router.get("/api/chat/digest")
async def get_digest(user_id: str = Depends(get_current_user)):
    """Return the latest daily cost digest for the user."""
    digest = await db.digests.find_one(
        {"user_id": user_id},
        sort=[("date", -1)],
    )
    if not digest:
        # Generate on-demand if none exists yet
        from app.services.cost_digest import generate_daily_digest
        content = await generate_daily_digest(user_id)
        return {"content": content, "generated_at": None, "date": None}

    return {
        "content": digest["content"],
        "generated_at": digest.get("generated_at"),
        "date": digest.get("date"),
    }
