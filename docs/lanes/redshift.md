# Redshift Lane — Backlog

_Initial file: 2026-04-23. Track work for the dedicated Redshift connector here._

## Shipped (v0 — lane/redshift)

- Dedicated `RedshiftConnector` split from AWS umbrella, registered in `CONNECTOR_MAP` + `PlatformType.redshift`.
- Redshift Data API wrapper (`execute_statement` + pagination).
- Provisioned query-level attribution (`SYS_QUERY_HISTORY` × node_rate × node_count).
- Concurrency Scaling cost (`STL_CONCURRENCY_SCALING_USAGE`, billable seconds past the free tier).
- Serverless per-RPU-hour (`SYS_SERVERLESS_USAGE`) + managed-storage daily proration.
- Spectrum per-TB scanned (`SYS_EXTERNAL_QUERY_DETAIL.total_bytes_external`).
- `describe_clusters` fallback for node type + count.
- `pricing_overrides`: node_hour, serverless_rpu_hour, spectrum_per_tb, managed_storage_gb_month, concurrency_scaling_free_hr_per_day, discount_pct.
- Structured `RedshiftError` with IAM / NotFound / Validation hints.
- 47-test pytest suite; `test_connectors.py` expanded with Redshift instantiation + pricing table tests.
- Platforms page + Setup page (Warehouses category) entries.
- Docs knowledge base: `docs/connectors/redshift.md`.

## Near-term (next 2 weeks)

- [ ] Reserved Node detection via `describe_reserved_nodes` + 1-yr / 3-yr rate flip.
- [ ] Provisioned RA3 managed storage from `SVV_TABLE_INFO` + `STV_NODE_STORAGE_CAPACITY`.
- [ ] Cluster-status timeline via `describe_cluster_events` — zero-out paused days.
- [ ] Filter `result_cache_hit = true` out of compute attribution (emit them as zero-cost metadata rows).
- [ ] Pull cluster-level AWS resource tags → map to `UnifiedCost.team`.

## Medium-term (4-6 weeks)

- [ ] Snapshot cost (manual + retention-window automated).
- [ ] Per-external-table Spectrum breakdown (join `SYS_EXTERNAL_QUERY_DETAIL` to `SYS_QUERY_HISTORY`).
- [ ] Zero-ETL usage split (`query_type = 'ZERO_ETL'`).
- [ ] Regional pricing table (us-east-1 is not global).
- [ ] `SYS_QUERY_TEXT` join for query-fingerprint cost roll-up.
- [ ] Cost Explorer cross-check — flag when connector estimate drifts > 10% from CE.

## Long-term (2-3 months)

- [ ] "Redshift Expert" agent — SQA hit-rate, distribution-key / sort-key advice, RA3 migration ROI, Serverless-vs-provisioned break-even.
- [ ] WLM queue depth from `STV_WLM_QUERY_STATE` + `STV_WLM_QUERY_QUEUE_STATE`.
- [ ] Write-back actions (auto-pause / auto-resize via `modify_cluster`, approval-gated).
- [ ] Unravel-style compression / dist-key advisor.
- [ ] Query-fingerprint dedup on `query_text` hash.

## Open Questions

- Is our Data API IAM policy guidance correct for customers using Secrets Manager vs IAM DB auth? Document both.
- Should we support `host` + `port` + password JDBC fallback for air-gapped clusters? (Current: Data API only.)
- Multi-region customers: one connection per region or auto-discover?
