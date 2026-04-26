# AWS — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

AWS is treated as a single Costly connector, but under the hood it spans 21+ services across compute, storage, databases, analytics, streaming, orchestration, and AI/ML — each with its own pricing model, its own usage-discovery API, and its own set of well-known waste patterns. The canonical billing data source is the **Cost and Usage Report (CUR) 2.0**, which AWS now also publishes in the FinOps-industry **FOCUS 1.2** spec (GA since April 2025); it is the ground truth on every charge and the only source that exposes resource-level line items, amortized pricing, and marketplace passthroughs. For real-time dashboards and conversational analytics (the Costly use case), the **Cost Explorer `GetCostAndUsage` API** is the practical primary — simpler auth, no S3 plumbing, but capped at grouping on two dimensions and missing resource-level detail. A production-grade AWS FinOps practice combines both: CUR 2.0 in S3 queried via Athena for depth, Cost Explorer for fast dashboards, Budgets + Cost Anomaly Detection for alerting, individual service APIs for inventory enrichment, and Savings Plans / Reserved Instances utilization reports for commitment health.

## Pricing Model (from AWS)

> All prices below are **on-demand, us-east-1 (N. Virginia)**, effective Q1 2026 unless otherwise stated. AWS publishes region-specific pricing at <https://aws.amazon.com/pricing/>. The canonical pricing database is the AWS Price List Query API (`pricing.us-east-1.amazonaws.com`) and Price List Bulk API (<https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json>).

### EC2 (Elastic Compute Cloud)

Per-second billing on Linux (1-min minimum), per-hour on Windows/RHEL/SUSE. Price varies by family, size, region, tenancy, and OS.

| Purchase Option | Commitment | Upfront | Typical Discount vs OD | Flexibility |
|-----------------|------------|---------|------------------------|-------------|
| On-Demand | None | None | 0% | Full |
| EC2 Instance Savings Plans | 1y / 3y | None / Partial / All | 34% / 47% / 54% | Same family + region |
| Compute Savings Plans | 1y / 3y | None / Partial / All | 27% / 40% / 50% | Any EC2 + Fargate + Lambda, any region |
| Reserved Instances (Standard) | 1y / 3y | Optional | 40% / 60% | Locked family |
| Reserved Instances (Convertible) | 1y / 3y | Optional | 30% / 50% | Can change family |
| Spot | None | None | 60% – 90% | 2-min interruption notice |

Selected instance on-demand prices (Linux, us-east-1, Q1 2026):

| Instance | vCPU | Memory | Price/hr |
|---------|------|--------|---------|
| t3.medium | 2 | 4 GB | $0.0416 |
| m6i.xlarge | 4 | 16 GB | $0.192 |
| m7g.xlarge (Graviton3) | 4 | 16 GB | $0.1632 (-15%) |
| c6i.xlarge | 4 | 8 GB | $0.170 |
| r6i.xlarge | 4 | 32 GB | $0.252 |
| r7g.xlarge (Graviton3) | 4 | 32 GB | $0.2142 |
| i4i.xlarge | 4 | 32 GB (local NVMe) | $0.343 |
| p5.48xlarge (H100) | 192 | 2 TB (8× H100) | $98.32 |
| p4d.24xlarge (A100) | 96 | 1.1 TB (8× A100) | $32.77 |
| g5.xlarge (A10G) | 4 | 16 GB (1× A10G) | $1.006 |

Sources: <https://aws.amazon.com/ec2/pricing/on-demand/>, <https://aws.amazon.com/ec2/pricing/reserved-instances/pricing/>, <https://aws.amazon.com/savingsplans/pricing/>, <https://aws.amazon.com/ec2/spot/pricing/>.

**EBS (attached storage)** — gp3 $0.08/GB-month + $0.005/provisioned IOPS above 3,000 + $0.04/MBps above 125. gp2 $0.10/GB-month (legacy). io2 $0.125/GB-month + $0.065/IOPS. Snapshots $0.05/GB-month. st1 $0.045/GB, sc1 $0.015/GB. <https://aws.amazon.com/ebs/pricing/>

**Elastic IP** — Since Feb 2024, AWS charges **$0.005/hr for every public IPv4 address**, attached or not. That's $3.60/month each. Audit unassociated EIPs and consider IPv6. <https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-plus-ipv6-egress-pricing/>

### S3 (Simple Storage Service)

| Class | Storage $/GB/mo | PUT/POST per 1K | GET per 1K | Retrieval | Min Storage Duration | Min Billable Object Size |
|-------|---------|---------|---------|---------|---------|---------|
| Standard | $0.023 | $0.005 | $0.0004 | free | — | — |
| Intelligent-Tiering (Frequent) | $0.023 | $0.005 | $0.0004 | free | — | — |
| Intelligent-Tiering (Infrequent) | $0.0125 | auto | auto | free | — | — |
| Intelligent-Tiering (Archive Instant) | $0.004 | auto | auto | free | — | — |
| Intelligent-Tiering (Archive) | $0.0036 | auto | auto | $0.01/GB | — | — |
| Intelligent-Tiering (Deep Archive) | $0.00099 | auto | auto | $0.02/GB | — | — |
| Standard-IA | $0.0125 | $0.01 | $0.001 | $0.01/GB | 30 days | 128 KB |
| One Zone-IA | $0.01 | $0.01 | $0.001 | $0.01/GB | 30 days | 128 KB |
| Glacier Instant Retrieval | $0.004 | $0.02 | $0.01 | $0.03/GB | 90 days | 128 KB |
| Glacier Flexible Retrieval | $0.0036 | $0.03 | $0.0004 | Std $0.01, Exp $0.03, Bulk free | 90 days | 40 KB overhead |
| Glacier Deep Archive | $0.00099 | $0.05 | $0.0004 | Std $0.02, Bulk $0.0025 | 180 days | 40 KB overhead |
| S3 Express One Zone | $0.16 | $0.0025 | $0.0002 | free | — | — |

Intelligent-Tiering monitoring fee: **$0.0025 per 1,000 objects/month** (waived if object <128 KB). Lifecycle transitions: **$0.01 per 1,000 requests** — do not transition millions of small objects. <https://aws.amazon.com/s3/pricing/>

**Data transfer** from S3: free within same region to AWS services via Gateway Endpoint; $0.02/GB cross-region; $0.09/GB to internet (first 10 TB/mo), tiering down to $0.05/GB above 150 TB/mo. CloudFront egress is $0.085/GB US/EU and **free from S3 to CloudFront**. <https://aws.amazon.com/s3/pricing/>

### RDS and Aurora

Instance hours + storage + backup + I/O (Aurora).

| Engine / Mode | Example (us-east-1) | Price |
|---------------|---------------------|-------|
| RDS PostgreSQL db.r6g.xlarge | Single-AZ | $0.462/hr |
| RDS PostgreSQL db.r6g.xlarge | Multi-AZ | $0.924/hr |
| RDS Aurora PostgreSQL r6g.xlarge (Standard) | | $0.462/hr, + $0.20/1M I/O |
| RDS Aurora PostgreSQL r6g.xlarge (I/O-Optimized) | | $0.600/hr, $0 I/O |
| Aurora Serverless v2 | per ACU | $0.12/ACU-hr |
| Aurora Serverless v2 Data API calls | | $0.35/1M |
| RDS Storage (gp3) | | $0.115/GB-mo |
| Aurora Storage | Standard | $0.10/GB-mo |
| Aurora Storage | I/O-Opt | $0.225/GB-mo |
| RDS Performance Insights | Long-term retention | $7.50/vCPU/month |
| Snapshot export to S3 | | $0.010/GB |

RI discounts: Standard 1y 40%, 3y 60%. Aurora Serverless v2 scales in 0.5-ACU steps with a new **zero-scaling** mode (GA 2024) that lets ACUs drop to 0 during idle. <https://aws.amazon.com/rds/pricing/>, <https://aws.amazon.com/rds/aurora/pricing/>.

### Lambda

- Requests: **$0.20 per 1M** invocations
- x86 duration: **$0.0000166667 per GB-second**
- arm64 (Graviton2) duration: **$0.0000133334 per GB-second** (-20%)
- Provisioned Concurrency: $0.0000041667/GB-s idle + $0.000009722/GB-s active
- SnapStart (Java/Python/.NET): $0.0001/GB cached + restoration fee
- Free tier: 1M requests + 400K GB-s / month, permanent

Rounded-up billing is now **per-ms** (1-ms minimum). Max 10 GB memory, 6 vCPU, 15-min execution, 10 GB ephemeral storage (`/tmp`) at $0.0000000309/GB-s above 512 MB. <https://aws.amazon.com/lambda/pricing/>

### DynamoDB

| Capacity Mode | Read | Write | Storage | Notes |
|----|----|----|----|----|
| On-Demand (Standard) | $0.25/1M RRU | $1.25/1M WRU | $0.25/GB-mo | 2024 on-demand throughput price cut ~50% |
| Provisioned | $0.00013/RCU-hr | $0.00065/WCU-hr | $0.25/GB-mo | Auto-scale optional |
| Reserved Capacity 1y | ~$0.000084/RCU-hr | ~$0.000420/WCU-hr | same | 53% RCU / 35% WCU off |
| Infrequent Access (2023 GA) | $0.0625/1M reads | $0.625/1M writes | $0.10/GB-mo | 60% storage discount for cold tables |
| Global Tables | adds full write cost per replica region + $0.02/GB cross-region transfer |
| Streams | $0.02/100K read requests |
| Backup (on-demand) | $0.10/GB-mo |
| PITR | $0.20/GB-mo |
| Export to S3 | $0.10/GB |

