import { PLATFORM_REGISTRY } from "./platform-registry";

/** Generate demo data for any platform view */
export function generateDemoViewData(platformKey: string, viewSlug: string, days: number) {
  const registry = PLATFORM_REGISTRY[platformKey];
  if (!registry) return null;

  const view = registry.views.find((v) => v.slug === viewSlug);
  if (!view) return null;

  const scale = days / 30;

  // Generate KPIs from config
  const kpis: Record<string, number> = {};
  for (const kpi of view.kpis) {
    kpis[kpi.key] = generateKpiValue(kpi.format, platformKey, kpi.key, scale);
  }

  // Generate chart data from config
  const charts: Record<string, Record<string, unknown>[]> = {};
  for (const chart of view.charts) {
    charts[chart.key] = generateChartData(chart.type, chart.xKey, chart.yKeys.map((y) => y.key), platformKey, days);
  }

  // Generate table data from config
  const table = generateTableData(view.table.columns, platformKey, viewSlug);

  return { kpis, charts, table, demo: true };
}

function generateKpiValue(format: string, platform: string, key: string, scale: number): number {
  const base = KPI_BASES[platform]?.[key] ?? KPI_FORMAT_DEFAULTS[format] ?? 1000;
  return Math.round(base * scale * (0.85 + Math.random() * 0.3));
}

const KPI_FORMAT_DEFAULTS: Record<string, number> = {
  currency: 5000,
  number: 1500,
  bytes: 500 * 1024 * 1024 * 1024, // 500 GB
  duration: 2500,
  percent: 72,
};

const KPI_BASES: Record<string, Record<string, number>> = {
  snowflake: { total_cost: 8500, total_credits: 3400, total_queries: 45000, active_warehouses: 8, daily_avg: 283, compute_cost: 6800, storage_cost: 1200, avg_duration_ms: 3200, cache_hit_pct: 68, total_spill_gb: 45 * 1024 * 1024 * 1024, total_warehouses: 8, avg_utilization: 42, idle_cost: 1200, total_patterns: 320, top_pattern_cost: 890, cacheable_pct: 35, total_bytes: 2.1e12, storage_cost_2: 450, table_count: 1200, stale_tables: 180, unique_users: 85, total_bytes_scanned: 15e12, failed_queries: 230 },
  aws: { total_cost: 12400, service_count: 14, daily_avg: 413, mom_change: 8.5, cluster_count: 3, node_hours: 2160, storage_gb: 500 * 1024 * 1024 * 1024, job_runs: 450, dpu_hours: 1800, crawler_runs: 120, bucket_count: 45, total_storage: 8e12, request_cost: 340 },
  gcp: { total_cost: 6200, total_tb_processed: 42, slot_hours: 8500, storage_cost: 890, total_jobs: 12000, avg_slot_ms: 4500, total_tb: 42, cache_hit_pct: 55, total_storage: 3.2e12, dataset_count: 28, table_count: 640 },
  databricks: { total_cost: 9800, dbu_consumed: 45000, cluster_hours: 3200, job_runs: 1800, total_jobs: 120, avg_duration: 180000, failure_rate: 3.2 },
  dbt_cloud: { total_cost: 2400, job_runs: 890, avg_duration: 145000, model_count: 380, total_models: 380, avg_run_time: 12000, slowest_model_time: 95000, error_count: 12 },
  fivetran: { total_cost: 1800, mar_used: 2500000, connector_count: 24, sync_count: 4200 },
  airbyte: { total_cost: 950, sync_count: 1800, records_synced: 45000000, connector_count: 12 },
  openai: { total_cost: 3200, total_tokens: 85000000, model_count: 5, daily_avg: 107, total_input: 52000000, total_output: 33000000, input_cost: 1900, output_cost: 1300 },
  anthropic: { total_cost: 2800, total_tokens: 62000000, model_count: 3, daily_avg: 93, total_input: 38000000, total_output: 24000000, input_cost: 1600, output_cost: 1200 },
  gemini: { total_cost: 800, total_tokens: 40000000, model_count: 3, daily_avg: 27 },
  looker: { total_cost: 3600, query_count: 25000, user_count: 85, dashboard_count: 120 },
  tableau: { total_cost: 4200, user_count: 150, view_count: 45000, extract_count: 280 },
  github: { total_cost: 680, total_minutes: 12000, workflow_count: 45, repo_count: 18 },
  gitlab: { total_cost: 520, total_minutes: 8500, pipeline_count: 3200, project_count: 12 },
  monte_carlo: { total_cost: 1500, table_count: 450, incident_count: 28, monitor_count: 120 },
  omni: { total_cost: 1200, query_count: 8000, user_count: 35, dashboard_count: 45 },
};

function generateChartData(
  type: string,
  xKey: string,
  yKeys: string[],
  platform: string,
  days: number,
): Record<string, unknown>[] {
  if (type === "pie") return generatePieData(xKey, yKeys[0], platform);
  if (type === "horizontal-bar") return generateBarItems(xKey, yKeys[0], platform);
  return generateTimeSeries(xKey, yKeys, days, platform);
}

function generateTimeSeries(xKey: string, yKeys: string[], days: number, platform: string): Record<string, unknown>[] {
  const data: Record<string, unknown>[] = [];
  const now = new Date();
  const baseValue = (KPI_BASES[platform]?.total_cost ?? 3000) / 30;

  for (let i = days; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const isWeekend = d.getDay() === 0 || d.getDay() === 6;
    const weekendFactor = isWeekend ? 0.65 : 1.0;

    const row: Record<string, unknown> = {
      [xKey]: d.toISOString().split("T")[0],
    };

    for (let j = 0; j < yKeys.length; j++) {
      const share = 1 / yKeys.length;
      const noise = 0.7 + Math.random() * 0.6;
      row[yKeys[j]] = Math.round(baseValue * share * weekendFactor * noise * 100) / 100;
    }

    data.push(row);
  }
  return data;
}

