"""Deep tests for the AWS Cost Explorer connector.

Covers:
1. ``cost_type`` credential validation + AmortizedCost path (metadata carries
   the UnblendedCost delta so RI/SP savings are visible to the UI).
2. Cost allocation tag breakdown is attached to each matching service row.
3. Multi-account STS AssumeRole fan-out — parametrized across 1, 2, and 5
   accounts. Each assumed account gets its own ``account_id`` on every row.

All AWS SDK calls are mocked; no network I/O.
"""

from __future__ import annotations

from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from app.models.platform import UnifiedCost, CostCategory


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

BASE_CREDS = {
    "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
    "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "region": "us-east-1",
}


def _cost_row(service: str, amount: str, unblended: str | None = None) -> dict:
    """Build a Cost Explorer Group payload for one service."""
    metrics: dict = {
        "UnblendedCost": {"Amount": unblended if unblended is not None else amount},
        "AmortizedCost": {"Amount": amount},
        "UsageQuantity": {"Amount": "100", "Unit": "GB"},
    }
    return {"Keys": [service], "Metrics": metrics}


def _ce_response(date: str, rows: list[dict]) -> dict:
    return {"ResultsByTime": [{"TimePeriod": {"Start": date}, "Groups": rows}]}


def _fake_boto_factory(
    account_id: str,
    ce_response: dict,
    tag_response: dict | None = None,
    assume_role_responses: dict[str, dict] | None = None,
) -> Callable:
    """Return a function that can be used as ``boto3.client`` side_effect.

    - ``ce`` client → returns ``ce_response`` on ``get_cost_and_usage``; if a
      ``tag_response`` is provided, the second call (the tag-grouped one)
      returns that payload.
    - ``sts`` client → ``get_caller_identity`` returns ``account_id``;
      ``assume_role`` looks up the RoleArn in ``assume_role_responses``.
    """
    assume_role_responses = assume_role_responses or {}

    def _make(service: str, *args, **kwargs):
        client = MagicMock(name=f"{service}-client")
        if service == "ce":
            # First call returns service breakdown; subsequent calls return
            # tag-grouped data (one per tag key).
            side_effects = [ce_response]
            if tag_response is not None:
                side_effects.append(tag_response)
            client.get_cost_and_usage.side_effect = (
                side_effects + [ce_response] * 10  # safety buffer
            )
        elif service == "sts":
            client.get_caller_identity.return_value = {"Account": account_id}

            def _assume(**assume_kwargs):
                arn = assume_kwargs["RoleArn"]
                return assume_role_responses.get(
                    arn,
                    {
                        "Credentials": {
                            "AccessKeyId": "AKIA-MEMBER",
                            "SecretAccessKey": "SECRET",
                            "SessionToken": "SESSION",
                        }
                    },
                )

            client.assume_role.side_effect = _assume
        return client

    return _make


# --------------------------------------------------------------------------- #
# cost_type toggle
# --------------------------------------------------------------------------- #


class TestCostTypeToggle:
    """AmortizedCost is the FinOps-truthful number for RI/SP customers."""

    def test_default_is_unblended(self):
        from app.services.connectors.aws_connector import AWSConnector

        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", _ce_response("2026-04-01", [])),
        ):
            conn = AWSConnector(BASE_CREDS)
        assert conn.cost_type == "UnblendedCost"

    @pytest.mark.parametrize(
        "cost_type",
        ["UnblendedCost", "AmortizedCost", "BlendedCost", "NetUnblendedCost", "NetAmortizedCost"],
    )
    def test_accepts_valid_cost_types(self, cost_type):
        from app.services.connectors.aws_connector import AWSConnector

        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", _ce_response("2026-04-01", [])),
        ):
            conn = AWSConnector({**BASE_CREDS, "cost_type": cost_type})
        assert conn.cost_type == cost_type

    def test_rejects_invalid_cost_type(self):
        from app.services.connectors.aws_connector import AWSConnector

        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", _ce_response("2026-04-01", [])),
        ):
            with pytest.raises(ValueError, match="Invalid cost_type"):
                AWSConnector({**BASE_CREDS, "cost_type": "MagicMoneyCost"})

    def test_amortized_populates_savings_delta(self):
        from app.services.connectors.aws_connector import AWSConnector

        ce_resp = _ce_response(
            "2026-04-01",
            [_cost_row("Amazon Redshift", amount="80.00", unblended="100.00")],
        )
        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", ce_resp),
        ):
            conn = AWSConnector({**BASE_CREDS, "cost_type": "AmortizedCost"})
            costs = conn.fetch_costs(days=7)

        service_costs = [c for c in costs if c.metadata.get("type") != "inventory"]
        assert len(service_costs) == 1
        row = service_costs[0]
        assert row.cost_usd == 80.00
        assert row.metadata["cost_type"] == "AmortizedCost"
        assert row.metadata["unblended_cost_usd"] == 100.00
        # $100 cash − $80 amortized = $20 of RI/SP savings surfaced on the row
        assert row.metadata["amortized_delta_usd"] == 20.00


