# AWS Billing & Cost Expert Knowledge Base

## Billing Model Overview

AWS bills per-service with hundreds of pricing dimensions. Key concepts:
- **On-Demand:** Pay-as-you-go, no commitment, highest rate
- **Reserved Instances (RI):** 1-3 year commitment, 30-72% savings on EC2/RDS/Redshift/ElastiCache/OpenSearch
- **Savings Plans:** Flexible $/hour commitment, 20-66% savings — Compute SP (broadest), EC2 Instance SP (deepest), SageMaker SP
- **Enterprise Discount Program (EDP):** Volume commitment ($1M+/year), 5-20% off entire bill
- **Spot Instances:** Up to 90% off EC2, but 2-minute interruption notice
- **Free Tier:** 12-month and always-free tiers exist for many services — watch for surprise charges when they expire

### How EDP Stacking Works
EDP discount applies first to list price, then RIs/Savings Plans apply on top. Example:
- List price: $1.00/hr
- 10% EDP → $0.90/hr
- 40% RI discount on $0.90 → $0.54/hr
- Total: 46% off vs 40% without EDP

### Billing Frequency & Granularity
- Billed monthly, charges accrue hourly or per-request
- Cost Explorer API: daily or monthly granularity, 14-month lookback (monthly), 12-month (daily)
- Cost and Usage Report (CUR): most granular — line-item level, hourly, delivered to S3

---

## Compute Services

### EC2 (Elastic Compute Cloud)
**Pricing model:** Per-second billing (Linux), per-hour (Windows/RHEL). Price varies by instance family, size, region, OS.

| Instance Type | Use Case | On-Demand (us-east-1) | Notes |
|--------------|----------|----------------------|-------|
| m6i.xlarge | General (Airflow, self-hosted tools) | $0.192/hr | Graviton m7g.xlarge = $0.163/hr (15% cheaper) |
| r6i.xlarge | Memory-intensive (Spark drivers) | $0.252/hr | Graviton r7g.xlarge = $0.214/hr |
| c6i.xlarge | Compute-intensive (data transforms) | $0.170/hr | Graviton c7g.xlarge = $0.145/hr |
| i3.xlarge | Storage-optimized (local NVMe) | $0.312/hr | For shuffle-heavy Spark |
| p4d.24xlarge | GPU (ML training) | $32.77/hr | Spot can be $9-12/hr |

**Common waste patterns:**
1. **Instances running 24/7 for 8hr workloads** — Use auto-scaling, Spot Fleet, or scheduled start/stop
2. **Oversized instances** — Check CloudWatch CPU/memory utilization. If <30% avg, downsize
3. **Old generation instances** — m5 → m6i → m7g (Graviton) saves 15-30% per generation
4. **Unattached EBS volumes** — $0.08/GB/month for gp3, accumulates after instance termination
5. **Elastic IPs not attached** — $0.005/hr ($3.60/month) per unattached EIP (changed 2024: now charged for ALL public IPv4 at $0.005/hr)

**Savings levers:**
- Savings Plans: 30-40% off for 1-year no-upfront
- Spot: 60-90% off for fault-tolerant workloads (Spark executors, batch jobs)
- Graviton (ARM): 15-20% cheaper, often 20-40% better performance
- Right-sizing: Use AWS Compute Optimizer recommendations

### EBS (Elastic Block Store)
| Volume Type | Price | IOPS | Throughput | Use Case |
|------------|-------|------|------------|----------|
| gp3 | $0.08/GB/mo + $0.005/IOPS (>3000) + $0.04/MBps (>125) | 3000 free | 125 MBps free | Default — most workloads |
| gp2 | $0.10/GB/mo | 3 IOPS/GB (burst to 3000) | 250 MBps | Legacy, migrate to gp3 |
| io2 | $0.125/GB/mo + $0.065/IOPS | Up to 64,000 | 1,000 MBps | High-perf databases |
| st1 | $0.045/GB/mo | N/A | 500 MBps | Sequential reads (data lakes) |
| sc1 | $0.015/GB/mo | N/A | 250 MBps | Cold storage, infrequent access |

**Gotcha:** gp2 → gp3 migration saves 20% baseline + gives you 3000 IOPS and 125 MBps free. Many teams still run gp2.

**Snapshot costs:** $0.05/GB/month. Old snapshots accumulate silently. Use AWS Backup lifecycle policies.

### Lambda
**Pricing:** $0.20 per 1M requests + $0.0000166667/GB-second (x86) or $0.0000133334 (ARM, 20% cheaper)

| Memory | Price/ms (x86) | Price/ms (ARM) |
|--------|---------------|----------------|
| 128 MB | $0.0000021 | $0.0000017 |
| 512 MB | $0.0000083 | $0.0000067 |
| 1024 MB | $0.0000167 | $0.0000133 |
| 3008 MB | $0.0000501 | $0.0000400 |
| 10240 MB | $0.0001667 | $0.0001333 |

**Common waste:**
1. **Over-provisioned memory** — Lambda scales CPU with memory. 128MB may be too little (slow = expensive), 3GB may be too much
2. **Cold starts in VPC** — VPC-attached Lambdas had 10-15s cold starts (fixed with Hyperplane ENI, but still adds latency)
3. **Provisioned Concurrency** — $0.000004167/GB-second when idle. Only use for truly latency-sensitive paths
4. **CloudWatch Logs** — Lambda logs everything. At scale, log ingestion ($0.50/GB) can exceed Lambda compute cost