const PIE_LABELS: Record<string, string[]> = {
  snowflake: ["ANALYTICS_WH", "ETL_WH", "REPORTING_WH", "DATA_SCIENCE_WH", "LOADING_WH"],
  aws: ["EC2", "RDS", "S3", "Lambda", "Redshift", "Glue", "ECS"],
  gcp: ["analytics-prod", "ml-training", "etl-pipeline", "reporting"],
  databricks: ["prod-workspace", "dev-workspace", "ml-workspace"],
  dbt_cloud: ["nightly-build", "hourly-incremental", "weekly-full", "ci-pr-checks"],
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "text-embedding-3-large"],
  anthropic: ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001", "claude-opus-4-20250115"],
  gemini: ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
  github: ["api-backend", "frontend-app", "data-pipeline", "ml-model"],
  gitlab: ["core-api", "web-frontend", "infra-terraform"],
};

function generatePieData(xKey: string, yKey: string, platform: string): Record<string, unknown>[] {
  const labels = PIE_LABELS[platform] || ["Item 1", "Item 2", "Item 3", "Item 4"];
  let remaining = 100;
  return labels.map((label, i) => {
    const share = i === labels.length - 1 ? remaining : Math.round(remaining * (0.2 + Math.random() * 0.4));
    remaining -= share;
    if (remaining < 0) remaining = 0;
    const baseCost = (KPI_BASES[platform]?.total_cost ?? 3000);
    return { [xKey]: label, [yKey]: Math.round(baseCost * share / 100) };
  });
}

function generateBarItems(xKey: string, yKey: string, platform: string): Record<string, unknown>[] {
  const labels = PIE_LABELS[platform] || ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5"];
  return labels.map((label) => ({
    [xKey]: label,
    [yKey]: Math.round(1000 + Math.random() * 4000),
  })).sort((a, b) => (b[yKey] as number) - (a[yKey] as number));
}

const TABLE_GENERATORS: Record<string, (cols: { key: string }[]) => Record<string, unknown>[]> = {};

function generateTableData(
  columns: { key: string; format?: string }[],
  platform: string,
  viewSlug: string,
): Record<string, unknown>[] {
  const labels = PIE_LABELS[platform] || ["Item 1", "Item 2", "Item 3"];
  const rows: Record<string, unknown>[] = [];

  for (let i = 0; i < Math.min(labels.length * 2, 15); i++) {
    const row: Record<string, unknown> = {};
    for (const col of columns) {
      row[col.key] = generateCellValue(col.key, col.format, labels[i % labels.length], i, platform);
    }
    rows.push(row);
  }

  return rows;
}

function generateCellValue(key: string, format: string | undefined, label: string, index: number, platform: string): unknown {
  // Name-like columns
  if (["name", "warehouse", "user", "cluster", "job", "model", "connector", "bucket", "table", "dataset", "project", "workflow", "repo", "workbook", "dashboard", "pipeline", "site", "source", "query", "query_text", "job_id", "pattern"].includes(key)) {
    if (key === "user") return ["alice@company.com", "bob@company.com", "etl_service", "analytics_bot", "data_team"][index % 5];
    if (key === "query_text" || key === "query") return ["SELECT * FROM orders WHERE ...", "INSERT INTO analytics...", "MERGE INTO dim_users...", "CREATE TABLE AS SELECT...", "WITH cte AS (SELECT...)"][index % 5];
    return label + (index >= (PIE_LABELS[platform]?.length ?? 3) ? `_${index}` : "");
  }

  // Status columns
  if (["status", "state", "severity"].includes(key)) {
    if (key === "state") return ["STARTED", "SUSPENDED", "STARTED", "SUSPENDED"][index % 4];
    if (key === "severity") return ["high", "medium", "low", "medium"][index % 4];
    return ["SUCCESS", "SUCCESS", "SUCCESS", "FAILED", "SUCCESS"][index % 5];
  }

  // Size/type columns
  if (key === "size") return ["X-Small", "Small", "Medium", "Large", "X-Large"][index % 5];
  if (key === "node_type") return ["dc2.large", "ra3.xlplus", "dc2.8xlarge"][index % 3];
  if (key === "type") return ["QUERY", "LOAD", "COPY", "MERGE"][index % 4];
  if (key === "storage_class") return ["STANDARD", "INFREQUENT_ACCESS", "GLACIER", "DEEP_ARCHIVE"][index % 4];
  if (key === "class") return key;
  if (key === "unit") return ["GB-Hours", "Requests", "GB", "Hours"][index % 4];
  if (key === "owner") return ["admin", "analyst", "engineer"][index % 3];
  if (key === "last_accessed" || key === "last_run" || key === "last_incident" || key === "last_synced") {
    const d = new Date(); d.setDate(d.getDate() - index * 3 - 1);
    return d.toISOString().split("T")[0];
  }

  // Numeric columns
  switch (format) {
    case "currency": return Math.round((500 + Math.random() * 3000) * 100) / 100;
    case "number": return Math.round(100 + Math.random() * 5000);
    case "bytes": return Math.round((1 + Math.random() * 100) * 1024 * 1024 * 1024);
    case "duration": return Math.round(500 + Math.random() * 10000);
    case "percent": return Math.round(Math.random() * 100 * 10) / 10;
    default: return Math.round(Math.random() * 1000);
  }
}
