"""Claude Code usage connector.

Parses local Claude Code session transcripts (JSONL files under
~/.claude/projects/**/*.jsonl) and produces UnifiedCost records with
cache-tier-aware pricing and per-tool-call cost attribution.

Covers subscription (Claude Code Max/Pro) traffic that the Anthropic
Admin API does NOT expose.

Schema of a JSONL assistant entry (as of Claude Code ~2026-04):

    {
      "type": "assistant",
      "timestamp": "2026-03-25T22:46:46.454Z",
      "sessionId": "uuid",
      "cwd": "/abs/path/to/project",
      "gitBranch": "main",
      "requestId": "req_...",
      "message": {
        "model": "claude-opus-4-6",
        "content": [
          {"type": "text", "text": "I'll read that file."},
          {"type": "tool_use", "id": "toolu_...", "name": "Read",
           "input": {"file_path": "/abs/path"}}
        ],
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

Per-tool-call attribution is approximate: JSONLs only record a single
aggregate `output_tokens` per assistant turn, so we weight each content
block by its JSON-serialised character count and split the output cost
proportionally across the tool names that appear in that turn.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
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

# Tool names we consider "built-in" for grouping in the UI. Everything else
# (including MCP servers, prefixed mcp__server__tool) is preserved verbatim
# but can still be filtered/sliced by the caller on `name.startswith("mcp__")`.
BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "Bash",
        "Read",
        "Edit",
        "Write",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "NotebookEdit",
        "TodoWrite",
        "Task",
        "Skill",
    }
)


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


@dataclass(frozen=True)
class ToolAttribution:
    """Per-tool slice of a single assistant turn's output.

    `output_tokens` and `cost_usd` are *approximate* — they share the turn's
    total in proportion to the JSON-serialised size of each tool_use block.
    Pure-text turns have no attribution; those skip the per-tool bucket.
    """

    name: str
    calls: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "ToolAttribution") -> "ToolAttribution":
        if not isinstance(other, ToolAttribution):
            return NotImplemented
        if self.name != other.name:
            raise ValueError(
                f"Cannot add ToolAttribution across tools: {self.name!r} vs {other.name!r}"
            )
        return ToolAttribution(
            name=self.name,
            calls=self.calls + other.calls,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
        )


@dataclass(frozen=True)
class TurnAttribution:
    """All tool-use slices for a single assistant turn."""

    tools: tuple[ToolAttribution, ...] = ()

    @property
    def total_calls(self) -> int:
        return sum(t.calls for t in self.tools)


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


def _content_block_weight(block: dict) -> int:
    """Character weight used to split aggregate output_tokens across blocks.

    For tool_use we count the JSON-serialised length of the input payload
    (that's what the server tokenised). For text/thinking we use the string
    length. Unknown block types get zero weight, which safely excludes them.
    """
    btype = block.get("type")
    if btype == "tool_use":
        payload = block.get("input") or {}
        try:
            return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        except (TypeError, ValueError):
            return 0
    if btype == "text":
        return len(block.get("text") or "")
    if btype == "thinking":
        return len(block.get("thinking") or "")
    return 0


def _attribute_tools(
    content: list[dict],
    output_tokens: int,
    output_cost_usd: float,
) -> TurnAttribution:
    """Split a turn's output_tokens/cost across tool_use blocks by JSON weight.

    Blocks with `type == "tool_use"` compete with text/thinking blocks for a
    share of the aggregate output. Multiple calls to the same tool in one
    turn are merged (`calls` incremented, tokens/cost summed).

    If the turn has no tool_use blocks, returns an empty TurnAttribution.
    """
    if not content or output_tokens <= 0:
        return TurnAttribution()

    weights: list[tuple[dict, int]] = []
    total_weight = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        w = _content_block_weight(block)
        weights.append((block, w))
        total_weight += w

    if total_weight == 0:
        return TurnAttribution()

    by_tool: dict[str, ToolAttribution] = {}
    for block, w in weights:
        if block.get("type") != "tool_use" or w == 0:
            continue
        name = str(block.get("name") or "unknown")
        share = w / total_weight
        tokens = int(round(output_tokens * share))
        cost = round(output_cost_usd * share, 6)
        existing = by_tool.get(name)
        if existing is None:
            by_tool[name] = ToolAttribution(
                name=name, calls=1, output_tokens=tokens, cost_usd=cost
            )
        else:
            by_tool[name] = ToolAttribution(
                name=name,
                calls=existing.calls + 1,
                output_tokens=existing.output_tokens + tokens,
                cost_usd=round(existing.cost_usd + cost, 6),
            )

    if not by_tool:
        return TurnAttribution()

    return TurnAttribution(tools=tuple(sorted(by_tool.values(), key=lambda t: t.name)))


def _parse_turn(
    raw: dict,
) -> tuple[datetime, str, str, str | None, TokenUsage, TurnAttribution] | None:
    """Extract (timestamp, session_id, model, cwd, usage, tool_attr) from one JSONL row.

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

    # Output-only cost (for per-tool split). Cache + input costs stay on the
    # parent turn — they're a consequence of the prompt, not the tool calls.
    price = _resolve_pricing(model)
    output_cost_usd = round(usage.output_tokens * price["output"] / 1_000_000.0, 6)
    content = message.get("content")
    if not isinstance(content, list):
        content = []
    tool_attr = _attribute_tools(content, usage.output_tokens, output_cost_usd)

    return ts, session_id, model, cwd, usage, tool_attr


def iter_jsonl_turns(
    projects_dir: Path,
) -> Iterator[tuple[datetime, str, str, str | None, str, TokenUsage, TurnAttribution]]:
    """Yield one tuple per assistant turn: (ts, session, model, cwd, project_dir_name, usage, tool_attr)."""
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
                        ts, session_id, model, cwd, usage, tool_attr = parsed
                        yield ts, session_id, model, cwd, project_path.name, usage, tool_attr
            except OSError:
                continue


@dataclass
class _Bucket:
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    tool_cost: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    tool_calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _build_tool_breakdown(bucket: _Bucket) -> dict[str, dict[str, float]]:
    """Serialise a bucket's per-tool attribution into metadata-friendly dicts."""
    out: dict[str, dict[str, float]] = {}
    for name in sorted(bucket.tool_tokens.keys()):
        out[name] = {
            "calls": int(bucket.tool_calls[name]),
            "output_tokens": int(bucket.tool_tokens[name]),
            "cost_usd": round(bucket.tool_cost[name], 6),
            "is_mcp": name.startswith("mcp__"),
            "is_builtin": name in BUILTIN_TOOL_NAMES,
        }
    return out


def aggregate_costs(
    turns: Iterable[tuple[datetime, str, str, str | None, str, TokenUsage, TurnAttribution]],
    since: datetime | None = None,
) -> list[UnifiedCost]:
    """Aggregate per-turn tuples into UnifiedCost records, one per (day, project, model).

    Each record carries a `tool_breakdown` in `metadata` keyed by tool name
    (Bash, Read, mcp__foo__bar, ...) mapped to {calls, output_tokens, cost_usd,
    is_mcp, is_builtin}. Turns without tool_use contribute to the record but
    do not add to the breakdown.
    """
    buckets: dict[tuple[str, str, str], _Bucket] = defaultdict(_Bucket)
    cwd_by_project: dict[str, str] = {}

    for ts, _session_id, model, cwd, project_dir_name, usage, tool_attr in turns:
        if since is not None and ts < since:
            continue
        date_key = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        project = project_name_from_cwd(cwd, project_dir_name)
        key = (date_key, project, model)
        bucket = buckets[key]
        bucket.usage = bucket.usage + usage
        for tool in tool_attr.tools:
            bucket.tool_tokens[tool.name] += tool.output_tokens
            bucket.tool_cost[tool.name] += tool.cost_usd
            bucket.tool_calls[tool.name] += tool.calls
        if cwd and project not in cwd_by_project:
            cwd_by_project[project] = cwd

    results: list[UnifiedCost] = []
    for (date_key, project, model), bucket in sorted(buckets.items()):
        cost = estimate_cost(model, bucket.usage)
        if cost <= 0:
            continue
        tool_breakdown = _build_tool_breakdown(bucket)
        results.append(
            UnifiedCost(
                date=date_key,
                platform="claude_code",
                service="claude_code",
                resource=model,
                category=CostCategory.ai_inference,
                cost_usd=cost,
                usage_quantity=bucket.usage.total,
                usage_unit="tokens",
                team=project,
                metadata={
                    "model": model,
                    "project": project,
                    "cwd": cwd_by_project.get(project),
                    "input_tokens": bucket.usage.input_tokens,
                    "output_tokens": bucket.usage.output_tokens,
                    "cache_read_tokens": bucket.usage.cache_read_tokens,
                    "cache_write_5m_tokens": bucket.usage.cache_write_5m_tokens,
                    "cache_write_1h_tokens": bucket.usage.cache_write_1h_tokens,
                    "tool_breakdown": tool_breakdown,
                    "tool_calls_total": sum(bucket.tool_calls.values()),
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
