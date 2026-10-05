import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, VersionMixin


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)


class MetricSample(Base):
    """Append-only; inserted idempotently (ON CONFLICT DO NOTHING)."""

    __tablename__ = "metric_samples"
    __table_args__ = (Index("ix_metric_samples_resource_ts", "resource_id", "ts"),)

    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    metric_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[float] = mapped_column(Double, nullable=False)


class UptimeRollup(Base, VersionMixin):
    __tablename__ = "uptime_rollups"
    __table_args__ = (
        CheckConstraint("up_samples <= total_samples", name="up_le_total"),
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    up_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    total_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cpu: Mapped[float | None] = mapped_column(Double)
    p95_cpu: Mapped[float | None] = mapped_column(Double)
    max_cpu: Mapped[float | None] = mapped_column(Double)
    avg_memory: Mapped[float | None] = mapped_column(Double)
    max_disk: Mapped[float | None] = mapped_column(Double)


class Incident(Base, VersionMixin, TimestampMixin):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("kind IN ('outage','degraded')", name="kind_valid"),
        UniqueConstraint("resource_id", "started_at", "kind", name="uq_incidents_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default="outage")


__all__ = ["Incident", "MetricDefinition", "MetricSample", "UptimeRollup", "func"]
