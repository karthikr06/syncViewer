"""lock the Supabase auto-generated data API: RLS on, privileges revoked from anon/authenticated

No-op for the role revokes on plain Postgres (tests), where those roles do not exist.
The API connects as the table owner, which bypasses RLS.
"""
from alembic import op

# the tables that existed at this revision (frozen; later migrations lock their own tables)
TABLES = [
    "audit_log", "collector_runs", "metric_definitions", "providers", "roles", "resource_types",
    "users", "agent_runs", "cloud_accounts", "insight_digests", "resources", "alert_rules",
    "incidents", "metric_samples", "recommendations", "uptime_rollups", "alerts",
]

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for t in [*TABLES, "alembic_version"]:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
                    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
                    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
                    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                                   'REVOKE ALL ON TABLES FROM %I', r);
                END IF;
            END LOOP;
        END $$
        """
    )


def downgrade() -> None:
    for t in [*TABLES, "alembic_version"]:
        op.execute(f'ALTER TABLE "{t}" DISABLE ROW LEVEL SECURITY')