**Optimization:**
- Use ARM (Graviton2) — 20% cheaper, often faster
- Power Tuning tool to find optimal memory setting
- Reduce execution time with connection pooling, SDK reuse

---

## Storage Services

### S3 (Simple Storage Service)
**Pricing:** Storage + Requests + Data Transfer

| Storage Class | Storage/GB/mo | PUT (per 1K) | GET (per 1K) | Retrieval | Min Duration |
|--------------|---------------|-------------|-------------|-----------|-------------|
| Standard | $0.023 | $0.005 | $0.0004 | Free | None |
| Intelligent-Tiering | $0.023 (Frequent) / $0.0125 (Infrequent) / $0.004 (Archive) | $0.005 | $0.0004 | Free | None |
| Standard-IA | $0.0125 | $0.01 | $0.001 | $0.01/GB | 30 days |
| One Zone-IA | $0.01 | $0.01 | $0.001 | $0.01/GB | 30 days |
| Glacier Instant | $0.004 | $0.02 | $0.01 | $0.03/GB | 90 days |
| Glacier Flexible | $0.0036 | $0.03 | $0.0004 | $0.01/GB (expedited: $0.03) | 90 days |
| Glacier Deep Archive | $0.00099 | $0.05 | $0.0004 | $0.02/GB | 180 days |

**Common waste patterns:**
1. **No lifecycle policies** — Data accumulates in Standard forever. Set rules: 30 days → IA, 90 days → Glacier, 365 days → Deep Archive
2. **Incomplete multipart uploads** — Abandoned uploads consume storage. Enable abort rule
3. **Old versioned objects** — Versioning keeps every version. Set lifecycle to expire non-current versions after 30 days
4. **Small files (< 128KB) in IA/Glacier** — Minimum object size charges apply. Small files cost MORE in IA than Standard
5. **LIST operations at scale** — $0.005 per 1,000 LIST requests. Millions of objects = significant cost
6. **S3 Select / Glacier Select** — $0.002/GB scanned + $0.0007/GB returned. Can save on transfer but adds compute cost

**Request cost gotcha:** A data pipeline doing millions of small PUTs per day:
- 10M PUTs/day × $0.005/1K = $50/day = $1,500/month just in PUT requests
- Fix: Batch small files, use larger objects, compress before upload

### S3 Express One Zone (new)
- Single-digit millisecond latency, 10x faster than Standard
- $0.16/GB/month (7x Standard) + $0.0025 per 1K PUT + $0.0002 per 1K GET
- Use for: Spark/EMR temporary shuffle storage, ML training data, analytics scratch space

---

## Database Services

### RDS (Relational Database Service)
**Pricing:** Instance hours + Storage + I/O (Aurora) + Backup + Data Transfer

| Engine | Instance (db.r6g.xlarge) | Multi-AZ | Storage (gp3) |
|--------|------------------------|----------|---------------|
| PostgreSQL | $0.462/hr | $0.924/hr (2x) | $0.115/GB/mo |
| MySQL | $0.462/hr | $0.924/hr | $0.115/GB/mo |
| Aurora PostgreSQL | $0.462/hr | $0.462/hr (reader replica) | $0.10/GB/mo + $0.20/1M I/O |
| Aurora Serverless v2 | $0.12/ACU-hour | Included | $0.10/GB/mo + $0.20/1M I/O |

**Common waste:**
1. **Multi-AZ for dev/staging** — 2x cost. Only production needs Multi-AZ
2. **Oversized RDS instances** — Check CloudWatch CPU/memory. Data teams often provision for peak, not average
3. **Aurora I/O costs** — Aurora's $0.20/1M I/O can dwarf instance cost for I/O-heavy workloads. Aurora I/O-Optimized eliminates I/O charges for 30% higher instance price — break-even at ~25% I/O spend
4. **Automated backups beyond retention** — Default 7-day retention is free. Manual snapshots persist forever at $0.095/GB/month
5. **Read replicas running unused** — Each replica = full instance cost

**Aurora Serverless v2:**
- Min 0.5 ACU, max 128 ACU. Scales in 0.5 ACU increments
- $0.12/ACU-hour = $0.06/hr at minimum (still running 24/7)
- Good for: variable workloads, dev environments
- Gotcha: minimum capacity is always charged, even at zero load

### DynamoDB
**Pricing models:**

| Mode | Write | Read | Storage |
|------|-------|------|---------|
| On-Demand | $1.25/1M WCU | $0.25/1M RCU | $0.25/GB/mo |
| Provisioned | $0.00065/WCU/hr | $0.00013/RCU/hr | $0.25/GB/mo |
| Reserved (1yr) | ~$0.000420/WCU/hr | ~$0.000084/RCU/hr | $0.25/GB/mo |

**Common waste:**
1. **Over-provisioned capacity** — Auto-scaling helps but has 5-15 min lag. On-Demand is simpler for spiky workloads
2. **Global tables** — Replicated write capacity costs per region. Don't replicate dev tables
3. **DynamoDB Streams** — $0.02/100K reads. High-volume tables can generate significant stream costs
4. **Point-in-time recovery (PITR)** — $0.20/GB/month. Worth it for production, unnecessary for temp tables

