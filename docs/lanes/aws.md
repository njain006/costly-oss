# Lane: AWS — Backlog

Running backlog for the AWS connector lane. Tick items as they ship.
The deep knowledge base lives in [`docs/connectors/aws.md`](../connectors/aws.md).

## Shipped (this lane)

- [x] **AmortizedCost toggle** — `cost_type` credential, valid set
      `{UnblendedCost, AmortizedCost, BlendedCost, NetUnblendedCost,
      NetAmortizedCost}`. AmortizedCost also pulls UnblendedCost to surface
      `amortized_delta_usd` on every row. (`aws_connector.py`)
- [x] **Tag allocation** — `cost_allocation_tag_keys` credential (CSV or list).
      Each matching service row carries a `tag_breakdown` dict keyed
      `"<tag>:<value>"`. One CE call per tag key (CE allows max 2 GroupBy
      clauses). (`aws_connector.py`)
- [x] **Multi-account STS AssumeRole** — `member_account_role_arns` +
      `external_id` credentials. Each member account yields its own rows
      with `account_id` / `account_name` metadata. A failing AssumeRole
      skips the account without aborting the sync.
- [x] **Frontend `By Account` panel** on the overview page. Renders the
      existing (but previously unused) `by_account` field from
      `/api/platforms/costs`. Demo data updated so the panel is visible
      in demo mode.
- [x] **Parametrised tests** — `tests/test_aws_connector.py` covers
      1 / 2 / 5 accounts, AmortizedCost delta, tag breakdown, assume-role
      failure fallback, and regression guards.

## Next up (quick wins)

- [ ] Expose `RECORD_TYPE` filter to strip / split Credits and Refunds
      (default-on to avoid misleading trend lines).
- [ ] Pull `GetSavingsPlansCoverage` / `GetSavingsPlansUtilization` and
      `GetReservationCoverage` / `GetReservationUtilization`; surface as
      four KPIs on the AWS platform page.
- [ ] Daily cache layer around Cost Explorer — every `get_cost_and_usage`
      call is $0.01, dashboard hits should not each pay that.
- [ ] Extend `SERVICE_CATEGORY_MAP` and `SERVICE_DISPLAY_NAMES` to cover
      the next tier of services that routinely show up in customer accounts:
      Config, CloudTrail, Textract, Comprehend, Rekognition, Translate,
      Transcribe, OpenSearch Service, Secrets Manager, KMS, GuardDuty,
      Inspector, Shield, WAF, CloudFront, API Gateway, AppSync, SNS, SES.
- [ ] Bedrock granularity — break out Bedrock Agents, Bedrock Knowledge
      Bases, Bedrock Guardrails, and Provisioned Throughput as separate
      display-name rows once `UsageType` is exposed.
- [ ] Q Developer (Amazon Q) — distinct line item once AWS exposes it.

## Medium term

- [ ] **CUR 2.0 / FOCUS Athena path** — accept an S3 prefix + Athena
      workgroup; query directly for resource-level detail + marketplace
      passthroughs. Cost Explorer stays the default for new customers.
- [ ] Anomaly detection: integrate `GetAnomalies` from AWS Cost Anomaly
      Detection (zero-setup), plus our own 7-day moving-average rule as a
      secondary signal.
- [ ] Rightsizing: wire `GetRightsizingRecommendation` + Compute Optimizer.
- [ ] Commitment recommendations: `GetSavingsPlansPurchaseRecommendation`
      and `GetReservationPurchaseRecommendation` → UI cards.
- [ ] NAT Gateway + Data Transfer breakdown via `USAGE_TYPE`.
- [ ] Hourly granularity for the last 14 days, gated behind a flag.
- [ ] Inventory enrichment for RDS, DynamoDB, ElastiCache, OpenSearch,
      MSK, SageMaker endpoints, EKS clusters, ECS services.

## Long term

- [ ] FOCUS 1.2 conformance across all platforms (AWS, Azure, GCP,
      Snowflake, Databricks) so the unified store speaks one schema.
- [ ] Kubernetes allocation via OpenCost + CUR 2.0 Split Cost Allocation.
- [ ] Cost categories + custom allocation rules (CloudZero-style).
- [ ] Forecasting (Prophet) with confidence intervals.
- [ ] Unit economics: cost per {API-call, user, GB-processed, trained-model}.
- [ ] Remediation actions via Cloud Custodian with an approval gate.
- [ ] Bedrock governance module (per-team / per-model / per-prompt).
- [ ] Marketplace split — Databricks / Snowflake / Mongo subscribed
      through AWS Marketplace as first-class line items.

## Notes

- Grade trajectory: **C+ → B**. Three of the five biggest gaps from the
  KB (AmortizedCost, tag allocation, multi-account fan-out) are now
  closed; frontend multi-account rendering is live. CUR 2.0 / FOCUS and
  the missing service coverage are the remaining B → A levers.
- Tests: `cd backend && pytest tests/test_aws_connector.py
  tests/test_connectors.py -x -q` — currently 109 passed, 3 skipped.