<https://aws.amazon.com/dynamodb/pricing/>, <https://aws.amazon.com/dynamodb/pricing/on-demand/>, <https://aws.amazon.com/dynamodb/pricing/provisioned/>.

### Redshift and Redshift Serverless

| Offering | Node / Unit | On-Demand |
|----|----|----|
| RA3 ra3.xlplus (4 vCPU, 32 GB) | | $1.086/hr |
| RA3 ra3.4xlarge (12 vCPU, 96 GB) | | $3.26/hr |
| RA3 ra3.16xlarge (48 vCPU, 384 GB) | | $13.04/hr |
| Managed Storage (RA3) | | $0.024/GB-mo |
| Concurrency Scaling | | $0.375/RPU-hr |
| Redshift Serverless | | $0.375/RPU-hr (8-512 RPU, per-second with 60-s minimum) |
| Redshift Spectrum | | $5/TB scanned |
| Data Sharing consumer | | free within same org, cross-region $0.0375/TB-s |
| ML (CREATE MODEL) | | pass-through to SageMaker |
| Reserved Nodes 1y | | ~33% off |
| Reserved Nodes 3y | | ~56% off |

Serverless introduced **AI-driven Price-Performance** targets in 2024 (optimize for cost vs speed). Serverless also supports snapshot-level sharing and auto-pause. <https://aws.amazon.com/redshift/pricing/>

### Glue

| Component | Price |
|----|----|
| Glue ETL (Spark, standard) | $0.44/DPU-hour (1 DPU = 4 vCPU + 16 GB) |
| Glue ETL (Ray / Python shell, G.1X) | $0.44/DPU-hour |
| Glue Flex execution | $0.29/DPU-hour (~34% off, best-effort scheduling) |
| Glue Streaming | $0.44/DPU-hour (always-on) |
| Glue Data Quality | $1.00 per 1,000 rules evaluated |
| Crawlers | $0.44/DPU-hour |
| Data Catalog storage | First 1M objects + 1M requests free, then $1/100K objects/mo, $1/1M requests |
| DataBrew | $1/node-hour |
| Glue Interactive Sessions | Same as ETL DPU, billed per-second (1-min min) |
| Schema Registry | Free |

Min billing is 1 minute per job; Spark jobs default to 10 DPUs but can scale down to 2 DPUs (G.1X) or even 1 DPU for small jobs. <https://aws.amazon.com/glue/pricing/>

### Athena

- DML queries: **$5.00/TB scanned** (10 MB minimum per query). Columnar formats (Parquet/ORC), compression, and partitioning directly reduce cost.
- Athena Federated Queries: pay data source cost + Lambda invocation cost.
- **Athena Provisioned Capacity / DPU**: $0.30/DPU-hour, 24-DPU minimum = $7.20/hr, 1-hr min, hourly billing — predictable cost for heavy workloads.
- Athena Serverless for Apache Spark: $0.35/DPU-hour (preview pricing at GA, per-second billed).
- CTAS, INSERT INTO: charged on scan of source + write to S3.

<https://aws.amazon.com/athena/pricing/>

### EMR

- **EMR on EC2**: EC2 instance price + EMR premium (20–30% of instance price depending on family). m5.xlarge = $0.192 + $0.048 = $0.240/hr. EMR premium for p5/g5 families is capped at $0.27/vCPU-hour.
- **EMR Serverless**: $0.052624/vCPU-hour + $0.0057785/GB-hour + $0.10/GB storage. No premium.
- **EMR on EKS**: Just EC2/Fargate + $0.026/vCPU-hour EMR premium — cheapest option for containerized Spark.
- **Studio / Notebook Execution**: $0.00027/notebook-minute.

<https://aws.amazon.com/emr/pricing/>

### EKS

- Cluster fee: **$0.10/hour per cluster** ($73.00/month).
- Extended support (Kubernetes versions beyond the 14-month standard window): **$0.60/hour per cluster** (6x standard).
- Compute: EC2 (own), Fargate (see below), or Karpenter-managed.
- Add-ons: VPC CNI, kube-proxy, CoreDNS, EBS-CSI — free; third-party add-ons billed by vendor.
- EKS Auto Mode (2024 GA): cluster fee + $0.60/vCPU-hour managed compute surcharge for a fully AWS-managed node lifecycle.

<https://aws.amazon.com/eks/pricing/>

### ECS + Fargate

- ECS on EC2: no ECS fee, pay EC2.
- ECS on Fargate (Linux x86): **$0.04048/vCPU-hr + $0.004445/GB-hr**.
- Fargate (arm64): $0.03238/vCPU-hr + $0.00356/GB-hr (~20% off).
- Fargate Spot: up to 70% off with 2-min interruption notice.
- Ephemeral storage above 20 GB: $0.000111/GB-hr.
- Compute Savings Plan coverage applies to Fargate.

<https://aws.amazon.com/fargate/pricing/>

### Bedrock

Pricing is **per-model** and splits into on-demand token pricing, batch (50% off), and provisioned throughput. Bedrock adds a markup vs the direct Anthropic/Cohere/Meta APIs, typically 0–10%.

| Model | Input $/1K tok | Output $/1K tok | Notes |
|----|----|----|----|
| Claude 3.7 Sonnet | $0.003 | $0.015 | Same as Anthropic direct |
| Claude 3.5 Haiku | $0.0008 | $0.004 | |
| Claude 3 Opus | $0.015 | $0.075 | |
| Llama 3.1 405B | $0.00532 | $0.016 | |
| Llama 3.1 70B | $0.00072 | $0.00072 | |
| Mistral Large 2 | $0.002 | $0.006 | |
| Mistral Small | $0.0002 | $0.0006 | |
| Titan Text Lite | $0.00015 | $0.0002 | |
| Amazon Nova Micro | $0.000035 | $0.00014 | Dec 2024 launch |
| Amazon Nova Lite | $0.00006 | $0.00024 | |
| Amazon Nova Pro | $0.0008 | $0.0032 | |
| Stable Diffusion XL 1.0 | $0.04–0.08/image | — | |
| Titan Image Generator | $0.008/image (standard) | $0.01 (premium) | |

- **Bedrock Agents**: model tokens + Lambda invocations + any knowledge base retrievals.
- **Knowledge Bases**: $0.35/GB/month vector store on OpenSearch Serverless (minimum 2 OCUs per KB ≈ $700/mo baseline) + embedding tokens + LLM tokens. Replace with Aurora pgvector or Pinecone to cut baseline.
- **Flows**: no additional Bedrock fee; pay for invoked models + agents.
- **Guardrails**: $0.15/1K text units (input + output) evaluated.
- **Provisioned Throughput**: 1-, 3-, or 6-month commitments. Claude Sonnet 3.5 MU (model unit): ~$30/hr, so ~$21,900/month per MU. Only justified at >3M tokens/hour sustained.
- **Custom Model Import**: $1.95/custom-model-unit-hour.

<https://aws.amazon.com/bedrock/pricing/>

### SageMaker

| Component | Price |
|----|----|
| Studio Domain | Free domain; underlying JupyterLab / Code Editor apps billed per-instance |
| Notebook / Studio JupyterLab (ml.t3.medium) | $0.05/hr |
| Training (ml.g5.xlarge, 1× A10G) | $1.408/hr |
| Training (ml.p4d.24xlarge, 8× A100) | $37.688/hr |
| Training (ml.p5.48xlarge, 8× H100) | $98.32/hr |
| **Managed Spot Training** | Up to 90% off training instance price |
| Real-time Inference (ml.m5.xlarge) | $0.23/hr |
| Serverless Inference | $0.20/1M requests + $0.0000166667/GB-s (similar to Lambda) |
| Async Inference | Same as real-time, scales to 0 |
| Batch Transform | Same as training instance |
| Pipelines | Free orchestration layer, pay for invoked jobs |
| Processing (ml.m5.xlarge) | $0.23/hr |
| Feature Store (online) | $0.045/1M read or write units |
| Feature Store (offline) | $0.06/GB-mo + S3 request costs |
| Model Monitor / Clarify | Same as processing instance |
| Ground Truth | $0.08–$0.08/object + human labeler fees |
| SageMaker Canvas | $1.90/hr Session + model training fees |
| JumpStart pre-trained model hosting | instance-type price |
| **SageMaker Savings Plans (1y / 3y)** | 24% / 43% off across notebooks, training, processing, inference |

<https://aws.amazon.com/sagemaker/pricing/>

In Dec 2024 AWS announced **SageMaker Unified Studio** (preview) — consolidates Studio + Data Wrangler + Lakehouse + Bedrock into a single IDE; billing is per-underlying-resource.

### OpenSearch Service

- Instance hours (e.g. r6g.large.search = $0.167/hr), EBS storage $0.135/GB-mo, UltraWarm $0.024/GB-mo, Cold $0.004/GB-mo.
- **OpenSearch Serverless**: $0.24/OCU-hour (OpenSearch Compute Unit), minimum 2 OCUs search + 2 OCUs indexing ≈ $700/month baseline per collection. Ingest/search OCUs are billed separately.
- Reserved Instances: 1y 31% off, 3y 50% off.
- Snapshots: free when to S3 in same region.

<https://aws.amazon.com/opensearch-service/pricing/>

### Step Functions

| Type | Price |
|----|----|
| Standard | $0.025 per 1,000 state transitions |
| Express — Duration | $0.00001667/GB-s |
| Express — Request | $1.00/1M requests |

Standard is for long-running, auditable workflows (up to 1 year, full history kept). Express is for high-volume short workflows (<5 min) — can be **50–90% cheaper** than Standard if state transitions are dense. <https://aws.amazon.com/step-functions/pricing/>

### Kinesis