### ElastiCache
- Redis/Memcached managed service
- **Pricing:** Instance hours (same as EC2 equivalent) + backup storage
- **Common waste:** Oversized nodes, Multi-AZ in dev, reserved nodes expiring
- cache.r6g.xlarge: $0.361/hr on-demand, $0.228/hr reserved (1yr)

### OpenSearch (formerly Elasticsearch Service)
- **Pricing:** Instance hours + EBS storage + UltraWarm + Cold storage
- **Common waste:** Oversized domains, too many shards, no ISM (Index State Management) lifecycle policies
- Data teams use for: log analytics, search, observability
- UltraWarm: $0.024/GB/month (vs $0.135/GB for hot r6g instances + EBS) — use for logs >7 days old

---

## Analytics & Data Warehouse

### Redshift
**Pricing models:**

| Type | Node | On-Demand | Reserved (1yr) | Reserved (3yr) |
|------|------|-----------|----------------|----------------|
| RA3 | ra3.xlplus (4 vCPU, 32 GB) | $1.086/hr | $0.73/hr (33% off) | $0.475/hr (56% off) |
| RA3 | ra3.4xlarge (12 vCPU, 96 GB) | $3.26/hr | $2.18/hr | $1.424/hr |
| RA3 | ra3.16xlarge (48 vCPU, 384 GB) | $13.04/hr | $8.72/hr | $5.696/hr |
| Serverless | N/A | $0.375/RPU-hour | N/A | N/A |

**Managed storage:** $0.024/GB/month (RA3 nodes)

**Redshift Serverless:**
- Base capacity: 8-512 RPU (Redshift Processing Units)
- $0.375/RPU-hour, billed per second (1-min minimum)
- Scales up/down automatically
- Good for: variable workloads, ad-hoc queries
- Gotcha: can be expensive for sustained workloads — compare with reserved RA3

**Common waste:**
1. **Clusters running 24/7 for business-hours queries** — Pause non-prod clusters (saves 60-70%)
2. **Concurrency Scaling** — $0.375/RPU-hour. Set max concurrency scaling clusters = 1 unless needed
3. **Spectrum scans** — $5/TB scanned from S3. Partitioning and columnar format reduce scans
4. **COPY vs INSERT** — INSERT is 100x slower and more expensive. Always use COPY for bulk loads
5. **Sort keys not defined** — Zone maps can't skip blocks without sort keys. Full table scans on every query
6. **No vacuum/analyze** — Dead rows waste storage and slow queries

**Optimization:**
- Use RA3 for steady workloads with reserved pricing
- Use Serverless for sporadic/variable workloads
- Pause dev/staging clusters on schedule
- Define sort keys and dist keys properly
- Monitor WLM queues to right-size concurrency

### Athena
**Pricing:** $5/TB scanned (on-demand) or $0.0625/DPU-hour (provisioned capacity)

**Cost reduction:**
1. **Columnar format (Parquet/ORC)** — 3-5x compression vs CSV = 3-5x cheaper queries
2. **Partitioning** — Partition by date/region to avoid full scans
3. **CTAS (CREATE TABLE AS)** — Convert CSV → Parquet: one-time cost, permanent savings
4. **Workgroup budgets** — Set per-query and per-workgroup scan limits
5. **Athena Provisioned** — Predictable cost for high-volume workloads. 24 DPU = $36/hr

### EMR (Elastic MapReduce)
**Pricing:** EC2 instance cost + EMR premium (varies by instance family)

| Instance | EC2 On-Demand | EMR Premium | Total |
|----------|--------------|-------------|-------|
| m5.xlarge | $0.192/hr | $0.048/hr (25%) | $0.240/hr |
| r5.xlarge | $0.252/hr | $0.063/hr | $0.315/hr |
| i3.xlarge | $0.312/hr | $0.078/hr | $0.390/hr |

**EMR on EKS:** No EMR premium — just EC2/EKS costs. 30-50% cheaper for Spark.
**EMR Serverless:** $0.052624/vCPU-hour + $0.0057785/GB-hour. No cluster management.

**Common waste:**
1. **Long-running clusters for batch jobs** — Use transient clusters (spin up, run, terminate)
2. **Not using Spot for task nodes** — Core nodes: On-Demand. Task nodes: 100% Spot (60-90% savings)
3. **Oversized clusters** — Auto-scaling or right-sizing based on YARN metrics
4. **S3 storage instead of HDFS for temp data** — Spark shuffle to S3 is slow and expensive. Use local NVMe (i3/d3) or S3 Express

### AWS Glue
**Pricing:**

| Service | Price |
|---------|-------|
| Glue ETL (Spark) | $0.44/DPU-hour (1 DPU = 4 vCPU, 16 GB) |
| Glue ETL (Ray) | $0.44/DPU-hour |
| Glue Streaming | $0.44/DPU-hour (always running) |
| Data Catalog | Free (first 1M objects), then $1/100K objects/month |
| Crawlers | $0.44/DPU-hour |
| Data Quality | $1/1,000 rules evaluated |
| DataBrew | $1/node-hour (interactive sessions) |

