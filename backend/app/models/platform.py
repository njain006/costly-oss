from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PlatformType(str, Enum):
    snowflake = "snowflake"
    aws = "aws"
    gcp = "gcp"
    dbt_cloud = "dbt_cloud"
    fivetran = "fivetran"
    airbyte = "airbyte"
    databricks = "databricks"
    anthropic = "anthropic"
    claude_code = "claude_code"
    openai = "openai"
    gemini = "gemini"
    confluent = "confluent"
    looker = "looker"
    tableau = "tableau"
    omni = "omni"
    monte_carlo = "monte_carlo"
    github = "github"
    gitlab = "gitlab"


class CostCategory(str, Enum):
    compute = "compute"
    storage = "storage"
    ingestion = "ingestion"
    transformation = "transformation"
    orchestration = "orchestration"
    serving = "serving"
    ai_inference = "ai_inference"
    networking = "networking"
    licensing = "licensing"
    ml_training = "ml_training"
    ml_serving = "ml_serving"
    data_quality = "data_quality"
    ci_cd = "ci_cd"


class PlatformConnectionCreate(BaseModel):
    platform: PlatformType
    name: str = Field(..., description="Display name for this connection")
    credentials: dict = Field(..., description="Platform-specific credentials")
    pricing_overrides: Optional[dict] = Field(
        default=None,
        description="Custom/negotiated pricing. E.g. Snowflake: {credit_price: 2.50}, "
                    "AWS: {edp_discount_pct: 10}, OpenAI: {gpt-4o: {input: 2.0, output: 8.0}}",
    )
    # AWS: {aws_access_key_id, aws_secret_access_key, region}
    # dbt Cloud: {api_token, account_id}
    # Anthropic: {api_key}
    # OpenAI: {api_key, org_id}
    # Gemini: {api_key} or {service_account_json, project_id}
    # Fivetran: {api_key, api_secret}
    # Airbyte: {api_token} or {api_token, host}
    # Monte Carlo: {api_key_id, api_token}
    # BigQuery (gcp): {project_id, service_account_json}
    # Databricks: {account_id, access_token, workspace_url}
    # Looker: {client_id, client_secret, instance_url}
    # Tableau: {server_url, token_name, token_secret, site_id}
    # GitHub: {token, org, repos}
    # GitLab: {token, instance_url, group_id, project_ids}
    # Omni: {api_key, instance_url}


class UnifiedCost(BaseModel):
    """Normalized cost record — every connector produces these."""
    date: str  # YYYY-MM-DD
    platform: PlatformType
    service: str  # aws_s3, aws_redshift, dbt_cloud, snowflake, anthropic, etc.
    resource: str  # bucket name, warehouse name, dbt job, model name
    category: CostCategory
    cost_usd: float
    usage_quantity: float = 0.0
    usage_unit: str = ""  # credits, GB, tokens, seconds, requests
    team: Optional[str] = None
    project: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class CostSummary(BaseModel):
    """Aggregated cost view for reports and dashboards."""
    total_cost: float
    period_start: str
    period_end: str
    by_platform: list[dict] = []
    by_category: list[dict] = []
    by_service: list[dict] = []
    by_team: list[dict] = []
    daily_trend: list[dict] = []
    top_resources: list[dict] = []
    month_over_month_change: Optional[float] = None
