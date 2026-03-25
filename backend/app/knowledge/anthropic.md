# Anthropic Billing & Cost Expert Knowledge Base

## Pricing Model

Token-based billing. Input/output priced separately. Extended thinking tokens billed as output.

### Current Model Pricing (per 1M tokens)
| Model | Input | Output | Context |
|-------|-------|--------|---------|
| Claude Opus 4 | $15.00 | $75.00 | 200K |
| Claude Sonnet 4 | $3.00 | $15.00 | 200K |
| Claude Haiku 3.5 | $0.80 | $4.00 | 200K |

### Prompt Caching (Major Cost Saver)
- Cached input tokens: 90% discount (only 10% of regular input price)
- Cache write: 25% premium on first write
- Cache TTL: 5 minutes (extended on each cache hit)
- **Best for:** System prompts, long documents, few-shot examples
- Breakeven: If prompt is reused 2+ times within 5 minutes

### Batch API
- 50% discount on both input and output
- 24-hour processing window
- Best for: bulk classification, evaluation, data processing

## Cost Optimization Strategies

1. **Prompt caching** — Cache system prompts and reference docs (90% savings on cached portion)
2. **Model routing** — Haiku for classification/extraction ($0.80 vs $15.00 input)
3. **Batch API** — For non-real-time workloads (50% off)
4. **Extended thinking control** — Set budget_tokens to limit thinking costs
5. **Max tokens** — Always set to prevent runaway output

## Common Cost Problems

### 1. "Opus costs are out of control"
- Extended thinking can generate 10x more tokens than the visible output
- Each thinking token billed at output rate ($75/1M for Opus)
- Fix: Use budget_tokens parameter, route simple tasks to Haiku

### 2. "Not using prompt caching"
- Every request sends the full system prompt as new input
- Fix: Use cache_control breakpoints on static content

## Admin API for Usage
- Endpoint: `/v1/organizations/usage`
- Requires admin API key (from console.anthropic.com > Organization Settings)
- Granularity: daily
- Group by: model
- Regular API keys cannot access usage data

## Extended Thinking Deep Dive
- Thinking tokens are billed as OUTPUT tokens at full rate
- Opus thinking at $75/1M output tokens can be very expensive
- A complex reasoning task might generate 10,000 thinking tokens = $0.75 per request on Opus
- **Budget control:** Use `budget_tokens` parameter to cap thinking
  - `budget_tokens: 5000` limits to 5K thinking tokens max
  - Minimum: 1,024 tokens
- **Streaming:** Thinking tokens are streamed in `thinking` content blocks — monitor in real-time

## Token Counting
- Use `/v1/messages/count_tokens` endpoint to estimate costs before sending
- System prompts, tools, and conversation history all count as input tokens
- Tool use results count as input tokens in the next turn

## Message Batches API
- 50% discount on both input and output tokens
- Results available within 24 hours (often faster)
- Max 100,000 requests per batch
- Separate rate limits from real-time API
- **Best for:** Evaluation runs, data processing, bulk classification

## Prompt Caching Economics
Calculate breakeven:
```
cache_write_cost = tokens * input_price * 1.25  (25% premium)
cache_read_cost = tokens * input_price * 0.10   (90% discount)
regular_cost = tokens * input_price * 1.00

breakeven_queries = cache_write_cost / (regular_cost - cache_read_cost)
                  = 1.25 / (1.0 - 0.1) = 1.39 → 2 queries
```
**Rule of thumb:** If you'll send the same context 2+ times in 5 minutes, use caching.

## Model Comparison for Cost Routing
| Task Type | Recommended Model | Why |
|-----------|------------------|-----|
| Classification, extraction | Haiku 3.5 ($0.80/$4.00) | 90% cheaper than Sonnet, sufficient for structured tasks |
| General coding, writing | Sonnet 4 ($3.00/$15.00) | Best balance of quality and cost |
| Complex reasoning, research | Opus 4 ($15.00/$75.00) | Only when Sonnet quality is insufficient |
| High-volume processing | Haiku 3.5 + Batch ($0.40/$2.00) | Batch + cheapest model = minimum cost |
