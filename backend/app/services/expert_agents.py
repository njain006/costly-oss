"""Platform-specific expert agent system.

Each platform gets a dedicated AI expert loaded with deep billing/pricing
knowledge scraped from official docs, competitor tools (Select.dev, etc.),
and community forums.

The main agent routes questions to the right expert based on platform context.
"""

import os
from pathlib import Path

# ── Knowledge Base Loading ────────────────────────────────────────────────────

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

_knowledge_cache: dict[str, str] = {}


def load_knowledge(platform: str) -> str:
    """Load the knowledge base for a platform from markdown files."""
    if platform in _knowledge_cache:
        return _knowledge_cache[platform]

    knowledge_file = KNOWLEDGE_DIR / f"{platform}.md"
    if knowledge_file.exists():
        content = knowledge_file.read_text()
        _knowledge_cache[platform] = content
        return content

    return ""


def reload_knowledge():
    """Clear the knowledge cache to pick up file changes."""
    _knowledge_cache.clear()


# ── Expert System Prompts ─────────────────────────────────────────────────────

def get_expert_system_prompt(platform: str) -> str:
    """Build the full system prompt for a platform expert agent."""
    knowledge = load_knowledge(platform)
    expert_name = EXPERT_NAMES.get(platform, f"{platform} Expert")
    base_prompt = EXPERT_BASE_PROMPTS.get(platform, DEFAULT_EXPERT_PROMPT)

    return f"""You are the {expert_name} within the Costly AI platform. You are THE expert on {platform} billing, pricing, cost optimization, and usage patterns.

{base_prompt}

## Your Knowledge Base

The following is your deep knowledge about {platform} billing and cost optimization. Use this to provide specific, accurate answers. When you reference billing rules or rates, cite them from this knowledge:

{knowledge}

## Response Guidelines

- Always ground answers in the user's actual data (use tools to fetch it)
- When discussing costs, ALWAYS convert credits/tokens/units to dollar amounts using the user's actual pricing
- When suggesting optimizations, include estimated dollar savings based on their data
- Be specific — don't say "reduce warehouse size", say "downsize ANALYTICS_WH from Large (8 credits/hr) to Medium (4 credits/hr) — saving ~$X/month based on your utilization of Y%"
- If you detect the user doesn't have custom pricing set, recommend they configure it for accurate cost tracking
- Flag billing gotchas proactively when you see patterns in their data
- Reference specific SQL queries from your knowledge base when the user needs to investigate further
"""


EXPERT_NAMES = {
    "snowflake": "Snowflake Cost Expert",
    "aws": "AWS Cost Expert",
    "openai": "OpenAI Cost Expert",
    "anthropic": "Anthropic Cost Expert",
    "dbt_cloud": "dbt Cloud Cost Expert",
    "databricks": "Databricks Cost Expert",
    "fivetran": "Fivetran Cost Expert",
    "gcp": "BigQuery Cost Expert",
    "looker": "Looker Cost Expert",
    "tableau": "Tableau Cost Expert",
    "github": "GitHub Actions Cost Expert",
    "gitlab": "GitLab CI Cost Expert",
    "airbyte": "Airbyte Cost Expert",
    "monte_carlo": "Monte Carlo Cost Expert",
    "gemini": "Gemini Cost Expert",
}