| Service | Price |
|----|----|
| Data Streams (provisioned) | $0.015/shard-hr + $0.014/1M PUT payload units (25 KB each) |
| Data Streams (on-demand) | $0.04/GB ingested + $0.04/GB retrieved |
| Enhanced fan-out consumer | $0.015/shard-consumer-hr + $0.013/GB delivered |
| Extended retention (>24 h) | $0.02/shard-hr (1–7 days), $0.10/GB-mo (long-term) |
| Firehose — direct PUT | $0.029/GB (first 500 TB/mo), tiers down to $0.012/GB above 5 PB |
| Firehose — dynamic partitioning | + $0.02/GB + $0.018/1,000 objects |
| Firehose — format conversion (JSON→Parquet/ORC) | + $0.018/GB |
| Data Analytics (Managed Service for Apache Flink) | $0.11/KPU-hr + $0.10/GB running storage |

<https://aws.amazon.com/kinesis/data-streams/pricing/>, <https://aws.amazon.com/kinesis/data-firehose/pricing/>, <https://aws.amazon.com/managed-service-apache-flink/pricing/>.

### MSK (Managed Streaming for Apache Kafka)

| Flavor | Price |
|----|----|
| MSK Provisioned (kafka.m7g.large) | $0.17/broker-hr |
| MSK Provisioned (kafka.m7g.xlarge) | $0.336/broker-hr |
| MSK Provisioned (kafka.m7g.2xlarge) | $0.672/broker-hr |
| Storage | $0.10/GB-mo |
| MSK Serverless | $0.75/cluster-hr + $0.0015/partition-hr + $0.10/GB ingested + $0.05/GB retrieved |
| MSK Connect | $0.11/MCU-hr + $0.10/GB-mo MCU storage |
| MSK Replicator | $0.10/GB replicated |

<https://aws.amazon.com/msk/pricing/>

### DataSync

- Per-GB transferred: **$0.0125/GB** (first 1 PB/mo), $0.008/GB (above).
- Discovery for on-prem: $5/10 TB scanned storage/mo (up to $100/mo per job).
- AWS-to-AWS transfer (e.g. S3 → FSx): same $0.0125/GB + standard data transfer.

<https://aws.amazon.com/datasync/pricing/>

### Transfer Family

- Protocol endpoint: **$0.30/hr per enabled protocol** per server ($216/month). Three protocols on one server = $648/month before data.
- Data uploaded: $0.04/GB.
- Data downloaded: $0.04/GB.
- 90% data discount via Transfer Family Web Apps (2024 GA).

<https://aws.amazon.com/aws-transfer-family/pricing/>

### Amazon Q

| Flavor | Price |
|----|----|
| Q Developer Free | $0/mo, limited prompts + agent runs |
| Q Developer Pro | $19/user/month, unlimited IDE + CLI usage |
| Q Business Lite | $3/user/month (read-only, simple Q&A) |
| Q Business Pro | $20/user/month (full workflows, custom plugins, 40+ connectors) |
| Q in Connect | $40/agent/month |
| Q in QuickSight | $250 base + $20/author/month |
| Q Apps (shared) | included in Q Business Pro |

<https://aws.amazon.com/q/pricing/>

### Savings Plans (cross-service)

- **Compute Savings Plans (1y/3y, no-upfront)**: 27% / 40% off on average across EC2 (any family/region/OS), Fargate, Lambda.
- **EC2 Instance Savings Plans**: 34% / 47% off — family+region locked.
- **SageMaker Savings Plans**: 24% / 43% off SageMaker training+inference+processing+notebook.
- Commitment is $/hour — e.g. $10/hr committed delivers coverage up to that hourly spend.
- Payment options: No Upfront, Partial, All — All Upfront ≈ 3% extra discount.

<https://aws.amazon.com/savingsplans/compute-pricing/>, <https://aws.amazon.com/savingsplans/sagemaker-pricing/>.

### Reserved Instances

For services without Savings Plans: RDS, ElastiCache, Redshift, OpenSearch, DynamoDB, MemoryDB. 1y / 3y terms; Partial / All Upfront. Convertible RIs (EC2 only) trade discount for family-change flexibility. Legacy EC2 RIs are deprecated in favor of Savings Plans but existing ones remain honored. <https://aws.amazon.com/aws-cost-management/pricing-ris/>

### EDP / PPA commit tiers

AWS **Enterprise Discount Program** (EDP) is a private-discount contract for accounts with annual spend >$1M. Typical tiering:

| Annual Commit | Typical Discount |
|----|----|
| $1M | 5% |
| $5M | 8–10% |
| $20M | 11–13% |
| $50M+ | 15–20% |
| $100M+ | bespoke |

EDP discount applies **first** (off list), then RIs/SPs apply on the EDP-discounted rate. EDP does **not** cover Marketplace, Support, Tax, or some edge services (Outposts, Ground Station, Shield Advanced in some cases). **PPA (Private Pricing Addendum)** is the newer replacement vehicle; same economics, more negotiable terms. Enterprises routinely negotiate extra product-specific credits on top — e.g. S3 Deep Archive at 50% off list or Bedrock Sonnet at 10% off token price.

### Marketplace passthroughs

AWS Marketplace purchases (Databricks, Snowflake, MongoDB Atlas, etc.) are billed via your AWS bill but **do not count** toward EDP, Savings Plans, or Reserved Instances. They appear in CUR with `line_item_product_code = AWSMarketplace`. Since 2022 AWS allows a **Marketplace EDP uplift** where up to ~25% of Marketplace spend can count toward your EDP commit — negotiate this explicitly.

## Billing / Usage Data Sources

### Primary (for depth): CUR 2.0 / FOCUS 1.2

The **Cost and Usage Report (CUR) 2.0** (and its FinOps-standard cousin **FOCUS 1.2**, which went GA in April 2025) is the only data source with:

- Every line item with a unique `line_item_usage_account_id`, `line_item_usage_start_date` (hourly), `line_item_resource_id`, `line_item_usage_amount`, `line_item_unblended_cost`, `pricing_public_on_demand_cost`, `savings_plan_savings_plan_effective_cost`, etc.
- Resource-level attribution including tags and cost categories.
- Amortized RI/SP effective cost per hour.
- Marketplace passthrough detail.
- Refunds, credits, EDP discounts.

**Setup** (Athena-queryable export):

```bash
# 1. Create S3 bucket for CUR
aws s3 mb s3://mycompany-cur-bucket --region us-east-1

# 2. Create CUR 2.0 data export (via Billing and Cost Management → Data Exports)
aws bcm-data-exports create-export --export '{
  "Name": "cur-2-0-parquet",
  "DataQuery": {
    "QueryStatement": "SELECT * FROM COST_AND_USAGE_REPORT",
    "TableConfigurations": {
      "COST_AND_USAGE_REPORT": {
        "TIME_GRANULARITY": "HOURLY",
        "INCLUDE_RESOURCES": "TRUE",
        "INCLUDE_MANUAL_DISCOUNT_COMPATIBILITY": "FALSE",
        "INCLUDE_SPLIT_COST_ALLOCATION_DATA": "TRUE"
      }
    }
  },
  "DestinationConfigurations": {
    "S3Destination": {
      "S3Bucket": "mycompany-cur-bucket",
      "S3Prefix": "cur2",
      "S3Region": "us-east-1",
      "S3OutputConfigurations": {
        "OutputType": "CUSTOM",
        "Format": "PARQUET",
        "Compression": "PARQUET",
        "Overwrite": "OVERWRITE_REPORT"
      }
    }
  },
  "RefreshCadence": {"Frequency": "SYNCHRONOUS"}
}'

# 3. Register Athena table via CloudFormation template AWS supplies,
#    or crawl with Glue.

# 4. Example daily cost by service, amortized:
SELECT
  bill_billing_period_start_date,
  line_item_product_code,
  SUM(line_item_unblended_cost)                              AS on_demand_cost,
  SUM(savings_plan_savings_plan_effective_cost)              AS sp_effective_cost,
  SUM(reservation_effective_cost)                            AS ri_effective_cost,
  SUM(line_item_unblended_cost
      - COALESCE(savings_plan_negation_unused_commitment, 0)
      - COALESCE(reservation_net_amortized_upfront_cost_for_usage, 0)) AS net_amortized_cost
FROM "cur2"."cur2_parquet"
WHERE line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
  AND year = '2026' AND month = '4'
GROUP BY 1, 2
ORDER BY 1, 2;
```

