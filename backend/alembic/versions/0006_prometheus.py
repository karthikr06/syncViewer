"""prometheus provider: read-only VM monitoring through a Prometheus query API"""
import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

PROVIDER_ID = 5


def _check(codes: str) -> None:
    op.execute("ALTER TABLE providers DROP CONSTRAINT ck_providers_code_valid")
    op.execute(f"ALTER TABLE providers ADD CONSTRAINT ck_providers_code_valid "
               f"CHECK (code IN ({codes}))")


def upgrade() -> None:
    _check("'azure','aws','gcp','mock','prometheus'")
    meta = sa.MetaData()
    providers = sa.Table("providers", meta, autoload_with=op.get_bind())
    rtypes = sa.Table("resource_types", meta, autoload_with=op.get_bind())
    op.bulk_insert(providers, [{"id": PROVIDER_ID, "code": "prometheus", "name": "Prometheus",
                                "is_enabled": True}])
    op.bulk_insert(rtypes, [{"id": PROVIDER_ID, "provider_id": PROVIDER_ID, "code": "vm"}])


def downgrade() -> None:
    op.execute(f"DELETE FROM resource_types WHERE provider_id = {PROVIDER_ID}")
    op.execute(f"DELETE FROM providers WHERE id = {PROVIDER_ID}")
    _check("'azure','aws','gcp','mock'")