EXPERT_BASE_PROMPTS = {
    "snowflake": """You specialize in Snowflake cost optimization. You understand:
- Credit-based billing across editions (Standard/Enterprise/Business Critical)
- Warehouse sizing, auto-suspend tuning, and multi-cluster economics
- The cloud services 10% adjustment and how to avoid billable cloud services
- Serverless feature costs (Snowpipe, Tasks, Clustering, MVs, Search Optimization)
- Storage costs (active, time travel, fail-safe) and how to reduce them
- Data transfer costs across regions and clouds
- Resource monitors and budget controls
- Query optimization for cost reduction (spillage, caching, scan efficiency)
- Cortex AI/ML feature billing
- How dbt, Looker, Tableau, and other tools drive Snowflake costs""",

    "aws": """You specialize in AWS cost optimization for data teams. You understand:
- EC2, S3, Redshift, Glue, EMR, SQS, Kinesis, DMS, Lambda pricing
- Enterprise Discount Program (EDP) and how it stacks with RIs/Savings Plans
- Reserved Instances vs Savings Plans trade-offs
- Data transfer costs (cross-AZ, cross-region, NAT Gateway, internet egress)
- Cost allocation tags and organizational billing
- Cost Explorer API and its limitations""",

    "openai": """You specialize in OpenAI API cost optimization. You understand:
- Per-model token pricing (input vs output, GPT-4o vs mini vs o-series)
- Prompt caching (50% savings on cached input tokens)
- Batch API (50% discount, 24hr turnaround)
- Model routing strategies (use cheaper models for simple tasks)
- Token optimization techniques (shorter prompts, max_tokens limits)
- Usage API for monitoring (completions, embeddings, images endpoints)""",

    "anthropic": """You specialize in Anthropic API cost optimization. You understand:
- Per-model token pricing (Opus/Sonnet/Haiku, input vs output)
- Prompt caching (90% discount on cached input, 25% premium on cache write)
- Batch API (50% discount)
- Extended thinking token costs (billed as output tokens)
- Model routing (Haiku for classification, Sonnet for general, Opus for complex)
- Admin API for usage monitoring""",

    "dbt_cloud": """You specialize in dbt Cloud cost optimization. You understand:
- Plan-based pricing (Developer/Team/Enterprise)
- The real cost is warehouse compute, not the dbt Cloud bill itself
- Incremental vs full-refresh economics
- Slim CI with state:modified+ for PR checks
- Warehouse-per-job-type strategies
- Defer to production for CI cost savings""",

    "databricks": """You specialize in Databricks cost optimization. You understand:
- DBU-based billing across SKUs (Interactive $0.55, Automated $0.15, SQL Compute $0.22, Jobs Light $0.10)
- Photon multiplier impact (2.9x automated, 2.0x interactive) — benchmark before enabling
- Cloud infrastructure costs are often 60-85% of total cost (DBUs are only part of the bill)
- Cluster sizing and auto-termination policies
- Interactive vs Jobs cluster SKU savings (73% cheaper on Jobs)
- Delta Live Tables tiering (Core/Pro/Advanced)
- Serverless SQL Warehouse economics
- Spot instances for worker nodes (60-90% savings on cloud infra)
- Unity Catalog governance overhead
- System Tables for billing analysis (system.billing.usage)""",

    "gemini": """You specialize in Google Gemini and Vertex AI cost optimization. You understand:
- AI Studio vs Vertex AI pricing (Vertex adds grounding, tuning, endpoint costs)
- Model tier pricing: Flash-Lite ($0.075), Flash ($0.15), Pro ($1.25) per 1M input tokens
- Thinking token billing at 75% discount vs regular output (but can generate 5-20x visible output)
- Context caching economics (75% input discount, breakeven at 2 queries)
- Multimodal pricing (images ~258 tokens, video ~258 tokens/sec, audio ~32 tokens/sec)
- Token-length pricing tiers (under/over 200K context boundary)
- Grounding with Google Search at $35/1K requests
- Free tier exploitation for low-volume use cases
- Model routing between Flash-Lite, Flash, and Pro based on task complexity""",
}

DEFAULT_EXPERT_PROMPT = """You are a cost optimization expert for this platform. Provide specific, data-driven recommendations based on the user's actual usage patterns."""


# ── Platform Detection ────────────────────────────────────────────────────────

PLATFORM_KEYWORDS = {
    "snowflake": ["snowflake", "warehouse", "credit", "credits", "auto-suspend", "auto_suspend",
                   "cloud services", "time travel", "fail-safe", "clustering", "snowpipe",
                   "metering", "resource monitor"],
    "aws": ["aws", "amazon", "ec2", "s3", "redshift", "glue", "emr", "lambda", "kinesis",
            "sqs", "rds", "edp", "savings plan", "reserved instance"],
    "openai": ["openai", "gpt", "gpt-4", "gpt-4o", "chatgpt", "dall-e", "whisper",
               "embedding", "o1", "o3", "o4"],
    "anthropic": ["anthropic", "claude", "opus", "sonnet", "haiku", "prompt caching"],
    "dbt_cloud": ["dbt", "dbt cloud", "dbt run", "incremental", "full-refresh", "materialization"],
    "databricks": ["databricks", "dbu", "spark", "delta", "unity catalog", "photon"],
    "fivetran": ["fivetran", "mar", "monthly active row", "connector"],
    "gemini": ["gemini", "vertex ai", "vertex", "google ai", "ai studio", "flash-lite",
                "grounding", "gemini pro", "gemini flash"],
    "gcp": ["bigquery", "gcp", "google cloud", "bq", "slots"],
    "looker": ["looker", "lookml", "pdt"],
    "tableau": ["tableau", "viz", "creator", "explorer", "viewer"],
    "github": ["github actions", "github", "workflow", "runner"],
    "gitlab": ["gitlab", "gitlab ci", "pipeline minutes"],
}


def detect_platforms(message: str) -> list[str]:
    """Detect which platforms a user message is about.
    Returns list of platform keys, most relevant first.
    """
    message_lower = message.lower()
    scores: dict[str, int] = {}

    for platform, keywords in PLATFORM_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in message_lower)
        if score > 0:
            scores[platform] = score

    # Sort by score descending
    return sorted(scores, key=lambda p: scores[p], reverse=True)


def get_expert_for_message(messages: list[dict]) -> str | None:
    """Analyze conversation to determine which expert to route to.
    Returns the platform key or None for general queries.
    """
    # Check the latest user message first, then scan history
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                platforms = detect_platforms(content)
                if platforms:
                    return platforms[0]
    return None


# ── Available Knowledge Bases ─────────────────────────────────────────────────

def list_available_experts() -> list[dict]:
    """List all available expert agents and their knowledge status."""
    experts = []
    for platform, name in EXPERT_NAMES.items():
        knowledge = load_knowledge(platform)
        experts.append({
            "platform": platform,
            "name": name,
            "has_knowledge_base": len(knowledge) > 0,
            "knowledge_size": len(knowledge),
        })
    return experts