**FOCUS 1.2 (GA April 2025)** is a vendor-neutral schema (<https://focus.finops.org/>) — same CUR 2.0 data reshaped with stable column names: `BilledCost`, `EffectiveCost`, `ServiceName`, `ResourceId`, `Tags`, `ChargeCategory`, `CommitmentDiscountType`. Because FOCUS is cross-cloud, adopting it now future-proofs Costly's schema once we unify AWS + Azure + GCP.

Auth for the CUR path requires:

- IAM role with `s3:GetObject`, `s3:ListBucket` on the CUR bucket.
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`.
- `glue:GetDatabase`, `glue:GetTable`, `glue:GetPartitions` (catalog).
- `s3:PutObject` on an Athena results bucket.
- Optional: KMS decrypt if CUR bucket is encrypted with CMK.

Minimal IAM policy: <https://docs.aws.amazon.com/athena/latest/ug/setting-up.html>

Docs: <https://docs.aws.amazon.com/cur/latest/userguide/what-is-cur.html>, <https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2.html>, <https://docs.aws.amazon.com/cur/latest/userguide/dataexports-create-focus.html>.

### Secondary (for ease): Cost Explorer `GetCostAndUsage`

What Costly currently uses (`aws_connector.py`). Strengths:

- Single API, IAM-only auth (no S3, no Athena).
- Pre-aggregated — returns daily/monthly sums in <2 s for typical queries.
- Supports AmortizedCost, UnblendedCost, NetAmortizedCost, NetUnblendedCost, BlendedCost, UsageQuantity, NormalizedUsageAmount metrics.
- 14-month daily lookback, 38-month monthly.

Weaknesses:

- API cost: **$0.01 per request**. A naive dashboard that fires Cost Explorer on every page-load can rack up meaningful bills.
- Two-dimension group-by maximum (can't group by service + region + tag simultaneously).
- No resource-level detail.
- Tag dimensions take 24 h to appear after tag activation.
- Rate-limited; easy to hit concurrent-query throttles from a chat agent.

**Metric cheat-sheet** (the `AmortizedCost` decision is the single most important FinOps choice):

| Metric | What it is | When to use |
|----|----|----|
| **UnblendedCost** | Raw cash cost charged to the account for the period | Matches your invoice line-item if you only look at Usage |
| **AmortizedCost** | Spreads RI/SP upfront fees across the term; treats committed usage as if paid hourly | **Default choice for FinOps dashboards** — shows what each service "really" costs |
| **NetUnblendedCost** | UnblendedCost minus AWS credits, discounts, refunds | Use when reporting to Finance |
| **NetAmortizedCost** | AmortizedCost minus credits/discounts/refunds | **Best for chargeback/showback to teams** |
| **BlendedCost** | Average rate across consolidated-billing family (legacy) | Rarely useful; avoid |
| **UsageQuantity** | Raw service units (vCPU-hr, GB-mo, requests, etc.) | Driver-based costing, unit economics |
| **NormalizedUsageAmount** | Usage converted to normalized units (used for EC2 instance-size flexibility) | RI analytics |

Example call:

```python
ce = boto3.client("ce")
resp = ce.get_cost_and_usage(
    TimePeriod={"Start": "2026-04-01", "End": "2026-04-23"},
    Granularity="DAILY",
    Metrics=["NetAmortizedCost", "UsageQuantity"],
    GroupBy=[
        {"Type": "DIMENSION", "Key": "SERVICE"},
        {"Type": "TAG",       "Key": "Team"},
    ],
    Filter={"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}},
)
```

<https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html>

### Tertiary

- **Budgets API** (`aws budgets describe-budgets`) — target vs actual spend, coverage budgets for RI/SP. Good for alert thresholds.
- **Cost Anomaly Detection** (`aws ce get-anomalies`) — AWS's own ML anomaly detector; free to read, useful as an alerting channel. Create a monitor per account or per service, set threshold expressions, and query anomalies via API.
- **AWS Cost Categories** (`aws ce list-cost-category-definitions`) — user-defined groupings (e.g. "Team/DataEng/Staging") that can be used as a dimension.
- **Rightsizing Recommendations API** (`aws ce get-rightsizing-recommendation`).
- **Savings Plans Utilization / Coverage** (`get_savings_plans_utilization`, `get_savings_plans_coverage`, `get_savings_plans_purchase_recommendation`) — free.
- **Reserved Instances APIs** (`describe_reserved_instances`, `get_reservation_utilization`, `get_reservation_coverage`).
- **Service Quotas API** (`service-quotas list-service-quotas`) — surface limits that block Costly sync or customer workloads.
- **Per-service list APIs** for inventory enrichment:
  - EC2: `describe_instances`, `describe_volumes`, `describe_addresses`, `describe_snapshots`, `describe_reserved_instances`
  - S3: `list_buckets`, `get_bucket_lifecycle_configuration`, `get_bucket_versioning`, `get_bucket_metrics_configuration`
  - Lambda: `list_functions`, `get_function_configuration`
  - RDS: `describe_db_instances`, `describe_db_clusters`, `describe_db_snapshots`
  - DynamoDB: `list_tables`, `describe_table`, `describe_contributor_insights`
  - Redshift: `describe_clusters`, `describe_reserved_nodes`
  - ElastiCache: `describe_cache_clusters`
  - OpenSearch: `describe_domains`
  - SageMaker: `list_endpoints`, `list_notebook_instances`, `list_training_jobs`
  - EMR: `list_clusters`, `describe_cluster`
  - EKS: `list_clusters`, `describe_cluster`, `list_nodegroups`
  - ECS: `list_clusters`, `list_services`, `list_tasks`
  - Glue: `get_jobs`, `get_crawlers`
  - MSK: `list_clusters_v2`
  - Kinesis: `list_streams`, `describe_stream`
  - Step Functions: `list_state_machines`
  - Bedrock: `list_foundation_models`, `list_model_invocation_logging_configurations`
  - CloudWatch Logs: `describe_log_groups`, `describe_metric_filters`, `describe_subscription_filters`

### Gotchas

- **Linked / consolidated billing.** Costs flow to the payer account. Linked accounts see their own usage via `LINKED_ACCOUNT` dimension. Credentials for the payer account are required to get the full picture.
- **RI/SP amortization.** AWS splits upfront fees into daily amortization (`reservation_amortized_upfront_cost_for_usage` in CUR). `UnblendedCost` does **not** include this — use `AmortizedCost` to see the true burdened rate. For chargeback, use `NetAmortizedCost`.
- **Marketplace accounting.** Marketplace line items roll up as `AWSMarketplace` unless you parse `line_item_product_code`. Ask customers which Marketplace vendors they use so you can split Databricks, Snowflake, MongoDB, Confluent out of the AWS total.
- **Credit application.** Credits apply to UnblendedCost first, then amortized RI/SP. When a month hits its credit cap, the daily rate looks like it "jumps" — this is expected. Net* metrics account for credits.
- **Refund timing.** Refunds appear as `RECORD_TYPE = Refund` with negative cost, often 30–60 days after the original charge. Filter them in or out depending on the question.
- **Data transfer peculiarities.** Data transfer is aggregated across all services before hitting the 10TB/40TB/100TB tier breaks. "EC2-Other" on Cost Explorer is a catch-all that hides EBS volumes, snapshots, NAT Gateway processing, and data transfer — always drill into `USAGE_TYPE` sub-dimension. The **2024 public IPv4 charge** ($0.005/hr per IP) surfaces as usage type `PublicIpv4:...`.
- **KMS charges buried everywhere.** Customer-managed keys cost $1/key-month + $0.03/10K requests; an EBS volume encrypted with a CMK triggers KMS requests on every attach/mount; S3 SSE-KMS triggers a KMS call per object operation.
- **Savings Plan "waste".** `savings_plan_negation_unused_commitment` in CUR shows hours the commit was not covered by eligible usage — this is real money spent on nothing. Track it.
- **Tag propagation lag.** Activating a cost-allocation tag takes up to 24 hours to appear in Cost Explorer / CUR. Historical data is not back-tagged.
- **`UsageQuantity` unit aliasing.** Same unit string means different things per service ("Hrs" for EC2 vs "GigaByteMonth" for S3). Always normalize by `line_item_usage_type` before summing.

## Schema / Fields Available

### CUR 2.0 (selected core columns — full dictionary has 150+ fields)

| Column | Type | Meaning |
|----|----|----|
| `identity_line_item_id` | string | Unique line-item key |
| `identity_time_interval` | interval | Hourly period |
| `bill_bill_type` | string | Anniversary, Purchase, Refund |
| `bill_billing_period_start_date` | timestamp | Month start |
| `bill_payer_account_id` | string | Payer (master) account |
| `line_item_usage_account_id` | string | Linked account where usage occurred |
| `line_item_line_item_type` | string | Usage, DiscountedUsage, SavingsPlanCoveredUsage, SavingsPlanNegation, RIFee, Fee, Refund, Credit, Tax |
| `line_item_product_code` | string | e.g. AmazonEC2, AmazonS3 |
| `line_item_usage_type` | string | e.g. BoxUsage:m6i.xlarge, EBS:VolumeUsage.gp3 |
| `line_item_operation` | string | e.g. RunInstances, CreateBucket |
| `line_item_resource_id` | string | ARN or resource ID (requires `INCLUDE_RESOURCES=true`) |
| `line_item_usage_start_date` | timestamp | Hourly |
| `line_item_usage_amount` | double | Quantity |
| `line_item_unblended_rate` | string | Public per-unit rate |
| `line_item_unblended_cost` | double | Cash cost for the hour |
| `line_item_currency_code` | string | USD by default |
| `line_item_availability_zone` | string | |
| `product_region` | string | |
| `product_instance_type` | string | |
| `product_operating_system` | string | |
| `product_tenancy` | string | |
| `pricing_public_on_demand_cost` | double | Pre-discount rate * quantity |
| `pricing_term` | string | OnDemand, Reserved, SavingsPlan, Spot |
| `reservation_arn` | string | RI identifier |
| `reservation_effective_cost` | double | Amortized RI cost per hour |
| `reservation_amortized_upfront_fee_for_billing_period` | double | |
| `reservation_recurring_fee_for_usage` | double | |
| `savings_plan_arn` | string | |
| `savings_plan_savings_plan_effective_cost` | double | Amortized SP cost per hour |
| `savings_plan_amortized_upfront_commitment_for_billing_period` | double | |
| `savings_plan_recurring_commitment_for_billing_period` | double | |
| `savings_plan_negation_unused_commitment` | double | Wasted commit dollars |
| `resource_tags` (map) or `resource_tags_user_<TagKey>` (flattened) | string | Cost allocation tags |
| `cost_category_<CategoryName>` | string | User-defined Cost Category values |
| `discount_bundled_discount` / `discount_total_discount` | double | EDP/PPA private discounts |
| `split_line_item_actual_usage` | double | Split cost allocation (EKS) |
| `split_line_item_reserved_usage` | double | |
| `split_line_item_split_cost` | double | Allocated cost per Kubernetes workload |

Full reference: <https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2.html>

### FOCUS 1.2 (core columns)

`BillingPeriodStart`, `BillingPeriodEnd`, `ChargePeriodStart`, `ChargePeriodEnd`, `BilledCost`, `EffectiveCost`, `ListCost`, `ContractedCost`, `CommitmentDiscountType`, `CommitmentDiscountCategory`, `ChargeCategory`, `ChargeClass`, `ChargeFrequency`, `Provider`, `ServiceName`, `ServiceCategory`, `SubAccountId`, `SubAccountName`, `Region`, `ResourceId`, `ResourceType`, `ResourceName`, `PricingCategory`, `PricingQuantity`, `PricingUnit`, `SkuId`, `SkuPriceId`, `Tags` (map). Full spec: <https://focus.finops.org/focus-specification/>

### Cost Explorer `GetCostAndUsage` Response (per-period per-group shape)

```json
{
  "ResultsByTime": [
    {
      "TimePeriod": {"Start": "2026-04-22", "End": "2026-04-23"},
      "Total": {"NetAmortizedCost": {"Amount": "123.45", "Unit": "USD"}},
      "Groups": [
        {
          "Keys": ["Amazon Simple Storage Service"],
          "Metrics": {
            "NetAmortizedCost": {"Amount": "12.34", "Unit": "USD"},
            "UsageQuantity": {"Amount": "1024.5", "Unit": "GB-Mo"}
          }
        }
      ],
      "Estimated": false
    }
  ],
  "DimensionValueAttributes": [...],
  "NextPageToken": null
}
```

## Grouping Dimensions

Cost Explorer supports these as `GroupBy.Key`:

| Dimension | What it unlocks |
|----|----|
| `SERVICE` | Top-level split across the ~250 AWS services. Costly's current default. |
| `LINKED_ACCOUNT` | Per-linked-account roll-up in consolidated billing. Essential for payer-level reporting. |
| `USAGE_TYPE` | Granular sub-service (e.g. `USW2-BoxUsage:m6i.xlarge`, `DataTransfer-Out-Bytes`). Needed to split "EC2-Other" into EBS vs data transfer vs EIP. |
| `OPERATION` | API operation (RunInstances, GetObject). Useful combined with USAGE_TYPE for unit-economics. |
| `REGION` | us-east-1, us-west-2, ... — region-sprawl detection. |
| `AZ` | Per-availability-zone (shows cross-AZ data transfer). |
| `INSTANCE_TYPE` | e.g. m6i.xlarge — for EC2/RDS/ElastiCache/Redshift rightsizing. |
| `RECORD_TYPE` | `Usage`, `Credit`, `Refund`, `Fee`, `Tax`, `RIFee`, `SavingsPlanUpfrontFee`, `SavingsPlanRecurringFee`, `SavingsPlanCoveredUsage`, `SavingsPlanNegation`, `DiscountedUsage`. Filter on this to include/exclude credits. |
| `TAG` | User cost-allocation tags (activate first in Billing console). Key to chargeback. |
| `COST_CATEGORY` | User-defined hierarchical groupings. |
| `PURCHASE_TYPE` | OnDemand, Reserved, Spot, SavingsPlan. Coverage analysis. |
| `PAYMENT_OPTION` | AllUpfront, PartialUpfront, NoUpfront. |
| `PLATFORM` | Linux/UNIX, Windows, RHEL, SUSE, etc. |
| `DATABASE_ENGINE` | MySQL, PostgreSQL, Aurora, Oracle, SQL Server. |
| `INSTANCE_TYPE_FAMILY` | m6i, r6g, c7g. |
| `LEGAL_ENTITY_NAME` | Amazon Web Services, Inc. vs Amazon.com Services LLC — impacts tax. |
| `INVOICING_ENTITY` | Same, for invoicing. |
| `SCOPE`, `SUBSCRIPTION_ID` | Savings Plans scope. |
| `RESOURCE_ID` | Only in CUR; not in Cost Explorer GetCostAndUsage (use `GetCostAndUsageWithResources` limited to EC2). |
| `TENANCY` | Shared, Dedicated, Host. |
| `DEPLOYMENT_OPTION` | Single-AZ, Multi-AZ. |

## Open-Source Tools

### FinOps / Cost intelligence

| Project | URL | Stars (Apr 2026) | License | Data source | Status |
|----|----|----|----|----|----|
| **OpenCost** | <https://github.com/opencost/opencost> | 5.5K | Apache 2.0 | K8s pod metrics + CUR | CNCF incubating; the reference implementation of the OpenCost spec for Kubernetes cost allocation |
| **Kubecost** | <https://github.com/kubecost/cost-analyzer-helm-chart> | 1.1K (chart) | Apache 2.0 (OSS tier) | CUR + K8s | Built on OpenCost; paid tier adds federation + governance |
| **Komiser** | <https://github.com/tailwarden/komiser> | 4.6K | Apache 2.0 | Resource inventory + CUR | Multi-cloud; last commit Jan 2024 (Tailwarden is now SaaS-first) |
| **Infracost** | <https://github.com/infracost/infracost> | 11.5K | Apache 2.0 | Terraform plan + AWS Price List | Pre-deploy estimation; CI/CD plugin |
| **Cloud Custodian (c7n)** | <https://github.com/cloud-custodian/cloud-custodian> | 5.3K | Apache 2.0 | AWS APIs + CUR | Policy engine for security + cost — widely used for stale-resource cleanup |
| **aws-nuke** | <https://github.com/rebuy-de/aws-nuke> | 5.7K | MIT | AWS APIs | Not cost-focused, but kills dev accounts between uses; saves money |
| **steampipe-mod-aws-thrifty** | <https://github.com/turbot/steampipe-mod-aws-thrifty> | ~200 | Apache 2.0 | Steampipe CUR plugin | Ready-made SQL queries + dashboards for EC2/RDS/EBS/S3 waste |
| **aws-cost-explorer-python** (AWS Samples) | <https://github.com/aws-samples/aws-cost-explorer-report> | ~600 | MIT-0 | Cost Explorer API | AWS's own reference CE report generator |
| **aws-finops-dashboard** | <https://github.com/ravikiranvm/aws-finops-dashboard> | ~250 | MIT | Cost Explorer | Streamlit dashboard; multi-account |
| **Cost Intelligence Dashboard (CID) / CUDOS** | <https://github.com/awslabs/cid-framework> | ~600 | MIT-0 | CUR via Athena | AWS-provided QuickSight template — the canonical CUR dashboard; installable via `cid-cmd` CLI |
| **FOCUS-converter (FinOps Foundation)** | <https://github.com/finops-project/focus-converter> | ~100 | Apache 2.0 | CUR | Converts CUR → FOCUS 1.x (now obsoleted by AWS-native FOCUS export) |
| **Nops / ProsperOps core (not OSS)** | — | — | — | — | Commercial — listed for reference |
| **CloudHealth / Apptio core (not OSS)** | — | — | — | — | Commercial |
| **finops-crash-course** | <https://github.com/finopsfoundation/finops-certified-practitioner-study-guide> | ~700 | CC-BY-SA | — | FinOps Foundation practitioner study guide (non-code) |
| **aws-rightsize-lambda** | <https://github.com/awslabs/aws-lambda-power-tuning> | 6.2K | Apache 2.0 | Lambda | Memory/power tuner; direct Lambda cost optimizer |
| **AutoSpotting** | <https://github.com/AutoSpotting/AutoSpotting> | 2.3K | OSL-3.0 | ASG + Spot | Converts ASG on-demand → Spot at runtime |
| **ec2.shop** | <https://ec2.shop/> + <https://github.com/yeo/ec2.shop> | ~700 | MIT | EC2 pricing scraped | Fast EC2 price comparison site |
| **ec2-instances.info / instances.vantage.sh** | <https://github.com/vantage-sh/ec2instances.info> | 4.7K | MIT | AWS Price List | Canonical instance-type comparison (Vantage maintains it as community good) |
| **aws-pricing** (npm) | <https://github.com/arabold/aws-pricing> | ~100 | MIT | AWS Price List | Node client for Pricing API |
| **py-moto** | <https://github.com/getmoto/moto> | 8.1K | Apache 2.0 | — | Mock AWS for tests — useful when testing connectors without touching real accounts |
| **PromQL / CloudWatch exporters** (`yace`) | <https://github.com/nerdswords/yet-another-cloudwatch-exporter> | 1.4K | Apache 2.0 | CloudWatch | Scrape CloudWatch metrics into Prometheus for cost-adjacent observability |
| **aws-cost-cli** | <https://github.com/kamranahmedse/aws-cost-cli> | 2.7K | MIT | Cost Explorer | Slack-integrated daily cost summary |
| **SlackOps / cost-notifier (AWS Samples)** | <https://github.com/aws-samples/aws-budget-notifier> | — | MIT-0 | Budgets | Slack + SNS daily/weekly cost posts |
| **GitHub — awesome-finops** | <https://github.com/jmcarp/awesome-finops> | ~700 | CC0 | — | Curated list; good starting point |

Commercial references (not OSS, listed per user request):

- **PyCloudLens** — no public repo; appears to be a branding of Cloudyn-era tooling.
- **CloudCheckr** (Spot/NetApp) — SaaS; strong governance + compliance, weaker on unit economics.

### Near-term bets for Costly

1. Adopt **FOCUS 1.2** schema internally — single source-of-truth for AWS+Azure+GCP.
2. Integrate **OpenCost** as the Kubernetes cost engine when we ship EKS drill-down (instead of rebuilding pod-level attribution).
3. Use the **Cost Intelligence Dashboard (CID)** SQL queries as reference for advanced views (RI/SP coverage, Graviton opportunity, idle-resource heatmap).
4. Use **Infracost** for pre-deploy "what-if" recommendations in the chat agent.
5. Ship **Cloud Custodian** policy templates as "one-click" remediations for known waste patterns.

## How Competitors Handle AWS

| Vendor | URL | AWS Integration Depth | What they show that Costly currently doesn't |
|----|----|----|----|
| **Vantage** | <https://www.vantage.sh/> | CUR 2.0 ingestion, 40+ integrations, Autopilot for SP auto-buy, Kubernetes cost (OpenCost), Virtual Tags, Annotations, Budget+Forecast per-team. Best-in-class product design. | Autopilot (SP auto-purchase), virtual tags on untagged resources, cost reports as shareable links, Anomaly detection w/ Slack auto-diagnosis, Active Directory–based team rollups, Terraform-integrated IaC cost. |
| **CloudZero** | <https://www.cloudzero.com/> | CUR ingestion + CostFormation DSL for allocation. AnyCost connector for non-AWS. Dimensions, cost-per-customer unit economics. | Cost-per-customer / cost-per-feature unit metrics (CostFormation — code-defined allocation), hypothesis testing, engineer-level "Bill of Materials" views. |
| **Finout** | <https://www.finout.io/> | MegaBill unified billing across clouds + SaaS. CostGuard anomaly. Virtual Tags with regex/lookup/CSV. Kubernetes cost from Prometheus or K8s state metrics. | MegaBill treats Snowflake, Datadog, GitHub as first-class alongside AWS — so a single chart can show "cost per API call" spanning AWS+Snowflake+Datadog. |
| **Datadog Cloud Cost Management** | <https://docs.datadoghq.com/cloud_cost_management/aws/> | Full CUR ingestion; integrates with Datadog APM, infra, RUM, logs. | "Cost per request" via APM trace correlation, anomaly detection shared with infra alerts, SLO-tied cost views. |
| **CloudChipr** | <https://cloudchipr.com/> | Resource inventory + Cost Explorer + CUR. Automation workflows (terminate idle, stop non-prod). Commitments marketplace. | Automation engine that actually deletes/stops resources on schedule, Commitments Marketplace to sell unused RIs. |
| **Amberflo** | <https://www.amberflo.io/> | Strong usage-based pricing / metering focus; less classic FinOps. | Customer metering + invoicing; adjacent to cost intelligence. |
| **Anodot Cloud Cost** | <https://www.anodot.com/cost-management/> | AI-led anomaly detection + forecast. CUR + Cost Explorer. | Forecast confidence intervals, unit economics, K8s + multi-cloud. |
| **Flexera One / Apptio Cloudability** | <https://www.flexera.com/products/spend-optimization/flexera-one-finops> | Enterprise incumbent. Full CUR + ITFM. Cloudability rightsizing + RI planner. | ITFM mapping to ServiceNow, chargeback GL, procurement workflows, TBM (Technology Business Management) taxonomies. |
| **Harness Cloud Cost Management** | <https://www.harness.io/products/cloud-cost> | CUR + K8s + CD integration. Asset governance. Cluster orchestrator. | Auto-stopping idle workloads, AutoScale recommendations, CI/CD-gated cost checks. |
| **Zesty** | <https://zesty.co/> | Real-time AWS commit optimization (Zesty Disk, Zesty Commitment Manager). Swaps SP/RI in/out every hour. | Dynamic SP laddering, EBS auto-scaling (file-system-aware). |
| **Granulate** (Intel) | <https://granulate.io/> | Runtime optimization agent — shrinks cost by ~20% via kernel-level tuning. | Runtime tuning, not cost reporting. |
| **ProsperOps** | <https://www.prosperops.com/> | RI + SP "AutoPilot" — actively trades convertibles to maximize savings. | Effective Savings Rate benchmark, automated 3-year ladder, marketplace RI arbitrage. |
| **Usage AI / USE.AI** | <https://usage.ai/> | RI marketplace + SP recommendations. | Commitment trading engine. |
| **Spot by NetApp (formerly Spotinst)** | <https://spot.io/> | Elastigroup, Ocean (K8s), Eco (SP optimizer). | Blended On-Demand+Spot clusters with SLA, K8s right-sizing via Ocean. |
| **Cast AI** | <https://cast.ai/> | K8s-focused; automated rebalancing, bin-packing, Spot migration. | Node-level automation with SLA guardrails. |
| **nOps** | <https://www.nops.io/> | Commitment management, idle detection, Share Savings model (take % of savings). | Rebate business model. |

### Screenshot summaries (public marketing assets, Apr 2026)

- **Vantage "Cost Reports"**: left panel = time-series area chart grouped by any dimension; right panel = ranked table with MoM + delta %; top controls = date/granularity/grouping/filters; "Save as Report" and "Share link" are first-class.
- **CloudZero "Cost per Customer"**: single line chart with per-customer series; drop-down to swap unit economics (per-user, per-API-call, per-MB); "what's driving this spike?" prompt opens an AI explainer.
- **Finout "MegaBill"**: waterfall of AWS vs GCP vs Snowflake vs Datadog with drill-through. Virtual tags are editable in-app like a spreadsheet.
- **Datadog CCM**: embeds cost under the same timeline as APM traces — "this endpoint costs $X/day" appears as a side-panel in APM.
- **CloudChipr "Workflows"**: drag-and-drop IFTTT-style ("if idle for 14 days AND tag Environment != prod, stop"). 

Cost-display conventions Costly should borrow:

- Default to **NetAmortizedCost** across the dashboard.
- Surface **MoM delta %** and a 30-day sparkline next to every line-item.
- Always show **Effective Savings Rate** (savings / (savings + bill)) prominently.
- Always show **SP/RI coverage %** and **SP utilization %**.
- Always show **"what-if"**: "If you had 100% SP coverage, you'd save $X/mo."

## Books / Published Material

| Title | Author(s) | Publisher / Year | Why it matters |
|----|----|----|----|
| **Cloud FinOps (2nd ed.)** | J. R. Storment & Mike Fuller | O'Reilly, 2023 | Canonical FinOps textbook; FinOps Foundation doctrine. <https://www.oreilly.com/library/view/cloud-finops-2nd/9781492098348/> |
| **AWS Cost Optimization Strategies: A Practical Guide** | Praveen Dharmavaram | Packt, 2024 | Hands-on with CE, CUR, Compute Optimizer; decent but workbook-level |
| **AWS Well-Architected Framework: Cost Optimization Pillar** | AWS | AWS Whitepapers, updated Feb 2024 | Free — the official AWS viewpoint on cost design. <https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html> |
| **AWS Prescriptive Guidance — FinOps** | AWS | AWS Docs Library, ongoing | Detailed playbooks. <https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-finops/introduction.html> |
| **The FinOps Way (essays)** | various | FinOps Foundation Insights, ongoing | <https://www.finops.org/insights/> |
| **FinOps Certified Practitioner Study Guide** | FinOps Foundation | 2024 (v2) | Free ref course |
| **FinOps Framework (Maturity Model)** | FinOps Foundation | <https://www.finops.org/framework/> | Capability map |
| **AWS re:Invent FinOps / Cost track talks** | AWS | 2024 & 2025 | Notable sessions: FIN310 "Mastering CUR 2.0", FIN203 "FinOps at Amazon.com", FIN402 "Advanced Savings Plans optimization", FIN308 "Generative AI cost at scale", FIN305 "Kubernetes cost observability with CID". YouTube AWS Events channel. |
| **AWS Partner Central — FinOps Competency Playbook** | AWS | 2024 | Blueprint for MSPs to consult on cost |
| **Corey Quinn — Last Week in AWS** | Duckbill Group | Newsletter 2016– | <https://www.lastweekinaws.com/> — industry-shaping cost commentary |
| **Corey Quinn — AWS Morning Brief podcast** | Duckbill Group | | Short-form; billing focus |
| **A Cloud Guru / Pluralsight — FinOps Learning Paths** | | 2024 courses | Intermediate-level, video |
| **AWS Skill Builder — "AWS Cloud Financial Management"** | AWS | Free | <https://skillbuilder.aws/> |
| **AWS Certified Cloud Practitioner (CLF-C02)** | AWS | 2023 refresh | Chapter 5 (Billing, Pricing, Support) is a useful foundation |
| **Stephen Barr — "AWS Cost Categories deep-dive"** | AWS blog | 2022 | <https://aws.amazon.com/blogs/aws-cloud-financial-management/deep-dive-into-aws-cost-categories/> |
| **Stephanie Gooch — "Optimize Amazon EC2 for cost with a multidimensional approach"** | AWS blog | 2024 | <https://aws.amazon.com/blogs/aws-cloud-financial-management/> |
| **"Amazon Q Developer and cost management"** | AWS blog | 2024 | How Q surfaces cost recommendations |
| **"Analyzing your AWS Cost and Usage Reports with Cloud Intelligence Dashboards"** | AWS blog | 2023 | <https://aws.amazon.com/blogs/aws-cloud-financial-management/> |
| **"Cost optimization techniques for Amazon Bedrock"** | AWS blog | Oct 2024 | <https://aws.amazon.com/blogs/machine-learning/> |
| **"FOCUS 1.2 GA on AWS — what's new"** | AWS Cloud Financial Management blog | Apr 2025 | FOCUS-format export |
| **"Graviton best practices"** | AWS whitepaper | 2024 | Migration patterns + benchmarks |

## Vendor Documentation Crawl

All URLs verified during Apr 2026 research pass.

**Billing & Invoicing**
- <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-what-is.html>
- <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/consolidated-billing.html>
- <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-procedure.html>

**Cost and Usage Reports (CUR) 2.0 + FOCUS 1.2**
- <https://docs.aws.amazon.com/cur/latest/userguide/what-is-cur.html>
- <https://docs.aws.amazon.com/cur/latest/userguide/dataexports-create-focus.html>
- <https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2.html>
- FOCUS spec: <https://focus.finops.org/focus-specification/>
- FOCUS 1.2 release notes: <https://focus.finops.org/version-1-2-release-notes/>

**Cost Explorer**
- <https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html>
- <https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsageWithResources.html>
- <https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetRightsizingRecommendation.html>
- <https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansPurchaseRecommendation.html>

**Budgets & Anomaly Detection**
- <https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html>
- <https://docs.aws.amazon.com/cost-management/latest/userguide/manage-ad.html>

**Pricing API**
- <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html>
- <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-price-list-api.html>

**Per-service pricing**
- EC2: <https://aws.amazon.com/ec2/pricing/>
- S3: <https://aws.amazon.com/s3/pricing/>
- RDS: <https://aws.amazon.com/rds/pricing/>
- Aurora: <https://aws.amazon.com/rds/aurora/pricing/>
- Lambda: <https://aws.amazon.com/lambda/pricing/>
- DynamoDB: <https://aws.amazon.com/dynamodb/pricing/>
- Redshift: <https://aws.amazon.com/redshift/pricing/>
- Athena: <https://aws.amazon.com/athena/pricing/>
- Glue: <https://aws.amazon.com/glue/pricing/>
- EMR: <https://aws.amazon.com/emr/pricing/>
- EKS: <https://aws.amazon.com/eks/pricing/>
- Fargate: <https://aws.amazon.com/fargate/pricing/>
- SageMaker: <https://aws.amazon.com/sagemaker/pricing/>
- Bedrock: <https://aws.amazon.com/bedrock/pricing/>
- OpenSearch: <https://aws.amazon.com/opensearch-service/pricing/>
- Step Functions: <https://aws.amazon.com/step-functions/pricing/>
- Kinesis: <https://aws.amazon.com/kinesis/data-streams/pricing/>
- MSK: <https://aws.amazon.com/msk/pricing/>
- DataSync: <https://aws.amazon.com/datasync/pricing/>
- Transfer Family: <https://aws.amazon.com/aws-transfer-family/pricing/>
- Amazon Q: <https://aws.amazon.com/q/pricing/>

**Savings Plans & RIs**
- <https://docs.aws.amazon.com/savingsplans/latest/userguide/what-is-savings-plans.html>
- <https://aws.amazon.com/savingsplans/compute-pricing/>
- <https://aws.amazon.com/savingsplans/sagemaker-pricing/>
- <https://aws.amazon.com/ec2/pricing/reserved-instances/pricing/>
- <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-reserved-instances.html>

**Well-Architected Cost Optimization**
- <https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html>

**AWS Cloud Financial Management blog**
- <https://aws.amazon.com/blogs/aws-cloud-financial-management/>

### 2025–2026 Changes to Know

- **FOCUS 1.2 GA (April 2025)** — AWS can now export CUR in FOCUS 1.2 natively; mandatory for multi-cloud FinOps.
- **Amazon Q Developer billing changes (2025)** — added per-seat $19 Pro tier and per-action usage metering for agent runs.
- **Bedrock Agents billing (2024)** — model invocations are billed separately from orchestration; Knowledge Base retrieval triggers OpenSearch Serverless OCU charges.
- **EC2 Public IPv4 charge** — since Feb 1, 2024: $0.005/hr per public IPv4.
- **Aurora I/O-Optimized** (2023) — 30% higher instance price but $0 I/O charge; break-even ~25% of cost spent on I/O.
- **DynamoDB on-demand price cut** (Nov 2024) — ~50% reduction on throughput units; IA tier GA.
- **Redshift Serverless AI-driven Price-Performance** (2024) — lets you target lower cost vs performance.
- **S3 Express One Zone GA** (Nov 2023), continued pricing refinement.
- **Lambda SnapStart for Python/.NET** (2024) — faster cold starts, new cache + restore fees.
- **Amazon Nova models** (Dec 2024) — cheaper Bedrock option for general text.
- **Graviton4 (r8g, m8g)** — 2024/2025 general availability; ~30% cheaper than x86 equivalents for equivalent perf.
- **EKS Auto Mode** (Dec 2024).
- **SageMaker Unified Studio** (preview Dec 2024; billing per-underlying-resource).
- **New regions** since 2024: Mexico (mx-central-1), Malaysia (ap-southeast-5), Thailand (ap-southeast-7), Taipei (ap-east-2), Saudi Arabia (me-central-2 in preview).
- **Savings Plans flexibility** — Compute SP now covers Lambda in all regions + SageMaker inference endpoints (expansion pending 2025 announcement).

## Best Practices (synthesized)

Ranked by typical dollar impact:

1. **Adopt FOCUS 1.2** as the internal schema, but keep CUR 2.0 as source of truth. Unlocks multi-cloud later.
2. **Default to NetAmortizedCost** in all dashboards. Never show raw UnblendedCost in a FinOps dashboard — it misrepresents commitment economics.
3. **Tag strategy**: mandate `Team`, `Environment`, `Project`, `CostCenter`, `Service` via AWS Organizations SCP + AWS Config rule. Enforce at creation time.
4. **Target SP/RI coverage > 80%** on steady compute. Use Compute Savings Plans for flex (EC2+Fargate+Lambda). Track coverage weekly; set Budget alerts at 75% floor.
5. **Commitment elasticity**: ladder 1y no-upfront SPs so ~1/12 expires each month, allowing right-sizing. Avoid 3y commits except for >80% confidence workloads.
6. **Multi-account rollup**: query at payer level but surface per-linked-account views. Use Cost Categories for cross-cutting groupings (e.g. "Product line A" spans 4 accounts).
7. **Anomaly alerting**: enable AWS Cost Anomaly Detection with $50 threshold on monitor-per-service. Supplement with in-product anomaly detection based on 7-day moving-average + 30% spike rule (OptScale formula).
8. **VPC endpoints**: Gateway endpoint for S3/DynamoDB (free), Interface endpoints for SQS/Kinesis/STS when cross-AZ NAT processing exceeds $100/mo.
9. **Graviton-first** policy for new workloads (EC2, RDS, Aurora, ElastiCache, OpenSearch, Lambda) unless ISA-locked.
10. **S3 lifecycle by default**: every new bucket gets a lifecycle policy (≥30 days → IA, ≥90 days → Glacier Flexible, ≥365 days → Deep Archive), abort-incomplete-multipart after 7 days, expire non-current versions after 30 days.
11. **Rightsize quarterly** using Compute Optimizer + CUR usage data (99th-percentile CPU, 80% target).
12. **EKS/ECS cost allocation** via OpenCost + Split Cost Allocation Data (SCAD) in CUR 2.0.
13. **Bedrock governance**: log every invocation to CloudWatch with `caller_id` tag; dashboard per-team token spend; enable Guardrails cost tracking.
14. **CloudWatch log discipline**: set retention on every Log Group (default is NEVER expire); ship high-volume logs to S3 via subscription filter (40% cheaper storage).
15. **Shutdown policies**: dev/staging EC2/RDS/Redshift stopped nights + weekends (saves ~65% of their cost).

## Costly's Current Connector Status

**File:** `backend/app/services/connectors/aws_connector.py` (300 LOC).

**Knowledge doc:** `backend/app/knowledge/aws.md` (846 LOC). Extensive pricing + waste-pattern knowledge is already encoded — this is a strong asset and the chat agent consumes it.

**What the connector does today:**

1. Authenticates with `aws_access_key_id` + `aws_secret_access_key` + `region`. Uses `sts:GetCallerIdentity` to fetch the account ID.
2. `test_connection()` — one-day Cost Explorer probe (`GetCostAndUsage` with `UnblendedCost`).
3. `fetch_costs(days=30)` — Cost Explorer `GetCostAndUsage` daily, grouped by **SERVICE**, metrics `UnblendedCost` + `UsageQuantity`. Emits one `UnifiedCost` per service per day.
4. Inventory enrichment (zero-cost rows just for UI inventory):
   - **S3 buckets** via `list_buckets` + CloudWatch `BucketSizeBytes` + `NumberOfObjects` + `get_bucket_location`.
   - **EC2 instances** via `describe_instances` (reads Name tag, instance_type, state, instance_id).
   - **Lambda functions** via `list_functions` (runtime, memory).

**Service coverage in `SERVICE_CATEGORY_MAP`** (maps display names → Costly categories):

| # | AWS Service (long name) | Display | Category |
|---|---|---|---|
| 1 | Amazon Simple Storage Service | S3 | storage |
| 2 | Amazon DynamoDB | DynamoDB | storage |
| 3 | Amazon Redshift | Redshift | compute |
| 4 | Amazon Athena | Athena | compute |
| 5 | Amazon EMR | EMR | compute |
| 6 | AWS Lambda | Lambda | compute |
| 7 | Amazon Elastic Container Service | ECS | compute |
| 8 | Amazon Elastic Kubernetes Service | EKS | compute |
| 9 | Amazon Elastic Compute Cloud - Compute | EC2 | compute |
| 10 | EC2 - Other | EC2 Other | compute |
| 11 | Amazon Managed Workflows for Apache Airflow | MWAA | orchestration |
| 12 | AWS Step Functions | Step Functions | orchestration |
| 13 | Amazon CloudWatch | CloudWatch | orchestration |
| 14 | AWS Glue | Glue | transformation |
| 15 | Amazon Kinesis | Kinesis | ingestion |
| 16 | AWS Database Migration Service | DMS | ingestion |
| 17 | Amazon Simple Queue Service | SQS | networking |
| 18 | Amazon Managed Streaming for Apache Kafka | MSK | networking |
| 19 | AWS Data Transfer | Data Transfer | networking |
| 20 | Amazon Bedrock | Bedrock | ai_inference |
| 21 | Amazon SageMaker | SageMaker | ml_training |
| 22 | Amazon QuickSight | QuickSight | serving |
| 23 | Amazon Relational Database Service | RDS | storage |
| 24 | Amazon Registrar | Registrar | networking |
| 25 | Amazon Route 53 | Route 53 | networking |

(That's 25 mapped services — counted as "21 services" in docs since EC2/EC2-Other and the two registrar/route53 entries collapse to fewer distinct categories, and Aurora/ElastiCache/OpenSearch/Fargate/etc. are not yet mapped.)

**How data flows through the system** (per `CLAUDE.md`): `AWSConnector.fetch_costs()` → list[`UnifiedCost`] → `services/unified_costs.py` stores in MongoDB → `routers/costs.py` serves `/api/costs` → Next.js dashboard.

## Gaps Relative to Best Practice

Ordered by severity:

1. **No CUR 2.0 / FOCUS path.** Only Cost Explorer is supported, so customers can't get resource-level attribution or amortized detail. Biggest delta vs Vantage/CloudZero/Finout.
2. **`UnblendedCost` only.** We're not showing amortized / net-amortized / net-unblended. Customers with RIs or SPs see misleading numbers.
3. **No Savings Plans / RI visibility.** No coverage, utilization, recommendations, or waste (negation_unused_commitment) tracking.
4. **No tag / cost category grouping.** `GroupBy` is hardcoded to `SERVICE`; we can't do per-team chargeback or environment split. Customers routinely ask "who owns this spend?" and we can't answer.
5. **No `LINKED_ACCOUNT` dimension.** Multi-account payers see only the payer-level roll-up; can't drill into linked accounts.
6. **Missing services** in `SERVICE_CATEGORY_MAP`:
   - Aurora (appears as RDS today but Aurora-specific usage types are different),
   - Fargate (rolls into ECS/EKS today, no split),
   - ElastiCache, MemoryDB, Neptune, DocumentDB, Timestream,
   - OpenSearch Service (not mapped!),
   - Amazon Q (Developer + Business),
   - CodeBuild, CodePipeline, CodeDeploy, CodeArtifact,
   - EventBridge, SNS, SES,
   - AWS Glue DataBrew, Glue Data Quality, Glue Data Catalog (split from ETL),
   - Amazon Forecast, Amazon Comprehend, Amazon Textract, Amazon Rekognition, Amazon Transcribe, Amazon Translate, Amazon Polly (AI services),
   - Amazon Managed Grafana, Amazon Managed Prometheus,
   - AWS Fargate (as first-class service),
   - Amazon CloudFront, Route 53 Resolver,
   - Amazon WorkSpaces, AppStream 2.0,
   - AWS Marketplace passthroughs (Databricks, Snowflake, MongoDB Atlas),
   - Support charges (Business/Enterprise Support line items),
   - Tax.
7. **No NAT Gateway / data transfer breakdown.** Catch-all "Data Transfer" loses the signal. Must drill `USAGE_TYPE` for `DataTransfer-Regional-Bytes`, `NatGateway-Hours`, etc.
8. **No hourly granularity.** Cost Explorer supports HOURLY for last 14 days; we only call DAILY. Hourly reveals batch-job spikes.
9. **No anomaly detection.** We aren't calling `GetAnomalies` or running our own moving-average detector on the stored series.
10. **No resource-level CloudWatch enrichment beyond S3/EC2/Lambda.** RDS, DynamoDB, EMR, Redshift, MSK, OpenSearch, SageMaker inventory all missing.
11. **Credentials.** Long-lived access keys are currently used — should move to IAM role assumption (external-ID STS pattern) or delegated OIDC.
12. **API cost** — Cost Explorer calls are $0.01 each. At scale, Costly should cache per-day aggregates in Mongo and only hit CE for deltas. (Some caching exists via `services/cache.py` but not across requests/users to the same account.)
13. **No Kubernetes cost allocation.** EKS spend is a black box at the pod level. OpenCost or SCAD (CUR 2.0 split-cost-allocation-data) needed.
14. **No commitment recommendations.** No surface for "buy a Compute Savings Plan at $X/hr to save $Y/month."
15. **No Graviton migration detector.** Can't flag "your m6i fleet would be 15% cheaper as m7g."
16. **Credits / refunds silently mixed in.** We don't filter `RECORD_TYPE` — credits inflate "spend decrease" signals.
17. **No multi-region roll-up.** `REGION` dimension unused.
18. **No IPv4 charge attribution.** The Feb 2024 public-IP charge is buried in EC2-Other.
19. **No IAM permissions audit** surfaced in-product (we have `docs/aws-iam-setup.md` but no in-app check).
20. **No per-account support-tier rollup** (Developer/Business/Enterprise % of bill).

## Roadmap

### Near-term (next 2–4 weeks)

1. Switch Cost Explorer `Metrics` to `NetAmortizedCost` + keep `UsageQuantity`. Ship side-by-side toggle (Raw vs Amortized).
2. Add `LINKED_ACCOUNT` as a second group dimension; let UI filter by account.
3. Filter out `RECORD_TYPE IN (Credit, Refund)` by default; expose as a toggle.
4. Expand `SERVICE_CATEGORY_MAP` to the 40+ services that appear in real customer accounts (list above).
5. Add tag-based grouping for a user-specified tag key (initially "Environment" or "Team"). Surface missing-tag % as a governance KPI.
6. Pull `get_savings_plans_coverage`, `get_savings_plans_utilization`, `get_reservation_coverage`, `get_reservation_utilization` — show four KPIs on the AWS dashboard.
7. Daily cache layer for Cost Explorer results — avoid burning $0.01/call on every dashboard hit.

### Medium-term (1–3 months)

8. **CUR 2.0 ingestion path**: allow customer to point Costly at an existing S3 export; Costly queries via Athena (read-only). Fall back to Cost Explorer when CUR is unavailable.
9. **Anomaly detection**: (a) consume `GetAnomalies` from AWS Cost Anomaly Detection for the zero-setup experience; (b) our own 7-day moving-average + 30% spike rule as secondary.
10. **Rightsizing recommendations**: call `GetRightsizingRecommendation` + AWS Compute Optimizer API; normalize to Costly's recommendation schema.
11. **Commitment recommendations**: call `GetSavingsPlansPurchaseRecommendation` and `GetReservationPurchaseRecommendation`, surface in UI.
12. **NAT Gateway + Data Transfer breakdown** via `USAGE_TYPE` dimension.
13. **Hourly granularity** for last 14 days on demand.
14. **Inventory enrichment** for RDS, DynamoDB, ElastiCache, OpenSearch, MSK, SageMaker endpoints, EKS clusters, ECS services.
15. **STS role-assumption auth** (external ID) as the canonical AWS creds path; deprecate long-lived keys in the UI.

### Long-term (3–9 months)

16. **FOCUS 1.2 conformance** — store AWS data in FOCUS shape internally so Azure + GCP + Snowflake + Databricks unify on the same model.
17. **Kubernetes cost allocation** via OpenCost (EKS) and CUR 2.0 Split Cost Allocation Data.
18. **Cost categories and custom allocation rules** (CloudZero-style). DSL or form-based.
19. **Forecasting** — Prophet or Amazon Forecast fallback; confidence-interval overlays.
20. **Unit economics** — cost-per-{API-call / user / GB-processed / trained-model} once tags + customer-chosen metric are plumbed.
21. **Remediation actions** — integrate Cloud Custodian policies for one-click "delete idle EBS > 30 days" / "stop non-prod nightly." Gate with approval flow.
22. **Bedrock governance module** — per-team / per-model / per-prompt token spend; guardrail cost tracking; Provisioned Throughput break-even calculator.
23. **Marketplace split** — surface Databricks/Snowflake/Mongo subscribed via AWS Marketplace as first-class line items.

## Change Log

- **2026-04-24**: Initial knowledge base created. Covers pricing for 21+ services, billing data sources (CUR 2.0 + FOCUS 1.2, Cost Explorer, Budgets, Anomaly Detection, per-service list APIs), OSS tooling landscape, competitor landscape, published reference material, a full list of current gaps vs best practice, and a phased roadmap.
- **2026-04-24 (lane/aws)**: Connector deepened.
  - Added `cost_type` credential — customers can opt into **AmortizedCost**; each row then carries `unblended_cost_usd` and `amortized_delta_usd` so the UI / chat agent can show the RI / Savings Plan benefit on every service. Closes roadmap gap "use Amortized*Cost metrics… expose UnblendedCost vs AmortizedCost as a toggle."
  - Added `cost_allocation_tag_keys` credential — Cost Explorer is queried with a second `TAG` `GroupBy` per key; the breakdown is attached as `metadata.tag_breakdown` on every service row. Closes roadmap gap "Add tag-based grouping for a user-specified tag key."
  - Added `member_account_role_arns` + `external_id` credentials — the connector iterates member ARNs, `sts:AssumeRole`s into each, queries Cost Explorer with the temporary credentials, and emits per-account `UnifiedCost` rows. Downstream `get_unified_costs` already aggregated `by_account`; now it has a real dimension to group on. Closes roadmap gap "STS role-assumption auth."
  - Frontend overview page now renders a **By Account** panel fed by the existing `/api/platforms/costs` → `by_account` field (previously computed, never shown). Also supplies demo data so the panel is visible in demo mode.
  - Tests: new `backend/tests/test_aws_connector.py` (14 new cases) parametrized across 1 / 2 / 5 accounts, plus regression guards.
