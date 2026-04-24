"""Claude Code usage connector.

Parses local Claude Code session transcripts (JSONL files under
~/.claude/projects/**/*.jsonl) and produces UnifiedCost records with
cache-tier-aware pricing.

Covers subscription (Claude Code Max/Pro) traffic that the Anthropic
Admin API does NOT expose.

Schema of a JSONL assistant entry (as of Claude Code ~2026-04):

    {
      "type": "assistant",
      "timestamp": "2026-03-25T22:46:46.454Z",
      "sessionId": "uuid",
      "cwd": "/abs/path/to/project",
      "gitBranch": "main",
      "message": {
        "model": "claude-opus-4-6",
        "usage": {
          "input_tokens": 3,
          "output_tokens": 512,
          "cache_read_input_tokens": 0,
          "cache_creation_input_tokens": 39655,
          "cache_creation": {
            "ephemeral_5m_input_tokens": 0,
            "ephemeral_1h_input_tokens": 39655
          },
          "service_tier": "standard"
        }
      }
    }
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from app.models.platform import CostCategory, UnifiedCost
from app.services.connectors.base import BaseConnector

# Pricing per million tokens — list-price (USD) for the tiers costly tracks.
# Cache tiers derived from input price:
#   cache_read        = 0.10 × input  (90% discount)
#   cache_write (5m)  = 1.25 × input  (25% premium)
#   cache_write (1h)  = 2.00 × input  (100% premium)
#
# Keep the longest prefixes first: the matcher iterates ordered by length.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4.x family
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-haiku-4": {"input": 1.0, "output": 5.0},
    # Legacy 3.x
    "claude-opus-3-5": {"input": 15.0, "output": 75.0},
    "claude-sonnet-3-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.0},
    "claude-haiku-3": {"input": 0.25, "output": 1.25},
}

CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.00

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class TokenUsage:
    """Token counts for a single assistant turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_5m_tokens
            + self.cache_write_1h_tokens
        )

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_5m_tokens=self.cache_write_5m_tokens + other.cache_write_5m_tokens,
            cache_write_1h_tokens=self.cache_write_1h_tokens + other.cache_write_1h_tokens,
        )


def _resolve_pricing(model: str) -> dict[str, float]:
    """Resolve list-price for a model name, preferring longer-prefix matches.

    Falls back to Sonnet-tier pricing for unknown models.
    """
    for key in sorted(MODEL_PRICING.keys(), key=len, reverse=True):
        if key in model:
            return MODEL_PRICING[key]
    return {"input": 3.0, "output": 15.0}


def estimate_cost(model: str, usage: TokenUsage) -> float:
    """Compute USD cost for a turn given tokenized usage.

    Cache writes are charged at a premium over list-price input;
    cache reads are discounted. All numbers are rounded to 6 decimals.
    """
    price = _resolve_pricing(model)
    per_million = 1_000_000.0
    cost = (
        usage.input_tokens * price["input"] / per_million
        + usage.output_tokens * price["output"] / per_million
        + usage.cache_read_tokens
        * price["input"]
        * CACHE_READ_MULTIPLIER
        / per_million
        + usage.cache_write_5m_tokens
        * price["input"]
        * CACHE_WRITE_5M_MULTIPLIER
        / per_million
        + usage.cache_write_1h_tokens
        * price["input"]
        * CACHE_WRITE_1H_MULTIPLIER
        / per_million
    )
    return round(cost, 6)


def project_name_from_cwd(cwd: str | None, fallback_dir_name: str) -> str:
    """Pick a human-readable project identifier.

    `cwd` is an absolute path recorded by Claude Code. When missing (older
    transcripts), fall back to the directory name Claude Code derived from
    the cwd (e.g. `-Users-jain-src-career-ops`) with leading dashes stripped.
    """
    if cwd:
        name = Path(cwd).name
        if name:
            return name
    return fallback_dir_name.lstrip("-")