# --------------------------------------------------------------------------- #
# Tag allocation
# --------------------------------------------------------------------------- #


class TestTagBreakdown:
    """Cost allocation tags light up the team/project/env story."""

    def test_no_tags_means_no_breakdown(self):
        from app.services.connectors.aws_connector import AWSConnector

        ce_resp = _ce_response("2026-04-01", [_cost_row("Amazon Simple Storage Service", "12.50")])
        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", ce_resp),
        ):
            conn = AWSConnector(BASE_CREDS)
            costs = conn.fetch_costs(days=7)

        service_rows = [c for c in costs if c.metadata.get("type") != "inventory"]
        assert "tag_breakdown" not in service_rows[0].metadata

    def test_tag_keys_parsed_from_csv(self):
        from app.services.connectors.aws_connector import AWSConnector

        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", _ce_response("2026-04-01", [])),
        ):
            conn = AWSConnector({**BASE_CREDS, "cost_allocation_tag_keys": "team, project ,env"})
        assert conn.tag_keys == ["team", "project", "env"]

    def test_tag_breakdown_attached_to_service_row(self):
        from app.services.connectors.aws_connector import AWSConnector

        ce_resp = _ce_response(
            "2026-04-01",
            [_cost_row("Amazon Simple Storage Service", "100.00")],
        )
        # Tag response: S3 cost split across team=analytics / team=growth
        tag_resp = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-04-01"},
                    "Groups": [
                        {
                            "Keys": ["Amazon Simple Storage Service", "team$analytics"],
                            "Metrics": {"UnblendedCost": {"Amount": "60.00"}},
                        },
                        {
                            "Keys": ["Amazon Simple Storage Service", "team$growth"],
                            "Metrics": {"UnblendedCost": {"Amount": "40.00"}},
                        },
                    ],
                }
            ]
        }
        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", ce_resp, tag_response=tag_resp),
        ):
            conn = AWSConnector({**BASE_CREDS, "cost_allocation_tag_keys": "team"})
            costs = conn.fetch_costs(days=7)

        service_rows = [c for c in costs if c.metadata.get("type") != "inventory"]
        assert len(service_rows) == 1
        breakdown = service_rows[0].metadata.get("tag_breakdown")
        assert breakdown == {"team:analytics": 60.00, "team:growth": 40.00}


# --------------------------------------------------------------------------- #
# Multi-account fan-out
# --------------------------------------------------------------------------- #


def _role_arn(account_id: str) -> str:
    return f"arn:aws:iam::{account_id}:role/CostlyReadOnly"