**Common waste:**
1. **Max DPU allocation** — Default 10 DPU. Many jobs need 2-5. Test and right-size
2. **Glue crawlers running too often** — Hourly crawlers on static schemas. Set to daily or event-triggered
3. **Glue Streaming always-on** — Charged even when no data flowing. Consider Lambda or Kinesis for sparse streams
4. **No Glue Auto Scaling** — Enable Flex execution for non-urgent ETL (uses spare capacity, same price but slower start)
5. **Job bookmarks not used** — Without bookmarks, jobs reprocess all data every run

**Glue vs EMR vs Athena decision:**
- **Glue:** Managed Spark, pay per DPU-hour. Best for: ETL pipelines, simple transforms
- **EMR:** Self-managed Spark/Hive/Presto. Best for: complex pipelines, cost-sensitive teams
- **Athena:** Serverless SQL. Best for: ad-hoc queries, infrequent analysis

---

## Data Transfer (The Hidden Cost Center)

### Transfer Pricing Matrix

| Route | Cost |
|-------|------|
| Inbound (internet → AWS) | Free |
| Same AZ, same VPC | Free |
| Same AZ, different VPC (peering) | Free |
| **Cross-AZ (same region)** | **$0.01/GB each direction** |
| Cross-region (within US) | $0.02/GB |
| Cross-region (US → Europe) | $0.02/GB |
| Internet egress (first 10TB/mo) | $0.09/GB |
| Internet egress (next 40TB/mo) | $0.085/GB |
| Internet egress (next 100TB/mo) | $0.07/GB |
| Internet egress (>150TB/mo) | $0.05/GB |
| CloudFront to internet | $0.085/GB (cheaper than direct) |

### NAT Gateway — The Silent Bill Killer
- **Processing:** $0.045/GB processed (BOTH directions)
- **Hourly:** $0.045/hr ($32.40/month per gateway)
- A data pipeline pulling 10TB/month through NAT: $450/month just in NAT processing
- **Fix:** Use VPC endpoints for S3 ($0.01/GB via Gateway endpoint = FREE) and DynamoDB (free)
- **Fix:** Use S3 Gateway Endpoint (free, no per-GB charge) instead of NAT for S3 traffic
- **Fix:** Use Interface VPC Endpoints ($0.01/hr + $0.01/GB) for other AWS services

### PrivateLink / Interface VPC Endpoints
- $0.01/hr per AZ ($7.20/month per endpoint per AZ)
- $0.01/GB processed
- For services like SQS, Kinesis, STS — cheaper than NAT at scale

### Cross-AZ Cost Gotchas for Data Teams
Data-intensive architectures hit cross-AZ costs hard:
- **Kafka/MSK cluster** — Replication factor 3 across 3 AZs: every message crosses AZ twice = $0.02/GB
- **EMR/Spark** — Shuffle between executors in different AZs: $0.01/GB each way
- **Multi-AZ RDS** — Synchronous replication: all writes cross AZ
- **EBS Multi-Attach** — io2 volumes shared across AZs: transfer costs per I/O

**Estimation formula:** Monthly cross-AZ cost = (daily_data_volume_GB × replication_factor × 2 × $0.01 × 30)

---

## Streaming & Messaging

### Kinesis
| Service | Pricing |
|---------|---------|
| Data Streams (on-demand) | $0.04/GB ingested + $0.04/GB retrieved (+ fan-out: $0.013/GB per consumer) |
| Data Streams (provisioned) | $0.015/shard/hr + $0.014/1M PUT |
| Data Firehose | $0.029/GB (first 500TB) |
| Data Analytics (Apache Flink) | $0.11/KPU-hour |

**Common waste:**
1. **Over-provisioned shards** — Each shard = $0.015/hr ($10.80/month). Scale down during off-hours
2. **Enhanced fan-out not needed** — Standard consumers (200ms latency) are free vs $0.013/GB for enhanced
3. **Firehose buffer size too small** — Smaller buffers = more S3 PUTs = more S3 request costs. Set buffer to 128MB/300s
4. **Kinesis Data Analytics always running** — Minimum 1 KPU ($0.11/hr = $79.20/month). Consider Lambda for low-volume

### MSK (Managed Streaming for Apache Kafka)
| Instance | On-Demand | Reserved (1yr) |
|----------|-----------|----------------|
| kafka.m5.large | $0.21/hr | $0.142/hr |
| kafka.m5.xlarge | $0.42/hr | $0.284/hr |
| kafka.m7g.xlarge | $0.336/hr (Graviton) | $0.228/hr |

+ Storage: $0.10/GB/month
+ MSK Serverless: $0.01/GB in + $0.006/partition-hour

**Common waste:**
1. **3-broker minimum even for dev** — MSK Serverless for dev, provisioned for prod
2. **High retention periods** — 7-day default. Archive to S3 via Firehose for long-term
3. **Under-utilized brokers** — Right-size based on bytes in/out metrics

### SQS (Simple Queue Service)
- Standard: $0.40/1M requests (first 1M free/month)
- FIFO: $0.50/1M requests
- Long polling: fewer requests = lower cost
- **Gotcha:** Each 64KB chunk = 1 request. A 256KB message = 4 requests

### SNS (Simple Notification Service)
- Publish: $0.50/1M requests
- Email: $2/100K notifications
- SMS: $0.00645/message (US)
- HTTP/SQS/Lambda delivery: free
- **Gotcha:** Fan-out to SQS: SNS publish cost + SQS receive cost

---

## AI/ML Services