def _parse_turn(raw: dict) -> tuple[datetime, str, str, str | None, TokenUsage] | None:
    """Extract (timestamp, session_id, model, cwd, usage) from one JSONL row.

    Returns None for rows we don't care about (user messages, attachments,
    system events, or assistant turns with no token usage).
    """
    if raw.get("type") != "assistant":
        return None

    message = raw.get("message") or {}
    usage_raw = message.get("usage") or {}
    if not usage_raw:
        return None

    timestamp_raw = raw.get("timestamp")
    if not timestamp_raw:
        return None
    try:
        ts = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
    except ValueError:
        return None

    session_id = raw.get("sessionId") or ""
    model = message.get("model") or "unknown"
    cwd = raw.get("cwd")

    cache_creation = usage_raw.get("cache_creation") or {}
    cache_5m = int(cache_creation.get("ephemeral_5m_input_tokens") or 0)
    cache_1h = int(cache_creation.get("ephemeral_1h_input_tokens") or 0)

    # Some Claude Code versions only emit the flat cache_creation_input_tokens
    # field. Treat that as a 5m write if we don't have the nested breakdown.
    if not cache_creation:
        cache_5m = int(usage_raw.get("cache_creation_input_tokens") or 0)
        cache_1h = 0

    usage = TokenUsage(
        input_tokens=int(usage_raw.get("input_tokens") or 0),
        output_tokens=int(usage_raw.get("output_tokens") or 0),
        cache_read_tokens=int(usage_raw.get("cache_read_input_tokens") or 0),
        cache_write_5m_tokens=cache_5m,
        cache_write_1h_tokens=cache_1h,
    )

    if usage.total == 0:
        return None

    return ts, session_id, model, cwd, usage


def iter_jsonl_turns(
    projects_dir: Path,
) -> Iterator[tuple[datetime, str, str, str | None, str, TokenUsage]]:
    """Yield one tuple per assistant turn: (ts, session, model, cwd, project_dir_name, usage)."""
    if not projects_dir.exists():
        return
    for project_path in sorted(projects_dir.iterdir()):
        if not project_path.is_dir():
            continue
        for jsonl_path in sorted(project_path.glob("*.jsonl")):
            try:
                with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        parsed = _parse_turn(raw)
                        if parsed is None:
                            continue
                        ts, session_id, model, cwd, usage = parsed
                        yield ts, session_id, model, cwd, project_path.name, usage
            except OSError:
                continue


def aggregate_costs(
    turns: Iterable[tuple[datetime, str, str, str | None, str, TokenUsage]],
    since: datetime | None = None,
) -> list[UnifiedCost]:
    """Aggregate per-turn tuples into UnifiedCost records, one per (day, project, model)."""
    buckets: dict[tuple[str, str, str], TokenUsage] = defaultdict(TokenUsage)
    cwd_by_project: dict[str, str] = {}

    for ts, _session_id, model, cwd, project_dir_name, usage in turns:
        if since is not None and ts < since:
            continue
        date_key = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        project = project_name_from_cwd(cwd, project_dir_name)
        buckets[(date_key, project, model)] += usage
        if cwd and project not in cwd_by_project:
            cwd_by_project[project] = cwd

    results: list[UnifiedCost] = []
    for (date_key, project, model), usage in sorted(buckets.items()):
        cost = estimate_cost(model, usage)
        if cost <= 0:
            continue
        results.append(
            UnifiedCost(
                date=date_key,
                platform="claude_code",
                service="claude_code",
                resource=model,
                category=CostCategory.ai_inference,
                cost_usd=cost,
                usage_quantity=usage.total,
                usage_unit="tokens",
                team=project,
                metadata={
                    "model": model,
                    "project": project,
                    "cwd": cwd_by_project.get(project),
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_5m_tokens": usage.cache_write_5m_tokens,
                    "cache_write_1h_tokens": usage.cache_write_1h_tokens,
                },
            )
        )
    return results


class ClaudeCodeConnector(BaseConnector):
    """Claude Code subscription/API usage, parsed from local JSONL."""

    platform = "claude_code"

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        projects_dir = credentials.get("projects_dir") if credentials else None
        self.projects_dir = Path(projects_dir).expanduser() if projects_dir else DEFAULT_PROJECTS_DIR

    def test_connection(self) -> dict:
        if not self.projects_dir.exists():
            return {
                "success": False,
                "message": f"Projects directory not found: {self.projects_dir}",
            }
        jsonl_files = list(self.projects_dir.glob("*/*.jsonl"))
        if not jsonl_files:
            return {
                "success": False,
                "message": f"No Claude Code session files found under {self.projects_dir}",
            }
        return {
            "success": True,
            "message": f"Found {len(jsonl_files)} session file(s) in {self.projects_dir}",
        }

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        return aggregate_costs(iter_jsonl_turns(self.projects_dir), since=since)
