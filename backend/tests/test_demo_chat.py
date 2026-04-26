"""Tests for ``generate_demo_chat_sample`` — seeded conversation used by the
``/api/demo/chat/sample`` endpoint.

Chat page first-time visitors see this sample so they get an immediate sense
of what the agent does without having to ask a question.
"""
from __future__ import annotations

import pytest

from app.services.demo import generate_demo_chat_sample


class TestEnvelope:
    def test_top_level_keys(self):
        result = generate_demo_chat_sample()
        assert {"conversation_id", "title", "created_at", "messages"} <= result.keys()

    def test_has_user_and_assistant_turns(self):
        result = generate_demo_chat_sample()
        roles = [m["role"] for m in result["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_at_least_two_user_messages(self):
        """Demonstrates a back-and-forth, not a single Q&A."""
        result = generate_demo_chat_sample()
        users = [m for m in result["messages"] if m["role"] == "user"]
        assert len(users) >= 2


class TestAssistantMessages:
    def test_assistant_messages_have_expert_label(self):
        result = generate_demo_chat_sample()
        assistants = [m for m in result["messages"] if m["role"] == "assistant"]
        for m in assistants:
            assert m.get("expert")
            assert m.get("expert_name")

    def test_at_least_one_assistant_has_artifacts(self):
        """Inline chart / table artifact makes the agent look capable."""
        result = generate_demo_chat_sample()
        assistants = [m for m in result["messages"] if m["role"] == "assistant"]
        with_artifacts = [m for m in assistants if m.get("artifacts")]
        assert with_artifacts, "expected at least one assistant turn with artifacts"

    def test_artifact_shapes(self):
        result = generate_demo_chat_sample()
        for msg in result["messages"]:
            for art in msg.get("artifacts", []) or []:
                assert "type" in art
                assert "title" in art
                if art["type"] == "chart":
                    assert "chart_type" in art
                    assert "data" in art
                    assert isinstance(art["data"], list) and art["data"]
                elif art["type"] == "table":
                    assert "columns" in art
                    assert "rows" in art


class TestDeterminism:
    def test_two_calls_identical_except_timestamp(self):
        """``created_at`` uses ``datetime.utcnow`` so it may differ by a few µs.
        The rest of the payload must be identical.
        """
        a = generate_demo_chat_sample()
        b = generate_demo_chat_sample()
        a.pop("created_at")
        b.pop("created_at")
        assert a == b
