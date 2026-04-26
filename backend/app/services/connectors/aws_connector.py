"""AWS Cost Explorer connector.

Pulls costs for ALL AWS services and inventories resources
(S3 buckets, EC2 instances, Lambda functions, etc.).

Extended capabilities (2026-04):
- ``cost_type`` toggle — fetch either ``UnblendedCost`` (default, cash outlay)
  or ``AmortizedCost`` (Savings Plan / Reserved Instance reality). When
  ``AmortizedCost`` is requested we also pull ``UnblendedCost`` so downstream
  consumers can surface the RI/SP savings delta.
- ``cost_allocation_tag_keys`` — comma-separated list of user-defined cost
  allocation tag keys. When set, each service row is enriched with a
  ``tag_breakdown`` metadata map so the chat agent and UI can slice by
  tag (team / project / environment).
- Multi-account via STS AssumeRole — when ``member_account_role_arns`` is
  supplied, the connector iterates each role, assumes it, and emits
  per-account ``UnifiedCost`` rows. Each row carries ``account_id`` and
  ``account_name`` metadata so the ``by_account`` aggregation in the
  unified-cost pipeline has a real dimension to group on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import boto3

from app.models.platform import UnifiedCost, CostCategory
from app.services.connectors.base import BaseConnector

# Map AWS service names to our cost categories
SERVICE_CATEGORY_MAP = {
    # Storage
    "Amazon Simple Storage Service": CostCategory.storage,
    "Amazon DynamoDB": CostCategory.storage,
    # Compute / Warehouses
    "Amazon Redshift": CostCategory.compute,
    "Amazon Athena": CostCategory.compute,
    "Amazon EMR": CostCategory.compute,
    "AWS Lambda": CostCategory.compute,
    "Amazon Elastic Container Service": CostCategory.compute,
    "Amazon Elastic Kubernetes Service": CostCategory.compute,
    "Amazon Elastic Compute Cloud - Compute": CostCategory.compute,
    "EC2 - Other": CostCategory.compute,
    # Orchestration
    "Amazon Managed Workflows for Apache Airflow": CostCategory.orchestration,
    "AWS Step Functions": CostCategory.orchestration,
    "Amazon CloudWatch": CostCategory.orchestration,
    # Transformation
    "AWS Glue": CostCategory.transformation,
    # Ingestion
    "Amazon Kinesis": CostCategory.ingestion,
    "AWS Database Migration Service": CostCategory.ingestion,
    # Networking / Messaging
    "Amazon Simple Queue Service": CostCategory.networking,
    "Amazon Managed Streaming for Apache Kafka": CostCategory.networking,
    "AWS Data Transfer": CostCategory.networking,
    # AI / ML
    "Amazon Bedrock": CostCategory.ai_inference,
    "Amazon SageMaker": CostCategory.ml_training,
    # BI
    "Amazon QuickSight": CostCategory.serving,
    # Database
    "Amazon Relational Database Service": CostCategory.storage,
    # Other
    "Amazon Registrar": CostCategory.networking,
    "Amazon Route 53": CostCategory.networking,
}

# Short display names for services
SERVICE_DISPLAY_NAMES = {
    "Amazon Simple Storage Service": "S3",
    "Amazon Elastic Compute Cloud - Compute": "EC2",
    "EC2 - Other": "EC2 Other",
    "AWS Lambda": "Lambda",
    "Amazon DynamoDB": "DynamoDB",
    "Amazon Redshift": "Redshift",
    "AWS Glue": "Glue",
    "Amazon Athena": "Athena",
    "Amazon Relational Database Service": "RDS",
    "Amazon Elastic Container Service": "ECS",
    "Amazon Elastic Kubernetes Service": "EKS",
    "Amazon CloudWatch": "CloudWatch",
    "Amazon Simple Queue Service": "SQS",
    "Amazon Kinesis": "Kinesis",
    "Amazon Bedrock": "Bedrock",
    "Amazon SageMaker": "SageMaker",
    "Amazon Managed Workflows for Apache Airflow": "MWAA",
    "AWS Step Functions": "Step Functions",
    "Amazon Managed Streaming for Apache Kafka": "MSK",
    "AWS Database Migration Service": "DMS",
    "Amazon QuickSight": "QuickSight",
    "AWS Data Transfer": "Data Transfer",
    "Amazon Registrar": "Registrar",
    "Amazon Route 53": "Route 53",
    "Amazon EMR": "EMR",
}

# Supported Cost Explorer metrics. UnblendedCost (default) is cash outlay;
# AmortizedCost folds Reserved Instance / Savings Plan prepayments back onto
# the usage hours, which is the number FinOps teams actually want.
VALID_COST_TYPES = (
    "UnblendedCost",
    "AmortizedCost",
    "BlendedCost",
    "NetUnblendedCost",
    "NetAmortizedCost",
)
DEFAULT_COST_TYPE = "UnblendedCost"


def _parse_tag_keys(raw) -> list[str]:
    """Normalise the ``cost_allocation_tag_keys`` credential.

    Accepts a comma-separated string or a list. Empty/whitespace-only inputs
    produce an empty list so the tag-grouping code path is skipped.
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(k).strip() for k in raw if str(k).strip()]
    return [k.strip() for k in str(raw).split(",") if k.strip()]


