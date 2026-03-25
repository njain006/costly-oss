import {
  BarChart3, DollarSign, Zap, HardDrive, Warehouse, Layers, History,
  Cloud, Database, Cpu, GitBranch, Eye, Bot, Server, Workflow,
  FolderSearch, Clock, Activity, Box, Globe, Gauge, Users,
  Sparkles, BarChart2, PieChart, Boxes, Network, Shield,
  type LucideIcon,
} from "lucide-react";

/* ─── Types ─── */

export interface KpiConfig {
  key: string;
  title: string;
  format: "currency" | "number" | "bytes" | "duration" | "percent";
  icon: LucideIcon;
}

export interface ChartConfig {
  key: string;
  title: string;
  type: "area" | "bar" | "horizontal-bar" | "pie" | "stacked-area";
  xKey: string;
  yKeys: { key: string; label: string; color?: string }[];
  span?: 1 | 2 | 3;
}

export interface TableColumn {
  key: string;
  label: string;
  format?: "currency" | "number" | "bytes" | "duration" | "percent" | "text";
  align?: "left" | "right";
}

export interface TableConfig {
  key: string;
  title: string;
  columns: TableColumn[];
}

export interface PlatformViewConfig {
  slug: string;
  label: string;
  icon: LucideIcon;
  kpis: KpiConfig[];
  charts: ChartConfig[];
  table: TableConfig;
}

export interface PlatformRegistryEntry {
  key: string;
  label: string;
  icon: LucideIcon;
  category: "warehouse" | "cloud" | "transformation" | "ai" | "ingestion" | "quality" | "bi" | "cicd";
  views: PlatformViewConfig[];
  /** If set, sidebar links to these paths instead of /platforms/<key>/<slug> */
  legacyPaths?: Record<string, string>;
}

/* ─── Snowflake ─── */

