import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, VersionMixin
from app.models.identity import Provider


class CloudAccount(Base, VersionMixin, TimestampMixin):
    __tablename__ = "cloud_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active','paused','error')", name="status_valid"),
        UniqueConstraint("owner_id", "provider_id", "external_ref", name="uq_cloud_accounts_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    provider: Mapped[Provider] = relationship(lazy="joined")

    @property
    def provider_code(self) -> str:
        return self.provider.code


class ResourceType(Base):
    __tablename__ = "resource_types"
    __table_args__ = (UniqueConstraint("provider_id", "code", name="uq_resource_types_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)


class Resource(Base, VersionMixin, TimestampMixin):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint(
            "power_state IN ('running','stopped','deallocated','unknown')", name="power_valid"
        ),
        CheckConstraint(
            "health_state IN ('healthy','degraded','unavailable','unknown')", name="health_valid"
        ),
        UniqueConstraint("account_id", "external_id", name="uq_resources_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cloud_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type_id: Mapped[int] = mapped_column(ForeignKey("resource_types.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str | None] = mapped_column(String(60))
    size_sku: Mapped[str | None] = mapped_column(String(80))
    power_state: Mapped[str] = mapped_column(String(15), nullable=False, server_default="unknown")
    health_state: Mapped[str] = mapped_column(String(15), nullable=False, server_default="unknown")
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
