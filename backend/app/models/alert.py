from pydantic import BaseModel, field_validator
from typing import Optional


def _check_webhook(url: Optional[str]) -> Optional[str]:
    # The server POSTs to this URL, so only allow Slack's webhook host;
    # anything else would let a user make the server call internal addresses.
    if url and not url.startswith("https://hooks.slack.com/"):
        raise ValueError("webhook_url must be a Slack incoming webhook (https://hooks.slack.com/...)")
    return url


class AlertCreate(BaseModel):
    name: str
    metric: str
    threshold: float
    channel: str
    webhook_url: Optional[str] = None
    # Optional: watch one Snowflake account; default is every account.
    connection_id: Optional[str] = None

    _webhook = field_validator("webhook_url")(classmethod(lambda cls, v: _check_webhook(v)))


class AlertUpdate(BaseModel):
    enabled: Optional[bool] = None
