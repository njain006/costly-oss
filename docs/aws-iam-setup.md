# AWS IAM Setup for Costly

Costly needs a dedicated IAM user with **read-only** access to Cost Explorer and resource inventory APIs.

## Quick Setup

```bash
# 1. Create the IAM user
aws iam create-user --user-name costly-reader

# 2. Attach the cost explorer policy
aws iam put-user-policy --user-name costly-reader \
  --policy-name CostExplorerReadOnly \
  --policy-document file://docs/aws-cost-explorer-policy.json

# 3. Attach the resource inventory policy
aws iam put-user-policy --user-name costly-reader \
  --policy-name ResourceInventoryReadOnly \
  --policy-document file://docs/aws-inventory-policy.json

# 4. Create access keys
aws iam create-access-key --user-name costly-reader
```

Use the Access Key ID, Secret Access Key, and region in the Costly Platforms > AWS connection form.

## Required Permissions

### Cost Explorer (required)

Enables cost tracking across all AWS services.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ce:GetCostForecast",
        "ce:GetDimensionValues",
        "ce:GetTags"
      ],
      "Resource": "*"
    }
  ]
}
```

### Resource Inventory (recommended)

Enables listing S3 buckets, EC2 instances, Lambda functions, and bucket-level metrics (size, object count).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "s3:GetBucketTagging",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "rds:DescribeDBInstances",
        "lambda:ListFunctions",
        "ecs:ListClusters",
        "eks:ListClusters",
        "redshift:DescribeClusters",
        "glue:GetDatabases",
        "dynamodb:ListTables",
        "sqs:ListQueues",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

## What Each Permission Does

| Permission | Purpose |
|-----------|---------|
| `ce:GetCostAndUsage` | Daily cost breakdown by service |
| `ce:GetCostForecast` | Projected spend |
| `ce:GetDimensionValues` | List available services/regions |
| `ce:GetTags` | Cost allocation tags |
| `s3:ListAllMyBuckets` | List all S3 buckets |
| `s3:GetBucketLocation` | Bucket region |
| `cloudwatch:GetMetricStatistics` | S3 bucket size and object count |
| `ec2:DescribeInstances` | List EC2 instances with type/state |
| `lambda:ListFunctions` | List Lambda functions with runtime/memory |
| `rds:DescribeDBInstances` | List RDS databases |

## Security Notes

- All permissions are **read-only** — Costly cannot modify, create, or delete any AWS resources
- Credentials are encrypted at rest using Fernet symmetric encryption in the Costly database
- The IAM user has no console access
- Consider using [IAM Access Analyzer](https://docs.aws.amazon.com/IAM/latest/UserGuide/what-is-access-analyzer.html) to audit the permissions