### SageMaker
| Component | Pricing |
|-----------|---------|
| Notebook instances | Same as equivalent EC2 (e.g., ml.t3.medium = $0.05/hr) |
| Training (ml.p3.2xlarge) | $3.825/hr |
| Training (ml.p4d.24xlarge) | $37.688/hr |
| Training (ml.g5.xlarge) | $1.408/hr |
| Inference (ml.m5.xlarge) | $0.23/hr |
| Inference (Serverless) | $0.0001/ms per 1MB memory |
| Processing | Same as training instance pricing |
| Feature Store | $0.06/GB/month (offline) + $0.045/read/write per 1M units (online) |
| Model Registry | Free |

**Common waste:**
1. **Notebook instances left running** — Auto-stop lifecycle config (idle detection)
2. **Training without Spot** — Managed Spot Training: 60-90% off, with checkpointing for interruptions
3. **Endpoints for batch workloads** — Use Batch Transform instead of real-time endpoints for batch scoring
4. **Single-instance endpoints** — Use Inference Recommender to right-size, multi-model endpoints to share instances
5. **Studio domains** — EFS storage grows silently at $0.30/GB/month

**SageMaker Savings Plans:** 1-year commitment, 64% savings on ml instances (training + inference + notebooks)

### Bedrock
| Model | Input (per 1K tokens) | Output (per 1K tokens) |
|-------|----------------------|----------------------|
| Claude 3.5 Sonnet | $0.003 | $0.015 |
| Claude 3 Haiku | $0.00025 | $0.00125 |
| Llama 3.1 70B | $0.00099 | $0.00099 |
| Titan Text Express | $0.0008 | $0.0016 |
| Stable Diffusion XL | $0.04-0.08/image | N/A |

+ **Provisioned Throughput:** 1-6 month commitment, no per-token charges, guaranteed capacity
+ **Knowledge Bases:** $0.35/GB/month (vector store) + model costs for retrieval
+ **Agents:** Model costs + Lambda invocation costs

**Gotcha:** Bedrock adds markup over direct API pricing. Claude Sonnet via Bedrock costs more than via Anthropic API directly.

---

## Orchestration & CI/CD

### Step Functions
| Type | Price |
|------|-------|
| Standard | $0.025/1K state transitions |
| Express (sync) | $0.000001/100ms per 64MB memory |
| Express (async) | Same as sync |

**Common waste:**
1. **Standard for high-volume short workflows** — Express is 50-90% cheaper for <5 min workflows
2. **Polling loops** — Wait states with retry loops generate thousands of transitions. Use callbacks instead
3. **Map state parallelism** — Each parallel branch = state transitions. Batch items to reduce transitions

### MWAA (Managed Airflow)
| Environment Size | Price |
|-----------------|-------|
| mw1.small (1 worker, 1 scheduler) | $0.49/hr ($353/month) |
| mw1.medium | $0.79/hr ($569/month) |
| mw1.large | $1.58/hr ($1,138/month) |

+ Worker auto-scaling: $0.055/worker-hour (small) to $0.220/worker-hour (large)
+ Metadata DB and scheduler always running = minimum cost even with zero DAGs

**Common waste:**
1. **mw1.large for simple DAGs** — Most data teams can use mw1.small or mw1.medium
2. **Max workers too high** — Auto-scaling overshoots. Set max_workers = 2-5x your avg parallelism
3. **Over-scheduled DAGs** — Minutely schedules on complex DAGs. Most ETL is hourly or daily

**Alternative:** Self-hosted Airflow on ECS/EKS can be 60-80% cheaper but requires ops overhead

### CodeBuild
| Compute Type | Price (Linux) |
|-------------|---------------|
| build.general1.small (3 GB, 2 vCPU) | $0.005/min |
| build.general1.medium (7 GB, 4 vCPU) | $0.01/min |
| build.general1.large (15 GB, 8 vCPU) | $0.02/min |
| build.general1.xlarge (72 GB, 36 vCPU) | $0.04/min |
| ARM (build.general1.small) | $0.00325/min (35% less) |

**Common waste:**
1. **Oversized build instances** — Most builds don't need 8 vCPU. Start with small/medium
2. **No caching** — S3 cache or local cache can cut build times 30-60%
3. **Windows builds** — 2x the cost of Linux. Use Linux where possible

### CodePipeline
- $1/active pipeline/month (first pipeline free)
- Action executions: $0.01/action execution (V2 pipelines)
- Cheap, but each stage/action adds up in complex pipelines

---

## Networking

### CloudFront (CDN)
- $0.085/GB (US/Europe, first 10TB) — cheaper than direct S3 egress ($0.09/GB)
- $0.01/10K HTTPS requests
- **Free tier:** 1TB/month + 10M requests
- **Origin Shield:** $0.0090/10K requests — reduces origin fetches
- Lambda@Edge: $0.60/1M requests + $0.00005001/128MB-second

### Route 53
- $0.50/hosted zone/month
- $0.40/1M standard queries
- $0.60/1M latency/geo queries
- Health checks: $0.50/endpoint/month (AWS) or $0.75 (non-AWS)

### VPC
- VPC itself: free
- NAT Gateway: $0.045/hr + $0.045/GB (see Data Transfer section)
- VPN Connection: $0.05/hr per connection ($36/month)
- Transit Gateway: $0.05/hr + $0.02/GB
- VPC Peering: free (but cross-AZ transfer costs apply)

