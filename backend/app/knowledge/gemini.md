# Gemini & Vertex AI Billing & Cost Expert Knowledge Base

## Pricing Model

Google offers Gemini models through two surfaces with different pricing:

### Google AI Studio (Direct API)
Consumer-grade API access. Simpler pricing, no GCP project required for free tier.

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Context |
|-------|----------------------|----------------------|---------|
| Gemini 2.5 Pro | $1.25 (<200K) / $2.50 (>200K) | $10.00 (<200K) / $15.00 (>200K) | 1M |
| Gemini 2.5 Flash | $0.15 (<200K) / $0.30 (>200K) | $0.60 (<200K) / $1.20 (>200K) | 1M |
| Gemini 2.0 Flash | $0.10 | $0.40 | 1M |
| Gemini 2.0 Flash-Lite | $0.075 | $0.30 | 1M |
| Gemini 1.5 Pro | $1.25 (<128K) / $2.50 (>128K) | $5.00 (<128K) / $10.00 (>128K) | 2M |
| Gemini 1.5 Flash | $0.075 (<128K) / $0.15 (>128K) | $0.30 (<128K) / $0.60 (>128K) | 1M |

**Free tier:** Gemini 2.0 Flash and Flash-Lite have generous free tiers (15 RPM, 1M TPM, 1500 RPD).

### Vertex AI (GCP)
Enterprise API with additional GCP markup, more features (grounding, tuning, evaluation).

- Pricing is generally the same as AI Studio for base models
- **Additional Vertex AI costs:**
  - Grounding with Google Search: $35/1K grounding requests
  - Supervised fine-tuning: charged per training token
  - Online prediction endpoints: per-node-hour charges
  - Batch prediction: same token pricing but with throughput guarantees

### Thinking Tokens (Gemini 2.5 Pro/Flash)
- Thinking tokens are billed at a **75% discount** vs regular output tokens
- Gemini 2.5 Pro thinking: $2.50/1M (vs $10.00 for regular output)
- Gemini 2.5 Flash thinking: $0.15/1M (vs $0.60 for regular output)
- **Gotcha:** Thinking can generate 5-20x the visible output tokens. Monitor thinking token usage.

### Context Caching
- Available for Gemini 1.5 Pro and 1.5 Flash
- Cache storage: $1.00/1M tokens per hour (Pro) / $0.025/1M tokens per hour (Flash)
- Cached input tokens: 75% discount (25% of regular input price)
- Minimum cache TTL: 1 minute
- **Best for:** Repeated queries against the same large document/context

### Multimodal Pricing
| Modality | Token Equivalent |
|----------|-----------------|
| Image | ~258 tokens per image (regardless of size) |
| Video | ~258 tokens per second of video |
| Audio | ~32 tokens per second of audio |
| PDF | Varies by page content |

## Cost Optimization Strategies

1. **Model routing** — Flash-Lite ($0.075 input) for classification/extraction, Flash ($0.15) for general tasks, Pro ($1.25) only for complex reasoning
2. **Context caching** — Cache large documents for repeated queries. Breakeven: ~2 queries against the same context
3. **Batch prediction** — Use for non-real-time workloads (bulk processing, evaluation)
4. **Free tier exploitation** — 2.0 Flash free tier covers many low-volume use cases
5. **Token-length pricing tiers** — Stay under 200K input tokens for Pro (saves 50% on input), under 128K for 1.5 models
6. **Thinking budget** — Set `thinking_budget` parameter on 2.5 models to limit thinking token generation

## Common Cost Problems

### 1. "Vertex AI bill much higher than expected"
- Grounding with Google Search at $35/1K requests adds up fast
- Online prediction endpoints running 24/7 even when unused
- Fix: Use batch prediction where possible, disable grounding for non-search queries

### 2. "Using Pro for everything"
- Many tasks (classification, extraction, summarization) work great with Flash
- Flash is 8-17x cheaper than Pro for input tokens
- Fix: Model routing based on task complexity

### 3. "Long context = long bill"
- Gemini's 1M-2M context is impressive but expensive at scale
- Sending 500K tokens per request × 1000 requests/day = significant cost
- Fix: Context caching, document chunking, use context window wisely

### 4. "Thinking tokens eating budget"
- Gemini 2.5 models generate thinking tokens by default
- A "simple" query can generate 5000+ thinking tokens
- Fix: Set `thinking_budget` parameter, use non-thinking models for simple tasks

## Usage Monitoring

### AI Studio
- Dashboard: aistudio.google.com → Usage tab
- API: Limited — no programmatic usage API equivalent to OpenAI/Anthropic

### Vertex AI
```
# GCP Cloud Monitoring for Vertex AI
gcloud monitoring metrics list --filter="metric.type=starts_with('aiplatform.googleapis.com')"

# Billing export to BigQuery
# Enable billing export in GCP Console → Billing → Billing Export
# Query:
SELECT
  service.description,
  sku.description,
  SUM(cost) AS total_cost,
  SUM(usage.amount) AS total_usage,
  usage.unit
FROM `project.dataset.gcp_billing_export_v1_XXXXXX`
WHERE service.description = 'Vertex AI'
  AND DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1, 2, 5
ORDER BY total_cost DESC;
```

## Gemini vs Competitors (Cost Comparison)

For equivalent tasks:
| Task | Gemini | OpenAI | Anthropic |
|------|--------|--------|-----------|
| Simple classification | Flash-Lite: $0.075/$0.30 | GPT-4o-mini: $0.15/$0.60 | Haiku: $0.80/$4.00 |
| General coding/writing | Flash: $0.15/$0.60 | GPT-4o: $2.50/$10.00 | Sonnet: $3.00/$15.00 |
| Complex reasoning | Pro: $1.25/$10.00 | o3: $10.00/$40.00 | Opus: $15.00/$75.00 |

**Gemini is the cheapest option at every tier.** Trade-off is that quality varies by task — benchmark before committing.
