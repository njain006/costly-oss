"""Chat session persistence — stores conversation history in MongoDB."""

import uuid
from datetime import datetime

from app.database import db

HISTORY_LIMIT = 20  # Max messages to load from history


async def create_session(user_id: str, first_message: str) -> str:
    """Create a new chat session and return its ID."""
    session_id = str(uuid.uuid4())
    await db.chat_sessions.insert_one({
        "user_id": user_id,
        "session_id": session_id,
        "messages": [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "preview": first_message[:100],
    })
    return session_id


async def load_session_messages(user_id: str, session_id: str) -> list[dict] | None:
    """Load the last N messages from a session. Returns None if session not found."""
    session = await db.chat_sessions.find_one(
        {"user_id": user_id, "session_id": session_id}
    )
    if not session:
        return None
    messages = session.get("messages", [])
    # Return only the last HISTORY_LIMIT messages
    return messages[-HISTORY_LIMIT:]


async def append_messages(user_id: str, session_id: str, messages: list[dict]):
    """Append messages to an existing session."""
    now = datetime.utcnow().isoformat()
    # Add timestamps to messages that don't have them
    for msg in messages:
        if "timestamp" not in msg:
            msg["timestamp"] = now

    await db.chat_sessions.update_one(
        {"user_id": user_id, "session_id": session_id},
        {
            "$push": {"messages": {"$each": messages}},
            "$set": {"updated_at": now},
        },
    )


async def list_sessions(user_id: str) -> list[dict]:
    """List all sessions for a user, newest first."""
    cursor = db.chat_sessions.find(
        {"user_id": user_id},
        {"session_id": 1, "preview": 1, "created_at": 1, "_id": 0},
    ).sort("created_at", -1)
    return await cursor.to_list(length=100)


async def delete_session(user_id: str, session_id: str) -> bool:
    """Delete a session. Returns True if deleted."""
    result = await db.chat_sessions.delete_one(
        {"user_id": user_id, "session_id": session_id}
    )
    return result.deleted_count > 0
