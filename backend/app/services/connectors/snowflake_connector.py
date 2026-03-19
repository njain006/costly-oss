"""Snowflake connector for the unified platform system.

Uses key-pair auth to connect and query ACCOUNT_USAGE views.
Reuses build_sf_connection() from services/snowflake.py.
"""

from datetime import datetime, timedelta

from app.models.platform import UnifiedCost, CostCategory
from app.services.connectors.base import BaseConnector


def _to_conn_doc(credentials: dict) -> dict:
    """Convert platform_connections credentials to the conn_doc format
    that build_sf_connection() and all snowflake.py functions expect."""
    from app.services.encryption import encrypt_value

    return {
        "account": credentials.get("account", "").strip().lower().replace(".snowflakecomputing.com", ""),
        "username": credentials.get("user", ""),
        "auth_type": "keypair",
        "private_key_encrypted": encrypt_value(credentials["private_key"]),
        "warehouse": credentials.get("warehouse", "COMPUTE_WH"),
        "database": credentials.get("database", "SNOWFLAKE"),
        "schema_name": credentials.get("schema_name", "ACCOUNT_USAGE"),
        "role": credentials.get("role", "ACCOUNTADMIN"),
    }


class SnowflakeConnector(BaseConnector):
    platform = "snowflake"

    def __init__(self, credentials: dict):
        super().__init__(credentials)
        self.conn_doc = _to_conn_doc(credentials)

    def test_connection(self) -> dict:
        try:
            from app.services.snowflake import build_sf_connection
            sf = build_sf_connection(self.conn_doc)
            cur = sf.cursor()
            cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
            row = cur.fetchone()
            cur.close()
            sf.close()
            return {
                "success": True,
                "message": f"Connected as {row[0]}, role {row[1]}, warehouse {row[2]}",
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def fetch_costs(self, days: int = 30) -> list[UnifiedCost]:
        """Query WAREHOUSE_METERING_HISTORY for credit costs."""
        from app.services.snowflake import build_sf_connection

        costs = []
        try:
            sf = build_sf_connection(self.conn_doc)
            cur = sf.cursor()

            # Warehouse credit consumption
            cur.execute(f"""
                SELECT
                    TO_CHAR(START_TIME, 'YYYY-MM-DD') AS date,
                    WAREHOUSE_NAME,
                    SUM(CREDITS_USED) AS credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
                GROUP BY 1, 2
                ORDER BY 1
            """)

            credit_price = 3.00  # Default, can be overridden via pricing_overrides
            for row in cur.fetchall():
                date, warehouse, credits = row
                if credits == 0:
                    continue
                costs.append(UnifiedCost(
                    date=date,
                    platform="snowflake",
                    service="snowflake_compute",
                    resource=warehouse,
                    category=CostCategory.compute,
                    cost_usd=round(float(credits) * credit_price, 4),
                    usage_quantity=round(float(credits), 4),
                    usage_unit="credits",
                ))

            # Storage costs
            cur.execute("""
                SELECT
                    AVERAGE_STAGE_BYTES,
                    AVERAGE_DATABASE_BYTES,
                    AVERAGE_FAILSAFE_BYTES
                FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
                ORDER BY USAGE_DATE DESC
                LIMIT 1
            """)
            storage = cur.fetchone()
            if storage:
                total_tb = sum(float(v or 0) for v in storage) / (1024 ** 4)
                storage_cost = round(total_tb * 23.0, 4)  # $23/TB/month default
                if storage_cost > 0:
                    costs.append(UnifiedCost(
                        date=datetime.utcnow().strftime("%Y-%m-%d"),
                        platform="snowflake",
                        service="snowflake_storage",
                        resource="Account Storage",
                        category=CostCategory.storage,
                        cost_usd=storage_cost,
                        usage_quantity=round(total_tb * 1024, 2),  # GB
                        usage_unit="GB",
                    ))

            cur.close()
            sf.close()
        except Exception:
            pass

        return costs