def _parse_role_arns(raw) -> list[str]:
    """Normalise ``member_account_role_arns`` into a list of ARNs."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(a).strip() for a in raw if str(a).strip()]
    return [a.strip() for a in str(raw).split(",") if a.strip()]


class AWSConnector(BaseConnector):
    platform = "aws"

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        self.region = credentials.get("region", "us-east-1")

        # Cost metric toggle (UnblendedCost | AmortizedCost | ...)
        cost_type = credentials.get("cost_type") or DEFAULT_COST_TYPE
        if cost_type not in VALID_COST_TYPES:
            raise ValueError(
                f"Invalid cost_type '{cost_type}'. Must be one of {VALID_COST_TYPES}"
            )
        self.cost_type: str = cost_type

        # Optional user-defined cost allocation tags (team, project, env...).
        # Tags must be activated in AWS Billing → Cost allocation tags first.
        self.tag_keys: list[str] = _parse_tag_keys(
            credentials.get("cost_allocation_tag_keys")
        )

        # Optional list of member-account role ARNs we can STS AssumeRole into
        # to emit per-account cost rows. Used by multi-account orgs where the
        # payer holds credentials and trusts member accounts via IAM.
        self.member_role_arns: list[str] = _parse_role_arns(
            credentials.get("member_account_role_arns")
        )
        self.external_id: str | None = credentials.get("external_id") or None

        self.client = boto3.client(
            "ce",
            aws_access_key_id=credentials["aws_access_key_id"],
            aws_secret_access_key=credentials["aws_secret_access_key"],
            region_name=self.region,
        )
        self._session = boto3.Session(
            aws_access_key_id=credentials["aws_access_key_id"],
            aws_secret_access_key=credentials["aws_secret_access_key"],
            region_name=self.region,
        )
        sts = boto3.client(
            "sts",
            aws_access_key_id=credentials["aws_access_key_id"],
            aws_secret_access_key=credentials["aws_secret_access_key"],
            region_name=self.region,
        )
        self.account_id: str = sts.get_caller_identity()["Account"]
        self._sts = sts  # retained for assume-role calls

    # ─── Public API ─────────────────────────────────────────────────

    def test_connection(self) -> dict:
        try:
            end = datetime.utcnow().strftime("%Y-%m-%d")
            start = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            self.client.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="DAILY",
                Metrics=[self.cost_type],
            )
            return {"success": True, "message": "AWS Cost Explorer connection successful"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e)}

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        costs = self._fetch_cost_data(
            days, self.client, self.account_id, account_name=None
        )
        # Multi-account fan-out via STS AssumeRole
        for role_arn in self.member_role_arns:
            try:
                member_ce, member_account_id, member_name = self._assume_role_ce_client(role_arn)
            except Exception:
                # If assume-role fails we skip the member and continue
                continue
            costs.extend(
                self._fetch_cost_data(
                    days, member_ce, member_account_id, account_name=member_name
                )
            )
        inventory = self._fetch_inventory()
        costs.extend(inventory)
        return costs

    # ─── Multi-account helpers ─────────────────────────────────────

    def _assume_role_ce_client(self, role_arn: str):
        """Assume a member-account role and return (ce_client, account_id, name).

        ``name`` is a human-readable fragment parsed from the ARN (the role
        name). The unified-cost pipeline will still overwrite ``account_name``
        with the connection's display name when it writes to MongoDB — this
        value is only used when the pipeline wasn't involved.
        """
        assume_kwargs = {
            "RoleArn": role_arn,
            "RoleSessionName": "costly-aws-multi-account",
        }
        if self.external_id:
            assume_kwargs["ExternalId"] = self.external_id
        resp = self._sts.assume_role(**assume_kwargs)
        creds = resp["Credentials"]
        ce = boto3.client(
            "ce",
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=self.region,
        )
        # arn:aws:iam::123456789012:role/CostlyReadOnly
        try:
            account_id = role_arn.split(":")[4]
        except Exception:
            account_id = ""
        role_name = role_arn.rsplit("/", 1)[-1] if "/" in role_arn else role_arn
        return ce, account_id, role_name

    # ─── Cost Explorer plumbing ────────────────────────────────────

    def _ce_metrics(self) -> list[str]:
        """Metrics to request from Cost Explorer.

        We always request UsageQuantity. When the user opted into AmortizedCost
        we also pull UnblendedCost so the savings delta is visible downstream.
        """
        metrics = [self.cost_type, "UsageQuantity"]
        if self.cost_type == "AmortizedCost":
            metrics.append("UnblendedCost")
        return metrics

    def _fetch_cost_data(
        self,
        days: int,
        ce_client,
        account_id: str,
        account_name: str | None,
    ) -> list[UnifiedCost]:
        """Fetch costs for ALL services from Cost Explorer for one account.

        When ``self.tag_keys`` is non-empty we also pull tag-grouped data and
        attach a ``tag_breakdown`` map to each service row so the UI / chat
        agent can slice by team/project/env without re-querying AWS.
        """
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        response = ce_client.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=self._ce_metrics(),
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        tag_breakdowns: dict[tuple[str, str, str], dict[str, float]] = {}
        if self.tag_keys:
            tag_breakdowns = self._fetch_tag_breakdowns(
                ce_client, start, end, self.tag_keys, account_id
            )

        costs: list[UnifiedCost] = []
        for result in response.get("ResultsByTime", []):
            date = result["TimePeriod"]["Start"]
            for group in result.get("Groups", []):
                service_name = group["Keys"][0]
                metrics = group["Metrics"]

                amount = float(metrics[self.cost_type]["Amount"])
                usage = float(metrics["UsageQuantity"]["Amount"])
                usage_unit = metrics["UsageQuantity"].get("Unit", "")

                if amount == 0:
                    continue

                display_name = SERVICE_DISPLAY_NAMES.get(service_name, service_name)
                service_key = display_name.lower().replace(" ", "_")

                metadata: dict = {
                    "account_id": account_id,
                    "cost_type": self.cost_type,
                }
                if account_name:
                    metadata["account_name"] = account_name

                # Surface RI/SP amortization delta when available
                if self.cost_type == "AmortizedCost" and "UnblendedCost" in metrics:
                    unblended = float(metrics["UnblendedCost"]["Amount"])
                    metadata["unblended_cost_usd"] = round(unblended, 4)
                    metadata["amortized_delta_usd"] = round(unblended - amount, 4)

                key = (date, service_name, account_id)
                if key in tag_breakdowns:
                    metadata["tag_breakdown"] = tag_breakdowns[key]

                costs.append(UnifiedCost(
                    date=date,
                    platform="aws",
                    service=f"aws_{service_key}",
                    resource=display_name,
                    category=SERVICE_CATEGORY_MAP.get(service_name, CostCategory.compute),
                    cost_usd=round(amount, 4),
                    usage_quantity=round(usage, 4),
                    usage_unit=usage_unit,
                    metadata=metadata,
                ))

        return costs

    def _fetch_tag_breakdowns(
        self,
        ce_client,
        start: str,
        end: str,
        tag_keys: Iterable[str],
        account_id: str,
    ) -> dict[tuple[str, str, str], dict[str, float]]:
        """Group cost by SERVICE + TAG for each activated tag key.

        Returns a dict keyed by (date, service_name, account_id) whose values
        are ``{"<tag_key>:<tag_value>": cost_usd, ...}``. This runs one API
        call per tag key (Cost Explorer allows at most two GroupBy clauses).
        """
        breakdowns: dict[tuple[str, str, str], dict[str, float]] = {}
        for tag_key in tag_keys:
            try:
                resp = ce_client.get_cost_and_usage(
                    TimePeriod={"Start": start, "End": end},
                    Granularity="DAILY",
                    Metrics=[self.cost_type],
                    GroupBy=[
                        {"Type": "DIMENSION", "Key": "SERVICE"},
                        {"Type": "TAG", "Key": tag_key},
                    ],
                )
            except Exception:
                continue

            for result in resp.get("ResultsByTime", []):
                date = result["TimePeriod"]["Start"]
                for group in result.get("Groups", []):
                    keys = group.get("Keys", [])
                    if len(keys) != 2:
                        continue
                    service_name, tag_pair = keys
                    amount = float(group["Metrics"][self.cost_type]["Amount"])
                    if amount == 0:
                        continue
                    # AWS returns tag values as "<key>$<value>"; fall back to raw.
                    tag_value = tag_pair.split("$", 1)[1] if "$" in tag_pair else tag_pair
                    entry_key = (date, service_name, account_id)
                    bucket = breakdowns.setdefault(entry_key, {})
                    label = f"{tag_key}:{tag_value or 'untagged'}"
                    bucket[label] = round(bucket.get(label, 0) + amount, 4)
        return breakdowns

    # ─── Inventory (unchanged behaviour) ───────────────────────────

    def _fetch_inventory(self) -> list[UnifiedCost]:
        """Fetch resource inventory (S3 buckets, EC2 instances, Lambda, etc.)
        as zero-cost records so they appear in the UI."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        inventory: list[UnifiedCost] = []

        # S3 Buckets — with size, object count from CloudWatch
        try:
            s3 = self._session.client("s3")
            cw = self._session.client("cloudwatch")
            buckets = s3.list_buckets().get("Buckets", [])

            cw_end = datetime.utcnow()
            cw_start = cw_end - timedelta(days=3)

            for b in buckets:
                name = b["Name"]
                created = b.get("CreationDate", "")
                created_str = created.isoformat() if hasattr(created, "isoformat") else str(created)

                size_bytes = 0
                obj_count = 0
                try:
                    sr = cw.get_metric_statistics(
                        Namespace="AWS/S3", MetricName="BucketSizeBytes",
                        Dimensions=[{"Name": "BucketName", "Value": name}, {"Name": "StorageType", "Value": "StandardStorage"}],
                        StartTime=cw_start, EndTime=cw_end, Period=86400, Statistics=["Average"],
                    )
                    if sr["Datapoints"]:
                        size_bytes = sr["Datapoints"][-1]["Average"]

                    cr = cw.get_metric_statistics(
                        Namespace="AWS/S3", MetricName="NumberOfObjects",
                        Dimensions=[{"Name": "BucketName", "Value": name}, {"Name": "StorageType", "Value": "AllStorageTypes"}],
                        StartTime=cw_start, EndTime=cw_end, Period=86400, Statistics=["Average"],
                    )
                    if cr["Datapoints"]:
                        obj_count = int(cr["Datapoints"][-1]["Average"])
                except Exception:
                    pass

                region = self.region
                try:
                    loc = s3.get_bucket_location(Bucket=name)
                    region = loc.get("LocationConstraint") or "us-east-1"
                except Exception:
                    pass

                size_gb = round(size_bytes / (1024 ** 3), 4)
                size_mb = round(size_bytes / (1024 ** 2), 2)

                inventory.append(UnifiedCost(
                    date=today,
                    platform="aws",
                    service="aws_s3",
                    resource=name,
                    category=CostCategory.storage,
                    cost_usd=0,
                    usage_quantity=size_gb,
                    usage_unit="GB",
                    metadata={
                        "account_id": self.account_id,
                        "type": "inventory",
                        "created": created_str,
                        "size_bytes": size_bytes,
                        "size_mb": size_mb,
                        "object_count": obj_count,
                        "region": region,
                    },
                ))
        except Exception:
            pass

        # EC2 Instances
        try:
            ec2 = self._session.client("ec2")
            reservations = ec2.describe_instances().get("Reservations", [])
            for r in reservations:
                for inst in r.get("Instances", []):
                    name = ""
                    for tag in inst.get("Tags", []):
                        if tag["Key"] == "Name":
                            name = tag["Value"]
                    label = f"{name} ({inst['InstanceId']})" if name else inst["InstanceId"]
                    inventory.append(UnifiedCost(
                        date=today,
                        platform="aws",
                        service="aws_ec2",
                        resource=label,
                        category=CostCategory.compute,
                        cost_usd=0,
                        usage_quantity=0,
                        usage_unit="instance",
                        metadata={
                            "account_id": self.account_id,
                            "type": "inventory",
                            "instance_type": inst.get("InstanceType", ""),
                            "state": inst.get("State", {}).get("Name", ""),
                            "instance_id": inst["InstanceId"],
                        },
                    ))
        except Exception:
            pass

        # Lambda Functions
        try:
            lam = self._session.client("lambda")
            functions = lam.list_functions().get("Functions", [])
            for fn in functions:
                inventory.append(UnifiedCost(
                    date=today,
                    platform="aws",
                    service="aws_lambda",
                    resource=fn["FunctionName"],
                    category=CostCategory.compute,
                    cost_usd=0,
                    usage_quantity=0,
                    usage_unit="function",
                    metadata={
                        "account_id": self.account_id,
                        "type": "inventory",
                        "runtime": fn.get("Runtime", ""),
                        "memory_mb": fn.get("MemorySize", 0),
                    },
                ))
        except Exception:
            pass

        return inventory
