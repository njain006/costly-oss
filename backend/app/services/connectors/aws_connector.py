"""AWS Cost Explorer connector.

Pulls costs for ALL AWS services and inventories resources
(S3 buckets, EC2 instances, Lambda functions, etc.).
"""

from datetime import datetime, timedelta

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


class AWSConnector(BaseConnector):
    platform = "aws"

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        self.region = credentials.get("region", "us-east-1")
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

    def test_connection(self) -> dict:
        try:
            end = datetime.utcnow().strftime("%Y-%m-%d")
            start = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            self.client.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
            )
            return {"success": True, "message": "AWS Cost Explorer connection successful"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        costs = self._fetch_cost_data(days)
        inventory = self._fetch_inventory()
        costs.extend(inventory)
        return costs

    def _fetch_cost_data(self, days: int) -> list[UnifiedCost]:
        """Fetch costs for ALL services from Cost Explorer."""
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        response = self.client.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost", "UsageQuantity"],
            GroupBy=[
                {"Type": "DIMENSION", "Key": "SERVICE"},
            ],
        )

        costs = []
        for result in response.get("ResultsByTime", []):
            date = result["TimePeriod"]["Start"]
            for group in result.get("Groups", []):
                service_name = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                usage = float(group["Metrics"]["UsageQuantity"]["Amount"])
                usage_unit = group["Metrics"]["UsageQuantity"].get("Unit", "")

                if amount == 0:
                    continue

                display_name = SERVICE_DISPLAY_NAMES.get(service_name, service_name)
                service_key = display_name.lower().replace(" ", "_")

                costs.append(UnifiedCost(
                    date=date,
                    platform="aws",
                    service=f"aws_{service_key}",
                    resource=display_name,
                    category=SERVICE_CATEGORY_MAP.get(service_name, CostCategory.compute),
                    cost_usd=round(amount, 4),
                    usage_quantity=round(usage, 4),
                    usage_unit=usage_unit,
                    metadata={"account_id": self.account_id},
                ))

        return costs

    def _fetch_inventory(self) -> list[UnifiedCost]:
        """Fetch resource inventory (S3 buckets, EC2 instances, Lambda, etc.)
        as zero-cost records so they appear in the UI."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        inventory = []

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

                # Get bucket size from CloudWatch
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

                # Get region
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