### AWS PrivateLink
- $0.01/hr per AZ per endpoint ($7.20/month per AZ)
- $0.01/GB processed
- Cheaper than NAT Gateway for AWS service access at scale

---

## Monitoring & Observability

### CloudWatch
| Feature | Price |
|---------|-------|
| Basic metrics | Free (5-min resolution, 10 per service) |
| Detailed metrics (1-min) | $0.30/metric/month |
| Custom metrics | $0.30/metric/month (first 10K), $0.10 (next 240K) |
| Dashboards | $3/dashboard/month |
| Alarms | $0.10/standard alarm, $0.30/high-res alarm |
| **Log ingestion** | **$0.50/GB** |
| Log storage | $0.03/GB/month |
| Log Insights queries | $0.005/GB scanned |
| Contributor Insights | $0.02/rule/month + $0.00000002/matching log event |

**Log ingestion is the #1 CloudWatch cost surprise for data teams:**
- A busy Spark/Airflow cluster logging at 1GB/hour = 720GB/month = $360/month just for ingestion
- Lambda functions logging request/response bodies can generate massive log volume
- **Fix:** Set log levels to WARN in production, use structured logging, set retention periods (default is NEVER expire)
- **Fix:** Use CloudWatch Logs subscription filters to S3 for long-term storage ($0.023/GB vs $0.03/GB)

### X-Ray
- $5/1M traces recorded
- $0.50/1M traces retrieved
- Free tier: 100K traces/month

### CloudTrail
- Management events: First trail free, $2/100K events for additional trails
- Data events (S3, Lambda): $0.10/100K events — can be extremely expensive at scale
- CloudTrail Lake: $2.50/GB ingested + $0.005/GB scanned

**CloudTrail Data Events gotcha:** Enabling S3 data events on a high-traffic bucket:
- 100M GET/PUT events/month × $0.10/100K = $100/month per bucket
- Only enable for compliance-critical buckets

---

## Data Integration

### DMS (Database Migration Service)
| Instance | On-Demand |
|----------|-----------|
| dms.t3.medium | $0.078/hr |
| dms.r5.large | $0.233/hr |
| dms.r5.xlarge | $0.466/hr |

+ Storage: $0.115/GB/month (gp2)
+ Serverless: $0.018/capacity unit/hr (auto-scales)
+ **Data transfer:** Free for replication into AWS. Standard rates for cross-region

**Common waste:**
1. **Oversized replication instances** — Start with dms.t3.medium, scale up only if replication lags
2. **Full load repeated instead of CDC** — CDC (Change Data Capture) only transfers deltas
3. **DMS instances running after migration complete** — Delete replication instances when done

### AWS Transfer Family (SFTP/FTPS/FTP)
- $0.30/protocol/hour ($216/month per endpoint) — expensive for low-volume transfers
- $0.04/GB transferred
- **Alternative:** S3 pre-signed URLs or direct S3 API for modern integrations

### EventBridge
- Custom events: $1/1M events
- Schema Registry: free
- Pipes: $0.40/1M invocations + $0.096/GB processed
- Scheduler: $1/1M invocations (first 14M free)

---

## Security & Governance

### AWS IAM Identity Center (SSO)
- Free for IAM Identity Center
- Per-user MFA: Free (built-in)

### AWS Organizations
- Free — no charge for consolidated billing or service control policies

### AWS Config
- $0.003/config item recorded
- $0.001/config rule evaluation
- **Gotcha:** With 500+ resources and 20 rules, monthly cost can reach $50-100+
- **Fix:** Only enable rules you actively monitor. Use conformance packs selectively

### GuardDuty
- $4/GB/month for CloudTrail events (first 500MB free)
- $1/GB/month for VPC Flow Logs and DNS logs
- **Gotcha:** High-traffic environments can see $100+/month

### Security Hub
- $0.0010/finding ingested (first 10K free)
- Standards checks: $0.0010/check/account/region
- Can add up in multi-account, multi-region setups

### Secrets Manager
- $0.40/secret/month + $0.05/10K API calls
- **vs SSM Parameter Store:** Free tier covers most use cases (standard params free, advanced $0.05/param/month)

### KMS (Key Management Service)
- $1/key/month for customer-managed keys
- $0.03/10K requests
- AWS-managed keys: free
- Symmetric keys: most cost-effective. Asymmetric keys: $1/key + $0.15/10K sign/verify operations

---

## Cost Management Tools (AWS Native)

### Cost Explorer
- Free for basic use
- API calls: $0.01/paginated request
- Hourly granularity: available but only for last 14 days
- Rightsizing recommendations: free
- Savings Plans recommendations: free

### Cost and Usage Report (CUR)
- Free to generate — delivered to S3
- The most granular billing data available (line-item, hourly, resource-level)
- ~1-10 GB/month for large accounts
- Query with Athena for custom cost analysis

### AWS Budgets
- First 2 budgets: free
- Additional: $0.02/budget/day ($0.62/budget/month)
- Budget actions can auto-stop resources when thresholds hit

### AWS Compute Optimizer
- Free for EC2, EBS, Lambda recommendations
- Enhanced (paid): $0.0003253/resource/month — adds memory metrics, 3-month lookback

