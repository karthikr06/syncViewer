"""baseline: 17 tables

Created from the SQLAlchemy models (see docs/decisions.md). Later migrations never touch the
models' metadata, so this stays a frozen baseline only as long as models are changed through
new migrations.
"""
from alembic import op
from app.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