@pytest.mark.parametrize("num_accounts", [1, 2, 5])
class TestMultiAccountFanOut:
    """STS AssumeRole should emit per-account cost rows with account_id set."""

    def test_fan_out_emits_rows_per_account(self, num_accounts):
        from app.services.connectors.aws_connector import AWSConnector

        payer_account = "111122223333"
        member_accounts = [f"{i:012d}" for i in range(222222222200, 222222222200 + (num_accounts - 1))]
        role_arns = [_role_arn(a) for a in member_accounts]

        # Each account produces a single S3 row so we can count cleanly
        ce_resp = _ce_response(
            "2026-04-01",
            [_cost_row("Amazon Simple Storage Service", "10.00")],
        )

        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory(
                payer_account,
                ce_resp,
                assume_role_responses={
                    arn: {
                        "Credentials": {
                            "AccessKeyId": f"AKIA-{i}",
                            "SecretAccessKey": "S",
                            "SessionToken": "T",
                        }
                    }
                    for i, arn in enumerate(role_arns)
                },
            ),
        ):
            conn = AWSConnector(
                {
                    **BASE_CREDS,
                    "member_account_role_arns": ",".join(role_arns),
                }
            )
            costs = conn.fetch_costs(days=7)

        service_rows = [c for c in costs if c.metadata.get("type") != "inventory"]
        # 1 payer row + one row per member account = num_accounts total
        assert len(service_rows) == num_accounts

        observed_accounts = {r.metadata["account_id"] for r in service_rows}
        expected_accounts = {payer_account, *member_accounts}
        assert observed_accounts == expected_accounts

        # Every row must be a valid UnifiedCost
        for row in service_rows:
            assert isinstance(row, UnifiedCost)
            assert row.platform == "aws"

    def test_member_account_name_parsed_from_role_arn(self, num_accounts):
        from app.services.connectors.aws_connector import AWSConnector

        payer_account = "111122223333"
        members = [f"{i:012d}" for i in range(444444444400, 444444444400 + (num_accounts - 1))]
        role_arns = [_role_arn(a) for a in members]

        ce_resp = _ce_response(
            "2026-04-01",
            [_cost_row("Amazon Simple Storage Service", "5.00")],
        )

        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory(payer_account, ce_resp),
        ):
            conn = AWSConnector(
                {**BASE_CREDS, "member_account_role_arns": role_arns}
            )
            costs = conn.fetch_costs(days=7)

        service_rows = [c for c in costs if c.metadata.get("type") != "inventory"]
        member_rows = [r for r in service_rows if r.metadata["account_id"] != payer_account]
        assert len(member_rows) == num_accounts - 1
        # account_name metadata comes from the role name fragment
        for row in member_rows:
            assert row.metadata.get("account_name") == "CostlyReadOnly"

    def test_failed_assume_role_does_not_break_other_accounts(self, num_accounts):
        from app.services.connectors.aws_connector import AWSConnector

        if num_accounts < 2:
            pytest.skip("Need at least one member to trigger assume-role failure")

        payer_account = "111122223333"
        members = [f"{i:012d}" for i in range(555555555500, 555555555500 + (num_accounts - 1))]
        role_arns = [_role_arn(a) for a in members]

        ce_resp = _ce_response(
            "2026-04-01",
            [_cost_row("Amazon Simple Storage Service", "7.00")],
        )

        # Make the first member role fail; others succeed.
        def assume_side_effect(**kwargs):
            if kwargs["RoleArn"] == role_arns[0]:
                raise RuntimeError("AccessDenied")
            return {
                "Credentials": {
                    "AccessKeyId": "OK",
                    "SecretAccessKey": "OK",
                    "SessionToken": "OK",
                }
            }

        def make_client(service, *args, **kwargs):
            client = MagicMock(name=service)
            if service == "ce":
                client.get_cost_and_usage.return_value = ce_resp
            elif service == "sts":
                client.get_caller_identity.return_value = {"Account": payer_account}
                client.assume_role.side_effect = assume_side_effect
            return client

        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=make_client,
        ):
            conn = AWSConnector(
                {**BASE_CREDS, "member_account_role_arns": role_arns}
            )
            costs = conn.fetch_costs(days=7)

        service_rows = [c for c in costs if c.metadata.get("type") != "inventory"]
        # Payer + (num_accounts - 2) successful members; 1 member failed.
        assert len(service_rows) == num_accounts - 1


# --------------------------------------------------------------------------- #
# Existing behaviour (regression guards)
# --------------------------------------------------------------------------- #


class TestRegressionGuards:
    """Fail loudly if the connector's external contract shifts."""

    def test_every_row_carries_account_id(self):
        from app.services.connectors.aws_connector import AWSConnector

        ce_resp = _ce_response(
            "2026-04-01",
            [_cost_row("Amazon Simple Storage Service", "1.00")],
        )
        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("999988887777", ce_resp),
        ):
            conn = AWSConnector(BASE_CREDS)
            costs = conn.fetch_costs(days=1)

        service_rows = [c for c in costs if c.metadata.get("type") != "inventory"]
        assert service_rows, "Expected at least one cost row"
        for row in service_rows:
            assert row.metadata.get("account_id") == "999988887777"

    def test_zero_cost_rows_are_skipped(self):
        from app.services.connectors.aws_connector import AWSConnector

        ce_resp = _ce_response(
            "2026-04-01",
            [_cost_row("Amazon Simple Storage Service", "0")],
        )
        with patch(
            "app.services.connectors.aws_connector.boto3.client",
            side_effect=_fake_boto_factory("111122223333", ce_resp),
        ):
            conn = AWSConnector(BASE_CREDS)
            costs = conn.fetch_costs(days=1)

        service_rows = [c for c in costs if c.metadata.get("type") != "inventory"]
        assert service_rows == []

    def test_service_category_mapping_is_preserved(self):
        from app.services.connectors.aws_connector import AWSConnector, SERVICE_CATEGORY_MAP

        assert SERVICE_CATEGORY_MAP["Amazon Bedrock"] == CostCategory.ai_inference
        assert SERVICE_CATEGORY_MAP["Amazon SageMaker"] == CostCategory.ml_training
        assert SERVICE_CATEGORY_MAP["Amazon Simple Storage Service"] == CostCategory.storage