### Trusted Advisor
- Basic checks: free (all accounts)
- Full checks: Business/Enterprise Support required ($100+/month minimum)
- Cost optimization checks: idle instances, underutilized EBS, unassociated EIPs

---

## Common Cost Problems & Solutions

### 1. "Our AWS bill went up 40% but nothing changed"
**Investigation checklist:**
1. Check Cost Explorer by service — which service spiked?
2. Check data transfer costs — often hidden in "EC2-Other"
3. Check NAT Gateway processing — GB processed metric in VPC console
4. Check CloudWatch log ingestion — someone turned on debug logging?
5. Check S3 request costs — new data pipeline doing millions of small PUTs?
6. Check for new services — someone launched a resource and forgot?
7. Check Reserved Instance/Savings Plan expiry — back to on-demand pricing

### 2. "We can't track costs by team/project/environment"
**Solution: Cost Allocation Tags**
1. Define mandatory tags: `Team`, `Environment`, `Project`, `CostCenter`
2. Enable in Billing Console → Cost Allocation Tags → Activate
3. Enforce with AWS Organizations SCP or Service Catalog
4. Use AWS Tag Editor to bulk-tag existing resources
5. **Untaggable resources:** Data transfer, support charges, some marketplace — allocate via CUR analysis
6. **Gotcha:** Tag changes take 24 hours to appear in billing data

### 3. "Reserved Instances are expiring and nobody noticed"
**Solution:**
1. Cost Explorer → RI Utilization report → set coverage target (80%+)
2. AWS Budgets → RI coverage budget with SNS alert at 80%
3. Review RI purchases quarterly — workloads change, RIs don't
4. Consider Savings Plans instead — more flexible, auto-apply to similar workloads

### 4. "Our data transfer costs are out of control"
**Investigation:**
1. CUR report filtered to DataTransfer usage types
2. VPC Flow Logs → analyze cross-AZ traffic patterns
3. Check for: NAT Gateway overuse, missing VPC endpoints, cross-region replication
4. **Quick wins:** S3 Gateway Endpoint (free), consolidate to single AZ for dev, CloudFront for egress

### 5. "Spot interruptions are breaking our pipelines"
**Solutions:**
1. Diversify instance types — use 10+ instance types in Spot Fleet
2. Use Spot placement score API to find best AZ
3. Checkpointing in Spark/EMR — resume from last checkpoint
4. Mix On-Demand (core) + Spot (task) nodes in EMR
5. Use Spot with EMR managed scaling — automatic fallback to On-Demand

### 6. "Our SageMaker/ML training costs are unpredictable"
**Solutions:**
1. SageMaker Managed Spot Training — 60-90% savings with checkpointing
2. SageMaker Savings Plans for steady training workloads
3. Use SageMaker Debugger to detect vanishing gradients early (stop wasting GPU hours)
4. Right-size: Use Inference Recommender before deploying endpoints
5. Multi-model endpoints: share instance across models
6. Serverless inference for low-traffic models (cold start trade-off)

---

## Optimization Checklist (by Impact)

### Tier 1: High Impact (typically 20-40% savings)
1. **Reserved Instances / Savings Plans** for steady-state compute (EC2, RDS, Redshift, ElastiCache)
2. **Spot Instances** for fault-tolerant workloads (Spark executors, batch training, CI/CD)
3. **Graviton (ARM) migration** — 15-20% cheaper, often faster for data workloads
4. **Right-sizing** — Use Compute Optimizer. Most instances are 2-4x oversized
5. **S3 lifecycle policies** — Move cold data to IA/Glacier automatically

### Tier 2: Medium Impact (typically 10-20% savings)
6. **VPC endpoints for S3** — Eliminate NAT Gateway data processing charges
7. **Stop/pause non-production resources** — Dev/staging off at night and weekends
8. **gp2 → gp3 EBS migration** — 20% cheaper, better baseline performance
9. **CloudWatch log optimization** — Set retention, reduce log verbosity, filter before ingestion
10. **Consolidate Availability Zones** — For non-HA workloads, single AZ eliminates cross-AZ costs

### Tier 3: Lower Impact but Easy Wins
11. **Delete unattached EBS volumes and old snapshots**
12. **Remove unused Elastic IPs** (now charged for ALL public IPv4)
13. **Review and clean up old AMIs** — Each AMI = snapshot storage costs
14. **Set S3 incomplete multipart upload cleanup**
15. **Tag everything** — Can't optimize what you can't measure

---

## SQL/CLI Commands for Investigation

### Cost Explorer CLI
```bash
# Get daily costs by service for last 30 days
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity DAILY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

# Get costs by linked account
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=LINKED_ACCOUNT

# Get Savings Plans utilization
aws ce get-savings-plans-utilization \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity MONTHLY

# Get RI coverage
aws ce get-reservation-coverage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --group-by Type=DIMENSION,Key=SERVICE
```

### Resource Investigation
```bash
# Find unattached EBS volumes
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].{ID:VolumeId,Size:Size,Created:CreateTime}'

# Find unattached Elastic IPs
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].{IP:PublicIp,AllocId:AllocationId}'

# Find old snapshots (>90 days)
aws ec2 describe-snapshots --owner-ids self \
  --query 'Snapshots[?StartTime<`2024-01-01`].{ID:SnapshotId,Size:VolumeSize,Date:StartTime}'

# Check NAT Gateway data processed
aws cloudwatch get-metric-statistics \
  --namespace AWS/NATGateway \
  --metric-name BytesOutToDestination \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-31T00:00:00Z \
  --period 86400 --statistics Sum
```

