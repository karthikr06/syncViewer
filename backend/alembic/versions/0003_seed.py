"""seed roles, providers, resource types, metric definitions"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ROLES = [(1, "admin"), (2, "user"), (3, "viewer")]
PROVIDERS = [(1, "azure", "Microsoft Azure", True), (2, "aws", "Amazon Web Services", False),
             (3, "gcp", "Google Cloud", False), (4, "mock", "Mock (generator)", True)]
METRICS = [(1, "availability", "bool"), (2, "cpu_percent", "percent"),
           (3, "memory_percent", "percent"), (4, "disk_used_percent", "percent"),
           (5, "network_in_bytes", "bytes"), (6, "network_out_bytes", "bytes")]


def upgrade() -> None:
    meta = sa.MetaData()
    roles = sa.Table("roles", meta, autoload_with=op.get_bind())
    providers = sa.Table("providers", meta, autoload_with=op.get_bind())
    rtypes = sa.Table("resource_types", meta, autoload_with=op.get_bind())
    metrics = sa.Table("metric_definitions", meta, autoload_with=op.get_bind())
    op.bulk_insert(roles, [{"id": i, "name": n} for i, n in ROLES])
    op.bulk_insert(providers, [
        {"id": i, "code": c, "name": n, "is_enabled": e} for i, c, n, e in PROVIDERS])
    op.bulk_insert(rtypes, [
        {"id": p[0], "provider_id": p[0], "code": "vm"} for p in PROVIDERS])
    op.bulk_insert(metrics, [{"id": i, "code": c, "unit": u} for i, c, u in METRICS])


def downgrade() -> None:
    for t in ("metric_definitions", "resource_types", "providers", "roles"):
        op.execute(f"DELETE FROM {t}")