const SNOWFLAKE: PlatformRegistryEntry = {
  key: "snowflake",
  label: "Snowflake",
  icon: Database,
  category: "warehouse",
  legacyPaths: {
    dashboard: "/dashboard",
    costs: "/costs",
    queries: "/queries",
    history: "/history",
    storage: "/storage",
    warehouses: "/warehouses",
    workloads: "/workloads",
  },
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "total_credits", title: "Credits Used", format: "number", icon: Gauge },
        { key: "total_queries", title: "Queries", format: "number", icon: Zap },
        { key: "active_warehouses", title: "Warehouses", format: "number", icon: Warehouse },
      ],
      charts: [
        { key: "cost_trend", title: "Daily Cost Trend", type: "stacked-area", xKey: "date", yKeys: [{ key: "compute_cost", label: "Compute" }, { key: "storage_cost", label: "Storage" }, { key: "cloud_services_cost", label: "Cloud Services" }], span: 2 },
        { key: "top_warehouses", title: "Top Warehouses", type: "horizontal-bar", xKey: "name", yKeys: [{ key: "credits", label: "Credits" }] },
      ],
      table: { key: "top_users", title: "Top Users by Cost", columns: [{ key: "user", label: "User" }, { key: "cost_usd", label: "Cost", format: "currency", align: "right" }, { key: "query_count", label: "Queries", format: "number", align: "right" }] },
    },
    {
      slug: "costs",
      label: "Cost Analysis",
      icon: DollarSign,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "daily_avg", title: "Daily Average", format: "currency", icon: BarChart2 },
        { key: "compute_cost", title: "Compute", format: "currency", icon: Cpu },
        { key: "storage_cost", title: "Storage", format: "currency", icon: HardDrive },
      ],
      charts: [
        { key: "daily_costs", title: "Daily Cost by Warehouse", type: "stacked-area", xKey: "date", yKeys: [{ key: "cost", label: "Cost" }], span: 2 },
        { key: "by_warehouse", title: "By Warehouse", type: "pie", xKey: "name", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "warehouse_costs", title: "Warehouse Cost Breakdown", columns: [{ key: "name", label: "Warehouse" }, { key: "credits", label: "Credits", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }, { key: "pct", label: "Share", format: "percent", align: "right" }] },
    },
    {
      slug: "queries",
      label: "Query Performance",
      icon: Zap,
      kpis: [
        { key: "total_queries", title: "Total Queries", format: "number", icon: Zap },
        { key: "avg_duration_ms", title: "Avg Duration", format: "duration", icon: Clock },
        { key: "cache_hit_pct", title: "Cache Hit Rate", format: "percent", icon: Activity },
        { key: "total_spill_gb", title: "Spillage", format: "bytes", icon: HardDrive },
      ],
      charts: [
        { key: "duration_trend", title: "Avg Duration Trend", type: "area", xKey: "date", yKeys: [{ key: "avg_ms", label: "Avg Duration (ms)" }], span: 2 },
        { key: "by_warehouse", title: "Queries by Warehouse", type: "pie", xKey: "warehouse", yKeys: [{ key: "count", label: "Queries" }] },
      ],
      table: { key: "slow_queries", title: "Slowest Queries", columns: [{ key: "query_text", label: "Query", format: "text" }, { key: "duration_ms", label: "Duration", format: "duration", align: "right" }, { key: "warehouse", label: "Warehouse" }, { key: "user", label: "User" }] },
    },
    {
      slug: "history",
      label: "Query History",
      icon: History,
      kpis: [
        { key: "total_queries", title: "Total Queries", format: "number", icon: History },
        { key: "unique_users", title: "Unique Users", format: "number", icon: Users },
        { key: "total_bytes_scanned", title: "Data Scanned", format: "bytes", icon: Database },
        { key: "failed_queries", title: "Failed", format: "number", icon: Shield },
      ],
      charts: [
        { key: "daily_volume", title: "Daily Query Volume", type: "bar", xKey: "date", yKeys: [{ key: "count", label: "Queries" }], span: 2 },
        { key: "by_status", title: "By Status", type: "pie", xKey: "status", yKeys: [{ key: "count", label: "Queries" }] },
      ],
      table: { key: "recent_queries", title: "Recent Queries", columns: [{ key: "query_text", label: "Query", format: "text" }, { key: "status", label: "Status" }, { key: "duration_ms", label: "Duration", format: "duration", align: "right" }, { key: "user", label: "User" }] },
    },
    {
      slug: "storage",
      label: "Storage",
      icon: HardDrive,
      kpis: [
        { key: "total_bytes", title: "Total Storage", format: "bytes", icon: HardDrive },
        { key: "storage_cost", title: "Storage Cost", format: "currency", icon: DollarSign },
        { key: "table_count", title: "Tables", format: "number", icon: Database },
        { key: "stale_tables", title: "Stale Tables", format: "number", icon: FolderSearch },
      ],
      charts: [
        { key: "storage_trend", title: "Storage Trend", type: "area", xKey: "date", yKeys: [{ key: "active_bytes", label: "Active" }, { key: "time_travel_bytes", label: "Time Travel" }, { key: "failsafe_bytes", label: "Failsafe" }], span: 2 },
        { key: "by_database", title: "By Database", type: "pie", xKey: "database", yKeys: [{ key: "bytes", label: "Size" }] },
      ],
      table: { key: "top_tables", title: "Largest Tables", columns: [{ key: "name", label: "Table" }, { key: "database", label: "Database" }, { key: "bytes", label: "Size", format: "bytes", align: "right" }, { key: "last_accessed", label: "Last Accessed" }] },
    },
    {
      slug: "warehouses",
      label: "Warehouses",
      icon: Warehouse,
      kpis: [
        { key: "total_warehouses", title: "Warehouses", format: "number", icon: Warehouse },
        { key: "total_credits", title: "Credits Used", format: "number", icon: Gauge },
        { key: "avg_utilization", title: "Avg Utilization", format: "percent", icon: Activity },
        { key: "idle_cost", title: "Idle Waste", format: "currency", icon: DollarSign },
      ],
      charts: [
        { key: "credits_by_warehouse", title: "Credits by Warehouse", type: "bar", xKey: "name", yKeys: [{ key: "credits", label: "Credits" }], span: 2 },
        { key: "utilization", title: "Utilization Distribution", type: "pie", xKey: "name", yKeys: [{ key: "utilization_pct", label: "Utilization" }] },
      ],
      table: { key: "warehouses", title: "All Warehouses", columns: [{ key: "name", label: "Name" }, { key: "size", label: "Size" }, { key: "state", label: "State" }, { key: "credits", label: "Credits", format: "number", align: "right" }, { key: "utilization_pct", label: "Utilization", format: "percent", align: "right" }] },
    },
    {
      slug: "workloads",
      label: "Workloads",
      icon: Layers,
      kpis: [
        { key: "total_patterns", title: "Query Patterns", format: "number", icon: Layers },
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "top_pattern_cost", title: "Top Pattern Cost", format: "currency", icon: BarChart2 },
        { key: "cacheable_pct", title: "Cacheable", format: "percent", icon: Sparkles },
      ],
      charts: [
        { key: "pattern_costs", title: "Top Patterns by Cost", type: "horizontal-bar", xKey: "pattern", yKeys: [{ key: "cost", label: "Cost" }], span: 2 },
        { key: "by_type", title: "By Type", type: "pie", xKey: "type", yKeys: [{ key: "count", label: "Patterns" }] },
      ],
      table: { key: "patterns", title: "Query Patterns", columns: [{ key: "pattern", label: "Pattern", format: "text" }, { key: "count", label: "Executions", format: "number", align: "right" }, { key: "avg_duration_ms", label: "Avg Duration", format: "duration", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── AWS ─── */

const AWS: PlatformRegistryEntry = {
  key: "aws",
  label: "AWS",
  icon: Cloud,
  category: "cloud",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "bucket_count", title: "S3 Buckets", format: "number", icon: Box },
        { key: "ec2_count", title: "EC2 Instances", format: "number", icon: Server },
        { key: "lambda_count", title: "Lambda Functions", format: "number", icon: Zap },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost Trend", type: "stacked-area", xKey: "date", yKeys: [{ key: "cost", label: "Cost" }], span: 2 },
        { key: "by_service", title: "By Service", type: "pie", xKey: "service", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "resources", title: "Resources & Costs", columns: [{ key: "name", label: "Resource" }, { key: "type", label: "Type" }, { key: "detail", label: "Details" }, { key: "status", label: "Status" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "redshift",
      label: "Redshift",
      icon: Database,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "cluster_count", title: "Clusters", format: "number", icon: Server },
        { key: "node_hours", title: "Node Hours", format: "number", icon: Clock },
        { key: "storage_gb", title: "Storage", format: "bytes", icon: HardDrive },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "area", xKey: "date", yKeys: [{ key: "cost", label: "Cost" }], span: 2 },
        { key: "by_cluster", title: "By Cluster", type: "pie", xKey: "cluster", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "clusters", title: "Clusters", columns: [{ key: "cluster", label: "Cluster" }, { key: "node_type", label: "Node Type" }, { key: "nodes", label: "Nodes", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "glue",
      label: "Glue",
      icon: Workflow,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "job_runs", title: "Job Runs", format: "number", icon: Workflow },
        { key: "dpu_hours", title: "DPU Hours", format: "number", icon: Cpu },
        { key: "crawler_runs", title: "Crawler Runs", format: "number", icon: FolderSearch },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "area", xKey: "date", yKeys: [{ key: "etl_cost", label: "ETL Jobs" }, { key: "crawler_cost", label: "Crawlers" }], span: 2 },
        { key: "by_job", title: "Top Jobs by Cost", type: "horizontal-bar", xKey: "job", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "jobs", title: "Glue Jobs", columns: [{ key: "job", label: "Job Name" }, { key: "runs", label: "Runs", format: "number", align: "right" }, { key: "dpu_hours", label: "DPU Hours", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "s3",
      label: "S3",
      icon: Box,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "bucket_count", title: "Buckets", format: "number", icon: Box },
        { key: "total_storage", title: "Total Storage", format: "bytes", icon: HardDrive },
        { key: "total_objects", title: "Objects", format: "number", icon: Boxes },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "storage_cost", label: "Storage" }, { key: "request_cost", label: "Requests" }, { key: "transfer_cost", label: "Transfer" }], span: 2 },
        { key: "by_class", title: "By Storage Class", type: "pie", xKey: "class", yKeys: [{ key: "bytes", label: "Size" }] },
      ],
      table: { key: "buckets", title: "Buckets", columns: [{ key: "name", label: "Bucket" }, { key: "size_display", label: "Size" }, { key: "objects", label: "Objects", align: "right" }, { key: "region", label: "Region" }, { key: "created", label: "Created" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "ec2",
      label: "EC2",
      icon: Server,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "instance_count", title: "Instances", format: "number", icon: Server },
        { key: "avg_utilization", title: "Avg CPU", format: "percent", icon: Activity },
        { key: "savings_opportunity", title: "Savings Opportunity", format: "currency", icon: Sparkles },
      ],
      charts: [
        { key: "daily_trend", title: "Daily EC2 Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "on_demand", label: "On-Demand" }, { key: "reserved", label: "Reserved" }, { key: "spot", label: "Spot" }], span: 2 },
        { key: "by_family", title: "By Instance Family", type: "pie", xKey: "family", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "instances", title: "EC2 Instances", columns: [{ key: "instance_id", label: "Instance" }, { key: "type", label: "Type" }, { key: "state", label: "State" }, { key: "avg_cpu", label: "Avg CPU", format: "percent", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "lambda",
      label: "Lambda",
      icon: Zap,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "invocations", title: "Invocations", format: "number", icon: Zap },
        { key: "avg_duration", title: "Avg Duration", format: "duration", icon: Clock },
        { key: "error_rate", title: "Error Rate", format: "percent", icon: Shield },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "compute_cost", label: "Compute" }, { key: "request_cost", label: "Requests" }], span: 2 },
        { key: "top_functions", title: "Top Functions by Cost", type: "horizontal-bar", xKey: "function", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "functions", title: "Lambda Functions", columns: [{ key: "function", label: "Function" }, { key: "runtime", label: "Runtime" }, { key: "invocations", label: "Invocations", format: "number", align: "right" }, { key: "avg_duration_ms", label: "Avg Duration", format: "duration", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "rds",
      label: "RDS",
      icon: Database,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "instance_count", title: "Instances", format: "number", icon: Database },
        { key: "avg_cpu", title: "Avg CPU", format: "percent", icon: Activity },
        { key: "avg_connections", title: "Avg Connections", format: "number", icon: Users },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "compute_cost", label: "Compute" }, { key: "storage_cost", label: "Storage" }, { key: "io_cost", label: "I/O" }], span: 2 },
        { key: "by_engine", title: "By Engine", type: "pie", xKey: "engine", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "instances", title: "RDS Instances", columns: [{ key: "instance_id", label: "Instance" }, { key: "engine", label: "Engine" }, { key: "class", label: "Class" }, { key: "multi_az", label: "Multi-AZ" }, { key: "cpu_pct", label: "CPU", format: "percent", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "transfer",
      label: "Data Transfer",
      icon: Network,
      kpis: [
        { key: "total_cost", title: "Transfer Cost", format: "currency", icon: DollarSign },
        { key: "total_gb", title: "Total Data", format: "bytes", icon: Globe },
        { key: "egress_cost", title: "Egress Cost", format: "currency", icon: Network },
        { key: "nat_gateway_cost", title: "NAT Gateway", format: "currency", icon: Shield },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Transfer Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "internet_egress", label: "Internet Egress" }, { key: "cross_region", label: "Cross-Region" }, { key: "nat_gateway", label: "NAT Gateway" }], span: 2 },
        { key: "by_type", title: "By Transfer Type", type: "pie", xKey: "type", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "transfers", title: "Transfer Breakdown", columns: [{ key: "type", label: "Type" }, { key: "source", label: "Source" }, { key: "destination", label: "Destination" }, { key: "gb", label: "Data", format: "bytes", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── BigQuery ─── */

const BIGQUERY: PlatformRegistryEntry = {
  key: "gcp",
  label: "BigQuery",
  icon: Database,
  category: "warehouse",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "total_tb_processed", title: "TB Processed", format: "number", icon: Database },
        { key: "slot_hours", title: "Slot Hours", format: "number", icon: Cpu },
        { key: "storage_cost", title: "Storage Cost", format: "currency", icon: HardDrive },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "query_cost", label: "Query" }, { key: "storage_cost", label: "Storage" }], span: 2 },
        { key: "by_project", title: "By Project", type: "pie", xKey: "project", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "top_queries", title: "Most Expensive Queries", columns: [{ key: "query", label: "Query", format: "text" }, { key: "tb_processed", label: "TB Processed", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }, { key: "user", label: "User" }] },
    },
    {
      slug: "jobs",
      label: "Slots & Jobs",
      icon: Cpu,
      kpis: [
        { key: "total_jobs", title: "Total Jobs", format: "number", icon: Workflow },
        { key: "avg_slot_ms", title: "Avg Slot Time", format: "duration", icon: Clock },
        { key: "total_tb", title: "Data Processed", format: "number", icon: Database },
        { key: "cache_hit_pct", title: "Cache Hit", format: "percent", icon: Sparkles },
      ],
      charts: [
        { key: "daily_jobs", title: "Daily Job Volume", type: "bar", xKey: "date", yKeys: [{ key: "count", label: "Jobs" }], span: 2 },
        { key: "by_type", title: "By Job Type", type: "pie", xKey: "type", yKeys: [{ key: "count", label: "Jobs" }] },
      ],
      table: { key: "jobs", title: "Recent Jobs", columns: [{ key: "job_id", label: "Job ID" }, { key: "type", label: "Type" }, { key: "bytes_processed", label: "Data", format: "bytes", align: "right" }, { key: "duration_ms", label: "Duration", format: "duration", align: "right" }] },
    },
    {
      slug: "storage",
      label: "Storage",
      icon: HardDrive,
      kpis: [
        { key: "total_storage", title: "Total Storage", format: "bytes", icon: HardDrive },
        { key: "storage_cost", title: "Monthly Cost", format: "currency", icon: DollarSign },
        { key: "dataset_count", title: "Datasets", format: "number", icon: Database },
        { key: "table_count", title: "Tables", format: "number", icon: Layers },
      ],
      charts: [
        { key: "storage_trend", title: "Storage Trend", type: "area", xKey: "date", yKeys: [{ key: "active_bytes", label: "Active" }, { key: "long_term_bytes", label: "Long-term" }], span: 2 },
        { key: "by_dataset", title: "By Dataset", type: "pie", xKey: "dataset", yKeys: [{ key: "bytes", label: "Size" }] },
      ],
      table: { key: "datasets", title: "Datasets", columns: [{ key: "dataset", label: "Dataset" }, { key: "table_count", label: "Tables", format: "number", align: "right" }, { key: "bytes", label: "Size", format: "bytes", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── Databricks ─── */

const DATABRICKS: PlatformRegistryEntry = {
  key: "databricks",
  label: "Databricks",
  icon: Cpu,
  category: "warehouse",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "dbu_consumed", title: "DBUs Consumed", format: "number", icon: Gauge },
        { key: "cluster_hours", title: "Cluster Hours", format: "number", icon: Clock },
        { key: "job_runs", title: "Job Runs", format: "number", icon: Workflow },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "compute", label: "Compute" }, { key: "sql", label: "SQL" }, { key: "jobs", label: "Jobs" }], span: 2 },
        { key: "by_workspace", title: "By Workspace", type: "pie", xKey: "workspace", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "clusters", title: "Clusters & Warehouses", columns: [{ key: "name", label: "Name" }, { key: "type", label: "Type" }, { key: "dbu", label: "DBUs", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "jobs",
      label: "Jobs",
      icon: Workflow,
      kpis: [
        { key: "total_jobs", title: "Total Jobs", format: "number", icon: Workflow },
        { key: "total_cost", title: "Job Cost", format: "currency", icon: DollarSign },
        { key: "avg_duration", title: "Avg Duration", format: "duration", icon: Clock },
        { key: "failure_rate", title: "Failure Rate", format: "percent", icon: Shield },
      ],
      charts: [
        { key: "daily_runs", title: "Daily Job Runs", type: "bar", xKey: "date", yKeys: [{ key: "success", label: "Success" }, { key: "failed", label: "Failed" }], span: 2 },
        { key: "top_jobs", title: "Top Jobs by Cost", type: "horizontal-bar", xKey: "job", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "jobs", title: "Jobs", columns: [{ key: "job", label: "Job Name" }, { key: "runs", label: "Runs", format: "number", align: "right" }, { key: "avg_duration_ms", label: "Avg Duration", format: "duration", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "sql-warehouses",
      label: "SQL Warehouses",
      icon: Database,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "warehouse_count", title: "Warehouses", format: "number", icon: Warehouse },
        { key: "total_dbu", title: "DBUs Used", format: "number", icon: Gauge },
        { key: "avg_query_time", title: "Avg Query Time", format: "duration", icon: Clock },
      ],
      charts: [
        { key: "daily_trend", title: "Daily SQL Warehouse Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "serverless", label: "Serverless" }, { key: "pro", label: "Pro" }, { key: "classic", label: "Classic" }], span: 2 },
        { key: "by_warehouse", title: "By Warehouse", type: "pie", xKey: "warehouse", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "warehouses", title: "SQL Warehouses", columns: [{ key: "name", label: "Warehouse" }, { key: "type", label: "Type" }, { key: "size", label: "Size" }, { key: "state", label: "State" }, { key: "dbu", label: "DBUs", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "clusters",
      label: "Clusters",
      icon: Server,
      kpis: [
        { key: "total_cost", title: "Cluster Cost", format: "currency", icon: DollarSign },
        { key: "cluster_count", title: "Clusters", format: "number", icon: Server },
        { key: "avg_utilization", title: "Avg Utilization", format: "percent", icon: Activity },
        { key: "idle_cost", title: "Idle Cost", format: "currency", icon: Clock },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cluster Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "interactive", label: "Interactive" }, { key: "automated", label: "Automated" }], span: 2 },
        { key: "by_cluster", title: "Top Clusters by Cost", type: "horizontal-bar", xKey: "cluster", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "clusters", title: "All Clusters", columns: [{ key: "name", label: "Cluster" }, { key: "type", label: "Type" }, { key: "node_type", label: "Node Type" }, { key: "workers", label: "Workers", format: "number", align: "right" }, { key: "dbu_rate", label: "DBU/hr", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "storage",
      label: "Storage",
      icon: HardDrive,
      kpis: [
        { key: "total_storage", title: "Total Storage", format: "bytes", icon: HardDrive },
        { key: "storage_cost", title: "Storage Cost", format: "currency", icon: DollarSign },
        { key: "table_count", title: "Delta Tables", format: "number", icon: Layers },
        { key: "optimize_savings", title: "Optimize Savings", format: "currency", icon: Sparkles },
      ],
      charts: [
        { key: "storage_trend", title: "Storage Trend", type: "area", xKey: "date", yKeys: [{ key: "managed_bytes", label: "Managed" }, { key: "external_bytes", label: "External" }], span: 2 },
        { key: "by_catalog", title: "By Catalog", type: "pie", xKey: "catalog", yKeys: [{ key: "bytes", label: "Size" }] },
      ],
      table: { key: "tables", title: "Largest Tables", columns: [{ key: "catalog", label: "Catalog" }, { key: "schema", label: "Schema" }, { key: "table", label: "Table" }, { key: "bytes", label: "Size", format: "bytes", align: "right" }, { key: "files", label: "Files", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "sku",
      label: "SKU Breakdown",
      icon: PieChart,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "interactive_cost", title: "Interactive", format: "currency", icon: Cpu },
        { key: "automated_cost", title: "Automated", format: "currency", icon: Workflow },
        { key: "sql_cost", title: "SQL Compute", format: "currency", icon: Database },
      ],
      charts: [
        { key: "daily_by_sku", title: "Daily Cost by SKU", type: "stacked-area", xKey: "date", yKeys: [{ key: "interactive", label: "Interactive ($0.55/DBU)" }, { key: "automated", label: "Automated ($0.15/DBU)" }, { key: "sql_compute", label: "SQL ($0.22/DBU)" }, { key: "jobs_light", label: "Jobs Light ($0.10/DBU)" }], span: 2 },
        { key: "by_sku", title: "By SKU", type: "pie", xKey: "sku", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "sku_details", title: "SKU Details", columns: [{ key: "sku", label: "SKU" }, { key: "dbu_rate", label: "Rate ($/DBU)" }, { key: "dbu_consumed", label: "DBUs", format: "number", align: "right" }, { key: "photon_multiplier", label: "Photon", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── dbt Cloud ─── */

const DBT_CLOUD: PlatformRegistryEntry = {
  key: "dbt_cloud",
  label: "dbt Cloud",
  icon: GitBranch,
  category: "transformation",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "job_runs", title: "Job Runs", format: "number", icon: Workflow },
        { key: "avg_duration", title: "Avg Duration", format: "duration", icon: Clock },
        { key: "model_count", title: "Models", format: "number", icon: Layers },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "area", xKey: "date", yKeys: [{ key: "cost", label: "Cost" }], span: 2 },
        { key: "by_job", title: "Cost by Job", type: "pie", xKey: "job", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "jobs", title: "dbt Jobs", columns: [{ key: "job", label: "Job" }, { key: "runs", label: "Runs", format: "number", align: "right" }, { key: "avg_duration_ms", label: "Avg Duration", format: "duration", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "models",
      label: "Models",
      icon: Layers,
      kpis: [
        { key: "total_models", title: "Total Models", format: "number", icon: Layers },
        { key: "avg_run_time", title: "Avg Run Time", format: "duration", icon: Clock },
        { key: "slowest_model_time", title: "Slowest Model", format: "duration", icon: Activity },
        { key: "error_count", title: "Errors", format: "number", icon: Shield },
      ],
      charts: [
        { key: "model_durations", title: "Slowest Models", type: "horizontal-bar", xKey: "model", yKeys: [{ key: "avg_ms", label: "Avg Duration" }], span: 2 },
        { key: "by_status", title: "Run Status", type: "pie", xKey: "status", yKeys: [{ key: "count", label: "Runs" }] },
      ],
      table: { key: "models", title: "Models", columns: [{ key: "model", label: "Model" }, { key: "runs", label: "Runs", format: "number", align: "right" }, { key: "avg_duration_ms", label: "Avg Duration", format: "duration", align: "right" }, { key: "last_run", label: "Last Run" }] },
    },
  ],
};

/* ─── Fivetran ─── */

const FIVETRAN: PlatformRegistryEntry = {
  key: "fivetran",
  label: "Fivetran",
  icon: Network,
  category: "ingestion",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "mar_used", title: "MAR Used", format: "number", icon: Activity },
        { key: "connector_count", title: "Connectors", format: "number", icon: Network },
        { key: "sync_count", title: "Syncs", format: "number", icon: Workflow },
      ],
      charts: [
        { key: "daily_trend", title: "Daily MAR Usage", type: "area", xKey: "date", yKeys: [{ key: "mar", label: "MAR" }], span: 2 },
        { key: "by_connector", title: "By Connector", type: "pie", xKey: "connector", yKeys: [{ key: "mar", label: "MAR" }] },
      ],
      table: { key: "connectors", title: "Connectors", columns: [{ key: "connector", label: "Connector" }, { key: "source", label: "Source" }, { key: "mar", label: "MAR", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── Airbyte ─── */

const AIRBYTE: PlatformRegistryEntry = {
  key: "airbyte",
  label: "Airbyte",
  icon: Network,
  category: "ingestion",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "sync_count", title: "Syncs", format: "number", icon: Workflow },
        { key: "records_synced", title: "Records Synced", format: "number", icon: Database },
        { key: "connector_count", title: "Connectors", format: "number", icon: Network },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "area", xKey: "date", yKeys: [{ key: "cost", label: "Cost" }], span: 2 },
        { key: "by_connector", title: "By Connector", type: "pie", xKey: "connector", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "connectors", title: "Connectors", columns: [{ key: "connector", label: "Connector" }, { key: "syncs", label: "Syncs", format: "number", align: "right" }, { key: "records", label: "Records", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── OpenAI ─── */

const OPENAI: PlatformRegistryEntry = {
  key: "openai",
  label: "OpenAI",
  icon: Bot,
  category: "ai",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "total_tokens", title: "Total Tokens", format: "number", icon: Zap },
        { key: "model_count", title: "Models Used", format: "number", icon: Bot },
        { key: "daily_avg", title: "Daily Average", format: "currency", icon: BarChart2 },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "input_cost", label: "Input" }, { key: "output_cost", label: "Output" }], span: 2 },
        { key: "by_model", title: "By Model", type: "pie", xKey: "model", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "models", title: "Model Usage", columns: [{ key: "model", label: "Model" }, { key: "input_tokens", label: "Input Tokens", format: "number", align: "right" }, { key: "output_tokens", label: "Output Tokens", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "usage",
      label: "Token Usage",
      icon: Activity,
      kpis: [
        { key: "total_input", title: "Input Tokens", format: "number", icon: Zap },
        { key: "total_output", title: "Output Tokens", format: "number", icon: Zap },
        { key: "input_cost", title: "Input Cost", format: "currency", icon: DollarSign },
        { key: "output_cost", title: "Output Cost", format: "currency", icon: DollarSign },
      ],
      charts: [
        { key: "daily_tokens", title: "Daily Token Usage", type: "stacked-area", xKey: "date", yKeys: [{ key: "input", label: "Input" }, { key: "output", label: "Output" }], span: 2 },
        { key: "by_model", title: "Tokens by Model", type: "horizontal-bar", xKey: "model", yKeys: [{ key: "tokens", label: "Tokens" }] },
      ],
      table: { key: "daily", title: "Daily Breakdown", columns: [{ key: "date", label: "Date" }, { key: "input_tokens", label: "Input", format: "number", align: "right" }, { key: "output_tokens", label: "Output", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── Anthropic ─── */

const ANTHROPIC: PlatformRegistryEntry = {
  key: "anthropic",
  label: "Anthropic",
  icon: Bot,
  category: "ai",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "total_tokens", title: "Total Tokens", format: "number", icon: Zap },
        { key: "model_count", title: "Models Used", format: "number", icon: Bot },
        { key: "daily_avg", title: "Daily Average", format: "currency", icon: BarChart2 },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "stacked-area", xKey: "date", yKeys: [{ key: "input_cost", label: "Input" }, { key: "output_cost", label: "Output" }], span: 2 },
        { key: "by_model", title: "By Model", type: "pie", xKey: "model", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "models", title: "Model Usage", columns: [{ key: "model", label: "Model" }, { key: "input_tokens", label: "Input Tokens", format: "number", align: "right" }, { key: "output_tokens", label: "Output Tokens", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
    {
      slug: "usage",
      label: "Token Usage",
      icon: Activity,
      kpis: [
        { key: "total_input", title: "Input Tokens", format: "number", icon: Zap },
        { key: "total_output", title: "Output Tokens", format: "number", icon: Zap },
        { key: "input_cost", title: "Input Cost", format: "currency", icon: DollarSign },
        { key: "output_cost", title: "Output Cost", format: "currency", icon: DollarSign },
      ],
      charts: [
        { key: "daily_tokens", title: "Daily Token Usage", type: "stacked-area", xKey: "date", yKeys: [{ key: "input", label: "Input" }, { key: "output", label: "Output" }], span: 2 },
        { key: "by_model", title: "Tokens by Model", type: "horizontal-bar", xKey: "model", yKeys: [{ key: "tokens", label: "Tokens" }] },
      ],
      table: { key: "daily", title: "Daily Breakdown", columns: [{ key: "date", label: "Date" }, { key: "input_tokens", label: "Input", format: "number", align: "right" }, { key: "output_tokens", label: "Output", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── Gemini ─── */

const GEMINI: PlatformRegistryEntry = {
  key: "gemini",
  label: "Gemini",
  icon: Bot,
  category: "ai",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "total_tokens", title: "Total Tokens", format: "number", icon: Zap },
        { key: "model_count", title: "Models Used", format: "number", icon: Bot },
        { key: "daily_avg", title: "Daily Average", format: "currency", icon: BarChart2 },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Cost", type: "area", xKey: "date", yKeys: [{ key: "cost", label: "Cost" }], span: 2 },
        { key: "by_model", title: "By Model", type: "pie", xKey: "model", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "models", title: "Model Usage", columns: [{ key: "model", label: "Model" }, { key: "tokens", label: "Tokens", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── Looker ─── */

const LOOKER: PlatformRegistryEntry = {
  key: "looker",
  label: "Looker",
  icon: Eye,
  category: "bi",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "query_count", title: "Queries Run", format: "number", icon: Zap },
        { key: "user_count", title: "Active Users", format: "number", icon: Users },
        { key: "dashboard_count", title: "Dashboards", format: "number", icon: BarChart3 },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Usage", type: "area", xKey: "date", yKeys: [{ key: "queries", label: "Queries" }], span: 2 },
        { key: "by_project", title: "By Project", type: "pie", xKey: "project", yKeys: [{ key: "queries", label: "Queries" }] },
      ],
      table: { key: "projects", title: "Projects", columns: [{ key: "project", label: "Project" }, { key: "queries", label: "Queries", format: "number", align: "right" }, { key: "users", label: "Users", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── Tableau ─── */

const TABLEAU: PlatformRegistryEntry = {
  key: "tableau",
  label: "Tableau",
  icon: PieChart,
  category: "bi",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "License Cost", format: "currency", icon: DollarSign },
        { key: "user_count", title: "Users", format: "number", icon: Users },
        { key: "view_count", title: "Views", format: "number", icon: Eye },
        { key: "extract_count", title: "Extracts", format: "number", icon: Database },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Views", type: "area", xKey: "date", yKeys: [{ key: "views", label: "Views" }], span: 2 },
        { key: "by_site", title: "By Site", type: "pie", xKey: "site", yKeys: [{ key: "cost", label: "Cost" }] },
      ],
      table: { key: "workbooks", title: "Workbooks", columns: [{ key: "workbook", label: "Workbook" }, { key: "views", label: "Views", format: "number", align: "right" }, { key: "owner", label: "Owner" }, { key: "last_accessed", label: "Last Accessed" }] },
    },
  ],
};

/* ─── GitHub Actions ─── */

const GITHUB: PlatformRegistryEntry = {
  key: "github",
  label: "GitHub Actions",
  icon: GitBranch,
  category: "cicd",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "total_minutes", title: "Total Minutes", format: "number", icon: Clock },
        { key: "workflow_count", title: "Workflows", format: "number", icon: Workflow },
        { key: "repo_count", title: "Repos", format: "number", icon: GitBranch },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Minutes", type: "bar", xKey: "date", yKeys: [{ key: "minutes", label: "Minutes" }], span: 2 },
        { key: "by_repo", title: "By Repo", type: "pie", xKey: "repo", yKeys: [{ key: "minutes", label: "Minutes" }] },
      ],
      table: { key: "workflows", title: "Workflows", columns: [{ key: "workflow", label: "Workflow" }, { key: "repo", label: "Repo" }, { key: "runs", label: "Runs", format: "number", align: "right" }, { key: "minutes", label: "Minutes", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── GitLab CI ─── */

const GITLAB: PlatformRegistryEntry = {
  key: "gitlab",
  label: "GitLab CI",
  icon: GitBranch,
  category: "cicd",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "total_minutes", title: "CI Minutes", format: "number", icon: Clock },
        { key: "pipeline_count", title: "Pipelines", format: "number", icon: Workflow },
        { key: "project_count", title: "Projects", format: "number", icon: GitBranch },
      ],
      charts: [
        { key: "daily_trend", title: "Daily CI Minutes", type: "bar", xKey: "date", yKeys: [{ key: "minutes", label: "Minutes" }], span: 2 },
        { key: "by_project", title: "By Project", type: "pie", xKey: "project", yKeys: [{ key: "minutes", label: "Minutes" }] },
      ],
      table: { key: "pipelines", title: "Pipelines", columns: [{ key: "project", label: "Project" }, { key: "pipelines", label: "Pipelines", format: "number", align: "right" }, { key: "minutes", label: "Minutes", format: "number", align: "right" }, { key: "cost", label: "Cost", format: "currency", align: "right" }] },
    },
  ],
};

/* ─── Monte Carlo ─── */

const MONTE_CARLO: PlatformRegistryEntry = {
  key: "monte_carlo",
  label: "Monte Carlo",
  icon: Shield,
  category: "quality",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "table_count", title: "Tables Monitored", format: "number", icon: Database },
        { key: "incident_count", title: "Incidents", format: "number", icon: Shield },
        { key: "monitor_count", title: "Monitors", format: "number", icon: Eye },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Incidents", type: "bar", xKey: "date", yKeys: [{ key: "incidents", label: "Incidents" }], span: 2 },
        { key: "by_severity", title: "By Severity", type: "pie", xKey: "severity", yKeys: [{ key: "count", label: "Incidents" }] },
      ],
      table: { key: "tables", title: "Monitored Tables", columns: [{ key: "table", label: "Table" }, { key: "status", label: "Status" }, { key: "incidents", label: "Incidents", format: "number", align: "right" }, { key: "last_incident", label: "Last Incident" }] },
    },
  ],
};

/* ─── Omni ─── */

const OMNI: PlatformRegistryEntry = {
  key: "omni",
  label: "Omni",
  icon: Globe,
  category: "bi",
  views: [
    {
      slug: "dashboard",
      label: "Dashboard",
      icon: BarChart3,
      kpis: [
        { key: "total_cost", title: "Total Cost", format: "currency", icon: DollarSign },
        { key: "query_count", title: "Queries", format: "number", icon: Zap },
        { key: "user_count", title: "Users", format: "number", icon: Users },
        { key: "dashboard_count", title: "Dashboards", format: "number", icon: BarChart3 },
      ],
      charts: [
        { key: "daily_trend", title: "Daily Queries", type: "area", xKey: "date", yKeys: [{ key: "queries", label: "Queries" }], span: 2 },
        { key: "by_dashboard", title: "By Dashboard", type: "pie", xKey: "dashboard", yKeys: [{ key: "queries", label: "Queries" }] },
      ],
      table: { key: "dashboards", title: "Dashboards", columns: [{ key: "dashboard", label: "Dashboard" }, { key: "queries", label: "Queries", format: "number", align: "right" }, { key: "users", label: "Users", format: "number", align: "right" }] },
    },
  ],
};

/* ─── Registry ─── */

export const PLATFORM_REGISTRY: Record<string, PlatformRegistryEntry> = {
  snowflake: SNOWFLAKE,
  aws: AWS,
  gcp: BIGQUERY,
  databricks: DATABRICKS,
  dbt_cloud: DBT_CLOUD,
  fivetran: FIVETRAN,
  airbyte: AIRBYTE,
  openai: OPENAI,
  anthropic: ANTHROPIC,
  gemini: GEMINI,
  looker: LOOKER,
  tableau: TABLEAU,
  github: GITHUB,
  gitlab: GITLAB,
  monte_carlo: MONTE_CARLO,
  omni: OMNI,
};

/** Get all platform entries grouped by category for display */
export function getPlatformsByCategory() {
  const categories: Record<string, PlatformRegistryEntry[]> = {};
  for (const entry of Object.values(PLATFORM_REGISTRY)) {
    if (!categories[entry.category]) categories[entry.category] = [];
    categories[entry.category].push(entry);
  }
  return categories;
}

/** Get the view path for a platform view (handles legacy Snowflake paths) */
export function getViewPath(platform: PlatformRegistryEntry, viewSlug: string): string {
  if (platform.legacyPaths?.[viewSlug]) {
    return platform.legacyPaths[viewSlug];
  }
  return `/platforms/${platform.key}/${viewSlug}`;
}

/** Check if a path belongs to a platform */
export function isPathInPlatform(pathname: string, platform: PlatformRegistryEntry): boolean {
  if (platform.legacyPaths) {
    return Object.values(platform.legacyPaths).some((p) => pathname === p);
  }
  return pathname.startsWith(`/platforms/${platform.key}/`);
}
