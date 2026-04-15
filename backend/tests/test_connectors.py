"""Tests for all platform connectors.

Tests verify:
1. Connector instantiation with credentials
2. BaseConnector interface compliance
3. UnifiedCost schema compliance from fetch_costs()
4. SERVICE_CATEGORY_MAP coverage (AWS)
5. Cost estimation functions (AI connectors)
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from app.models.platform import UnifiedCost, CostCategory, PlatformType
from app.services.connectors.base import BaseConnector


def _can_import(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


# ─── Test: All connectors implement BaseConnector ───────────────────

CONNECTOR_CLASSES = [
    ("app.services.connectors.aws_connector", "AWSConnector", "aws"),
    ("app.services.connectors.anthropic_connector", "AnthropicConnector", "anthropic"),
    ("app.services.connectors.dbt_cloud_connector", "DbtCloudConnector", "dbt_cloud"),
    ("app.services.connectors.openai_connector", "OpenAIConnector", "openai"),
    ("app.services.connectors.fivetran_connector", "FivetranConnector", "fivetran"),
    ("app.services.connectors.gemini_connector", "GeminiConnector", "gemini"),
    ("app.services.connectors.airbyte_connector", "AirbyteConnector", "airbyte"),
    ("app.services.connectors.monte_carlo_connector", "MonteCarloConnector", "monte_carlo"),
    ("app.services.connectors.bigquery_connector", "BigQueryConnector", "gcp"),
    ("app.services.connectors.databricks_connector", "DatabricksConnector", "databricks"),
    ("app.services.connectors.looker_connector", "LookerConnector", "looker"),
    ("app.services.connectors.tableau_connector", "TableauConnector", "tableau"),
    ("app.services.connectors.github_connector", "GitHubConnector", "github"),
    ("app.services.connectors.gitlab_connector", "GitLabConnector", "gitlab"),
    ("app.services.connectors.omni_connector", "OmniConnector", "omni"),
]


@pytest.mark.parametrize("module_path,class_name,platform", CONNECTOR_CLASSES)
def test_connector_is_base_connector(module_path, class_name, platform):
    """Every connector must inherit from BaseConnector."""
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    assert issubclass(cls, BaseConnector), f"{class_name} must inherit BaseConnector"


@pytest.mark.parametrize("module_path,class_name,platform", CONNECTOR_CLASSES)
def test_connector_has_platform_attribute(module_path, class_name, platform):
    """Every connector must declare a platform string."""
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    assert hasattr(cls, "platform"), f"{class_name} must have platform attribute"
    assert cls.platform == platform, f"{class_name}.platform should be '{platform}'"


@pytest.mark.parametrize("module_path,class_name,platform", CONNECTOR_CLASSES)
def test_connector_has_required_methods(module_path, class_name, platform):
    """Every connector must implement test_connection() and fetch_costs()."""
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    assert callable(getattr(cls, "test_connection", None)), f"{class_name} missing test_connection()"
    assert callable(getattr(cls, "fetch_costs", None)), f"{class_name} missing fetch_costs()"


# ─── Test: CONNECTOR_MAP registration ──────────────────────────────

@pytest.mark.skipif(
    not _can_import("motor"),
    reason="motor not installed (runs in Docker)"
)
def test_connector_map_has_all_connectors():
    """CONNECTOR_MAP must include all 16 connectors (15 external + snowflake).

    SnowflakeConnector was added to CONNECTOR_MAP in commit bceb94f
    ("Sync with upstream: ... Snowflake unification") and is already on main.
    The expected count here was updated from 15 to reflect that existing addition.
    """
    from app.services.unified_costs import CONNECTOR_MAP
    expected = {"snowflake", "aws", "anthropic", "dbt_cloud", "openai", "fivetran", "gemini",
                "airbyte", "monte_carlo", "gcp", "databricks", "looker",
                "tableau", "github", "gitlab", "omni"}
    assert set(CONNECTOR_MAP.keys()) == expected


@pytest.mark.skipif(
    not _can_import("motor"),
    reason="motor not installed (runs in Docker)"
)
def test_connector_map_values_are_base_connector():
    """Every entry in CONNECTOR_MAP must be a BaseConnector subclass."""
    from app.services.unified_costs import CONNECTOR_MAP
    for platform, cls in CONNECTOR_MAP.items():
        assert issubclass(cls, BaseConnector), f"CONNECTOR_MAP['{platform}'] is not a BaseConnector"


# ─── Test: AWS connector ───────────────────────────────────────────

class TestAWSConnector:

    @patch("boto3.client")
    def test_instantiation(self, mock_boto, aws_credentials):
        from app.services.connectors.aws_connector import AWSConnector
        mock_client = MagicMock()
        mock_boto.return_value = mock_client
        mock_client.get_caller_identity.return_value = {"Account": "123456789012"}
        conn = AWSConnector(aws_credentials)
        assert conn.platform == "aws"
        assert conn.account_id == "123456789012"

    def test_service_category_map_completeness(self):
        from app.services.connectors.aws_connector import SERVICE_CATEGORY_MAP
        # Must have at least 19 services (expanded from original 11)
        assert len(SERVICE_CATEGORY_MAP) >= 19, f"Expected 19+ services, got {len(SERVICE_CATEGORY_MAP)}"

    def test_service_category_map_values(self):
        from app.services.connectors.aws_connector import SERVICE_CATEGORY_MAP
        for service, category in SERVICE_CATEGORY_MAP.items():
            assert isinstance(category, CostCategory), f"Invalid category for {service}"

    def test_key_services_present(self):
        from app.services.connectors.aws_connector import SERVICE_CATEGORY_MAP
        required = [
            "Amazon Simple Storage Service",
            "Amazon Redshift",
            "AWS Glue",
            "Amazon SageMaker",
            "Amazon Bedrock",
            "AWS Database Migration Service",
            "Amazon Kinesis",
        ]
        for svc in required:
            assert svc in SERVICE_CATEGORY_MAP, f"Missing AWS service: {svc}"

    def test_sagemaker_is_ml_training(self):
        from app.services.connectors.aws_connector import SERVICE_CATEGORY_MAP
        assert SERVICE_CATEGORY_MAP["Amazon SageMaker"] == CostCategory.ml_training

    def test_bedrock_is_ai_inference(self):
        from app.services.connectors.aws_connector import SERVICE_CATEGORY_MAP
        assert SERVICE_CATEGORY_MAP["Amazon Bedrock"] == CostCategory.ai_inference

    @patch("boto3.client")
    def test_fetch_costs_returns_unified_costs(self, mock_boto, aws_credentials):
        from app.services.connectors.aws_connector import AWSConnector

        mock_ce = MagicMock()
        mock_boto.return_value = mock_ce
        mock_ce.get_cost_and_usage.return_value = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-03-01"},
                    "Groups": [
                        {
                            "Keys": ["Amazon Simple Storage Service"],
                            "Metrics": {
                                "UnblendedCost": {"Amount": "12.50"},
                                "UsageQuantity": {"Amount": "1000", "Unit": "GB"},
                            },
                        }
                    ],
                }
            ]
        }

        conn = AWSConnector(aws_credentials)
        costs = conn.fetch_costs(days=7)

        assert len(costs) == 1
        assert isinstance(costs[0], UnifiedCost)
        assert costs[0].platform == "aws"
        # SERVICE_DISPLAY_NAMES maps "Amazon Simple Storage Service" → "S3" → "aws_s3"
        assert costs[0].service == "aws_s3"
        assert costs[0].category == CostCategory.storage
        assert costs[0].cost_usd == 12.50
        assert costs[0].date == "2026-03-01"

    @patch("boto3.client")
    def test_fetch_costs_skips_zero_cost(self, mock_boto, aws_credentials):
        from app.services.connectors.aws_connector import AWSConnector

        mock_ce = MagicMock()
        mock_boto.return_value = mock_ce
        mock_ce.get_cost_and_usage.return_value = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-03-01"},
                    "Groups": [
                        {
                            "Keys": ["Amazon Simple Storage Service"],
                            "Metrics": {
                                "UnblendedCost": {"Amount": "0"},
                                "UsageQuantity": {"Amount": "0", "Unit": ""},
                            },
                        }
                    ],
                }
            ]
        }

        conn = AWSConnector(aws_credentials)
        costs = conn.fetch_costs(days=7)
        assert len(costs) == 0


# ─── Test: OpenAI connector ────────────────────────────────────────

class TestOpenAIConnector:

    def test_instantiation(self, openai_credentials):
        from app.services.connectors.openai_connector import OpenAIConnector
        conn = OpenAIConnector(openai_credentials)
        assert conn.platform == "openai"
        assert conn.org_id == "org-test-123"

    def test_cost_estimation(self):
        from app.services.connectors.openai_connector import _estimate_cost
        # GPT-4o: $2.50/M input, $10/M output
        cost = _estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert cost == 12.5  # $2.50 + $10.00

    def test_cost_estimation_mini(self):
        from app.services.connectors.openai_connector import _estimate_cost
        # GPT-4o-mini: $0.15/M input, $0.60/M output
        cost = _estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == 0.75

    def test_cost_estimation_unknown_model_falls_back(self):
        from app.services.connectors.openai_connector import _estimate_cost
        cost = _estimate_cost("unknown-model-xyz", 1_000_000, 0)
        assert cost > 0  # Should use fallback pricing

    def test_model_pricing_table(self):
        from app.services.connectors.openai_connector import MODEL_PRICING
        required_models = ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"]
        for model in required_models:
            assert model in MODEL_PRICING, f"Missing pricing for {model}"


# ─── Test: Anthropic connector ─────────────────────────────────────

class TestAnthropicConnector:

    def test_instantiation(self, anthropic_credentials):
        from app.services.connectors.anthropic_connector import AnthropicConnector
        conn = AnthropicConnector(anthropic_credentials)
        assert conn.platform == "anthropic"

    def test_cost_estimation(self):
        from app.services.connectors.anthropic_connector import _estimate_cost
        # Sonnet: $3/M input, $15/M output
        cost = _estimate_cost("claude-sonnet-4", 1_000_000, 1_000_000)
        assert cost == 18.0

    def test_cost_estimation_haiku(self):
        from app.services.connectors.anthropic_connector import _estimate_cost
        cost = _estimate_cost("claude-haiku-3-5", 1_000_000, 1_000_000)
        assert cost == 4.8  # $0.80 + $4.00


# ─── Test: dbt Cloud connector ─────────────────────────────────────

class TestDbtCloudConnector:

    def test_instantiation(self, dbt_cloud_credentials):
        from app.services.connectors.dbt_cloud_connector import DbtCloudConnector
        conn = DbtCloudConnector(dbt_cloud_credentials)
        assert conn.platform == "dbt_cloud"


# ─── Test: Fivetran connector ──────────────────────────────────────

class TestFivetranConnector:

    def test_instantiation(self, fivetran_credentials):
        from app.services.connectors.fivetran_connector import FivetranConnector
        conn = FivetranConnector(fivetran_credentials)
        assert conn.platform == "fivetran"


# ─── Test: Gemini connector ────────────────────────────────────────

class TestGeminiConnector:

    def test_instantiation_ai_studio(self, gemini_credentials):
        from app.services.connectors.gemini_connector import GeminiConnector
        conn = GeminiConnector(gemini_credentials)
        assert conn.platform == "gemini"
        assert conn.use_vertex is False

    def test_instantiation_vertex(self):
        from app.services.connectors.gemini_connector import GeminiConnector
        conn = GeminiConnector({
            "service_account_json": '{"type":"service_account"}',
            "project_id": "test-project",
        })
        assert conn.use_vertex is True

    def test_cost_estimation(self):
        from app.services.connectors.gemini_connector import _estimate_cost
        cost = _estimate_cost("gemini-2.0-flash", 1_000_000, 1_000_000)
        assert cost == 0.5  # $0.10 + $0.40


# ─── Test: Airbyte connector ───────────────────────────────────────

class TestAirbyteConnector:

    def test_instantiation_cloud(self, airbyte_credentials):
        from app.services.connectors.airbyte_connector import AirbyteConnector
        conn = AirbyteConnector(airbyte_credentials)
        assert conn.platform == "airbyte"
        assert conn.is_cloud is True

    def test_instantiation_self_hosted(self):
        from app.services.connectors.airbyte_connector import AirbyteConnector
        conn = AirbyteConnector({"api_token": "test", "host": "http://localhost:8001/v1"})
        assert conn.is_cloud is False


# ─── Test: Monte Carlo connector ───────────────────────────────────

class TestMonteCarloConnector:

    def test_instantiation(self, monte_carlo_credentials):
        from app.services.connectors.monte_carlo_connector import MonteCarloConnector
        conn = MonteCarloConnector(monte_carlo_credentials)
        assert conn.platform == "monte_carlo"


# ─── Test: BigQuery connector ──────────────────────────────────────

class TestBigQueryConnector:

    def test_instantiation(self, bigquery_credentials):
        from app.services.connectors.bigquery_connector import BigQueryConnector
        conn = BigQueryConnector(bigquery_credentials)
        assert conn.platform == "gcp"
        assert conn.project_id == "test-project"


# ─── Test: Databricks connector ────────────────────────────────────

class TestDatabricksConnector:

    def test_instantiation(self, databricks_credentials):
        from app.services.connectors.databricks_connector import DatabricksConnector
        conn = DatabricksConnector(databricks_credentials)
        assert conn.platform == "databricks"

    def test_dbu_pricing_table(self):
        from app.services.connectors.databricks_connector import DBU_PRICING
        required_skus = ["ALL_PURPOSE", "JOBS", "SQL", "DLT", "MODEL_SERVING"]
        for sku in required_skus:
            assert sku in DBU_PRICING, f"Missing DBU pricing for {sku}"


# ─── Test: GitHub connector ────────────────────────────────────────

class TestGitHubConnector:

    def test_instantiation(self, github_credentials):
        from app.services.connectors.github_connector import GitHubConnector
        conn = GitHubConnector(github_credentials)
        assert conn.platform == "github"
        assert conn.org == "test-org"

    def test_runner_pricing(self):
        from app.services.connectors.github_connector import RUNNER_PRICING
        assert "ubuntu" in RUNNER_PRICING
        assert "macos" in RUNNER_PRICING
        assert RUNNER_PRICING["macos"] > RUNNER_PRICING["ubuntu"]


# ─── Test: GitLab connector ────────────────────────────────────────

class TestGitLabConnector:

    def test_instantiation(self, gitlab_credentials):
        from app.services.connectors.gitlab_connector import GitLabConnector
        conn = GitLabConnector(gitlab_credentials)
        assert conn.platform == "gitlab"


# ─── Test: Looker connector ────────────────────────────────────────

class TestLookerConnector:

    def test_instantiation(self, looker_credentials):
        from app.services.connectors.looker_connector import LookerConnector
        conn = LookerConnector(looker_credentials)
        assert conn.platform == "looker"


# ─── Test: Tableau connector ───────────────────────────────────────

class TestTableauConnector:

    def test_instantiation(self, tableau_credentials):
        from app.services.connectors.tableau_connector import TableauConnector
        conn = TableauConnector(tableau_credentials)
        assert conn.platform == "tableau"


# ─── Test: Omni connector ──────────────────────────────────────────

class TestOmniConnector:

    def test_instantiation(self, omni_credentials):
        from app.services.connectors.omni_connector import OmniConnector
        conn = OmniConnector(omni_credentials)
        assert conn.platform == "omni"


# ─── Test: UnifiedCost model ───────────────────────────────────────

class TestUnifiedCostModel:

    def test_create_valid_cost(self):
        cost = UnifiedCost(
            date="2026-03-01",
            platform="aws",
            service="aws_s3",
            resource="my-bucket",
            category=CostCategory.storage,
            cost_usd=12.50,
            usage_quantity=1000,
            usage_unit="GB",
        )
        assert cost.cost_usd == 12.50
        assert cost.team is None
        assert cost.metadata == {}

    def test_all_platforms_are_valid(self):
        for p in PlatformType:
            cost = UnifiedCost(
                date="2026-03-01",
                platform=p.value,
                service="test",
                resource="test",
                category=CostCategory.compute,
                cost_usd=1.0,
            )
            assert cost.platform == p.value

    def test_all_categories_are_valid(self):
        for c in CostCategory:
            cost = UnifiedCost(
                date="2026-03-01",
                platform="aws",
                service="test",
                resource="test",
                category=c.value,
                cost_usd=1.0,
            )
            assert cost.category == c.value


# ─── Test: Demo data generators ────────────────────────────────────

class TestDemoData:

    def test_demo_connections(self):
        from app.services.demo_platforms import generate_demo_platform_connections
        conns = generate_demo_platform_connections()
        assert len(conns) >= 3
        platforms = {c["platform"] for c in conns}
        assert "snowflake" in platforms
        assert "aws" in platforms

    def test_demo_unified_costs(self):
        from app.services.demo_platforms import generate_demo_unified_costs
        result = generate_demo_unified_costs(days=7)
        assert "total_cost" in result
        assert result["total_cost"] > 0
        assert len(result["by_platform"]) > 0
        assert len(result["by_category"]) > 0
        assert len(result["daily_trend"]) == 7
        assert len(result["top_resources"]) > 0

    def test_demo_costs_no_claude_references(self):
        """Demo data should not reference Claude models."""
        from app.services.demo_platforms import generate_demo_unified_costs
        import json
        result = generate_demo_unified_costs(days=7)
        result_str = json.dumps(result).lower()
        assert "claude" not in result_str, "Demo data should not mention Claude"
