import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

PROVIDERS = Literal["mock", "azure", "aws", "gcp"]
METRICS = Literal["availability", "cpu_percent", "memory_percent", "disk_used_percent",
                  "network_in_bytes", "network_out_bytes"]
SEVERITY = Literal["info", "warning", "critical"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: PROVIDERS = "mock"
    external_ref: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def _scenario(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "scenario" in v and v["scenario"] not in ("small", "medium", "large"):
            raise ValueError("scenario must be small, medium or large")
        return v


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["active", "paused"] | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    metric: METRICS
    operator: Literal[">", ">=", "<", "<="]
    threshold: float
    duration_minutes: int = Field(default=0, ge=0, le=1440)
    severity: SEVERITY = "warning"
    account_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    is_enabled: bool = True

    @field_validator("resource_id")
    @classmethod
    def _one_scope(cls, v, info):
        if v is not None and info.data.get("account_id") is not None:
            raise ValueError("set either account_id or resource_id, not both")
        return v


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    operator: Literal[">", ">=", "<", "<="] | None = None
    threshold: float | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    severity: SEVERITY | None = None
    is_enabled: bool | None = None


class RecommendationUpdate(BaseModel):
    status: Literal["new", "dismissed", "done"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    configured: bool
    tools_called: list[str] = []


class UserUpdate(BaseModel):
    role: Literal["admin", "user", "viewer"] | None = None
    is_active: bool | None = None
