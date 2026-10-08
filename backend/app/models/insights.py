import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, VersionMixin


class Recommendation(Base, VersionMixin, TimestampMixin):
    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint(
            "category IN ('rightsizing','reliability','capacity','waste','pattern')",
            name="category_valid",
        ),
        CheckConstraint("severity IN ('info','warning','critical')", name="severity_valid"),
        CheckConstraint("status IN ('new','dismissed','done')", name="status_valid"),
        CheckConstraint("source IN ('rule','agent')", name="source_valid"),
        Index(
            "uq_recommendations_open_dedupe",
            "workspace_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status = 'new'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(15), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, server_default="info")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="new")
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="rule")
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)


class InsightDigest(Base, VersionMixin):
    __tablename__ = "insight_digests"
    __table_args__ = (
        CheckConstraint("generated_by IN ('rules','agent')", name="generated_by_valid"),
        CheckConstraint("period_end >= period_start", name="period_ordered"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(10), nullable=False, server_default="rules")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    tools_called: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    model: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ok")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
