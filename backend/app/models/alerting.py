import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, VersionMixin
from app.models.metrics import MetricDefinition


class AlertRule(Base, VersionMixin, TimestampMixin):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint("operator IN ('>','>=','<','<=')", name="operator_valid"),
        CheckConstraint("severity IN ('info','warning','critical')", name="severity_valid"),
        CheckConstraint(
            "NOT (account_id IS NOT NULL AND resource_id IS NOT NULL)", name="single_scope"
        ),
        CheckConstraint("duration_minutes >= 0", name="duration_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cloud_accounts.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    metric_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), nullable=False)
    operator: Mapped[str] = mapped_column(String(2), nullable=False)
    threshold: Mapped[float] = mapped_column(Double, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    severity: Mapped[str] = mapped_column(String(10), nullable=False, server_default="warning")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    metric_def: Mapped[MetricDefinition] = relationship(lazy="joined")

    @property
    def metric(self) -> str:
        return self.metric_def.code


class Alert(Base, VersionMixin):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("state IN ('open','acknowledged','resolved')", name="state_valid"),
        # at most one unresolved alert per (rule, resource)
        Index(
            "uq_alerts_active",
            "rule_id",
            "resource_id",
            unique=True,
            postgresql_where=text("state <> 'resolved'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(15), nullable=False, server_default="open")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value_at_open: Mapped[float | None] = mapped_column(Double)


__all__ = ["Alert", "AlertRule", "SmallInteger"]