---

## AWS Pricing API
```python
# Programmatic pricing lookup
import boto3
pricing = boto3.client('pricing', region_name='us-east-1')

# Get EC2 on-demand pricing
response = pricing.get_products(
    ServiceCode='AmazonEC2',
    Filters=[
        {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': 'm6i.xlarge'},
        {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': 'US East (N. Virginia)'},
        {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
        {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
        {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'},
    ]
)
```

## Key Billing Dates & Rules
- Bills finalize 3-5 days after month end
- Credits apply in order: RI/SP → EDP → AWS credits → free tier
- Tax calculated on post-discount amount
- Support costs: percentage of monthly AWS bill (Developer 3%, Business 10%+, Enterprise 7%+)
- Data transfer aggregated across all services before tiering kicks in

## Waste Detection Rules (from steampipe-mod-aws-thrifty)

### Industry-Standard Thresholds
These thresholds are used by the open-source aws-thrifty project and represent consensus defaults:

| Resource | Metric | Alarm | Warning |
|----------|--------|-------|---------|
| EC2 CPU | 30-day avg utilization | <20% (downsize) | <35% (investigate) |
| RDS CPU | 30-day avg utilization | <25% (downsize) | <50% (investigate) |
| RDS Connections | 30-day avg daily connections | 0 (unused) | <2 (barely used) |
| EBS I/O | 30-day avg read+write ops | <100 (unused) | <500 (underused) |
| Instance Age | Running time | >90 days (review RI/SP) | >30 days |
| EBS Snapshots | Age | >90 days (consider delete) | — |
| S3 Buckets | Lifecycle policy | None = alarm | — |
| Elastic IPs | Attachment status | Unattached = alarm | — |

### EBS Volume Type Migration (Easy Wins)
| Current | Migrate To | Why |
|---------|-----------|-----|
| gp2 | gp3 | gp3 is 20% cheaper with same baseline IOPS (3,000) and higher throughput (125 MB/s vs 128 MB/s). No downside. |
| io1 | io2 | Same price, but io2 offers 99.999% durability (vs 99.9%). No downside. |
| io1/io2 with ≤16,000 IOPS | gp3 | gp3 supports up to 16,000 IOPS. If you're under that, gp3 is significantly cheaper. |

### Rightsizing Formula (from OptScale)
```
recommended_cpu = ceil(current_cpu / 80 * observed_q99_cpu_utilization)
projected_cpu_after_resize = min(current_avg_cpu * current_cpu / target_cpu, 100)
monthly_saving = (current_hourly_price - recommended_hourly_price) * 720
```
Default metric: 99th percentile CPU over 30 days, with 80% utilization limit.

### S3 Cost Gotchas (from Vantage Handbook)

**Small object penalty in IA/Glacier:**
- Standard-IA and One Zone-IA charge minimum 128KB per object
- Glacier classes add 32KB overhead at Glacier rate + 8KB at Standard rate per object
- Storing millions of <128KB files in IA costs MORE than Standard class

**Hidden S3 costs most teams miss:**
1. **Request metrics** — GET/PUT/LIST/COPY all charged per-request. LIST operations on large buckets can spike costs
2. **Bandwidth egress** — Where runaway costs happen. Use CloudFront or Cloudflare Bandwidth Alliance for heavy egress
3. **S3 doesn't expose request metrics by default** — Enable via `aws s3api put-bucket-metrics-configuration`

### Savings Plans vs Reserved Instances Decision Tree
```
Is the service EC2, Lambda, Fargate, or SageMaker?
  YES → Use Savings Plans (more flexible, same discount)
  NO  → Is it RDS, ElastiCache, Redshift, or OpenSearch?
    YES → Use Reserved Instances (only option)
    NO  → On-Demand or Spot (if fault-tolerant)
```

**Key rule:** Savings Plans are ALWAYS preferred over RIs for compute services. RIs only for services not covered by Savings Plans.

### CloudWatch Cost Trap
- CloudWatch is used automatically by OTHER AWS services — you plan for EC2 costs but get surprise CloudWatch charges
- **Log Groups retain logs INDEFINITELY by default** — the #1 CloudWatch cost trap
- Fix: Set explicit retention periods (1 day to 10 years) on every Log Group
- Progressive metric pricing: first 10K metrics = $0.30/metric/mo, next 240K = $0.10/metric/mo

### NAT Gateway Optimization
NAT Gateways triple-charge: hourly fee + per-GB processing + standard bandwidth charges.
**Fix:** Use VPC Endpoints for AWS service traffic (S3, DynamoDB, etc.) — eliminates both NAT hourly and per-GB charges.

### EC2-Other (Mystery Cost Category)
This catch-all includes: EBS volumes, EBS snapshots, T2/T3/T4g CPU credits (Unlimited mode), NAT Gateway, data transfer, idle Elastic IPs. If this line item spikes, check for stranded resources.

### Anomaly Detection Formula (from OptScale)
```
if today_cost > avg_cost_over_N_days * (1 + threshold_pct / 100):
    trigger_alert(severity='high')
```
Default: N=7 days, threshold=30%. Simple but effective moving average with percentage spike detection.
