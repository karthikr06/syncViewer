"""workspaces (teams), invites, developer role, VM action history

- Data moves from per-user to per-workspace ownership. Every existing user becomes the admin of a
  workspace whose id equals their user id, so the existing owner_id values are already valid
  workspace ids: the column is renamed and re-pointed, no rows are rewritten.
- Role "user" becomes "developer"; workspace members are developers or viewers.
- agent_runs keep the asking user (user_id) rather than the workspace.
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

OWNED = ("cloud_accounts", "alert_rules", "recommendations", "insight_digests")
NEW_TABLES = ("workspaces", "workspace_invites", "vm_actions")

VIEW_UPTIME = """
    CREATE VIEW v_account_uptime_7d AS
    SELECT a.id AS account_id, a.{col},
           COALESCE(sum(u.up_samples), 0)::bigint AS up_samples,
           COALESCE(sum(u.total_samples), 0)::bigint AS total_samples,
           CASE WHEN COALESCE(sum(u.total_samples), 0) = 0 THEN NULL
                ELSE 100.0 * sum(u.up_samples) / sum(u.total_samples) END AS uptime_percent
    FROM cloud_accounts a
    LEFT JOIN resources r ON r.account_id = a.id AND r.deleted_at IS NULL
    LEFT JOIN uptime_rollups u ON u.resource_id = r.id
                              AND u.bucket_start >= now() - interval '7 days'
    WHERE a.deleted_at IS NULL
    GROUP BY a.id, a.{col}
"""
VIEW_ALERTS = """
    CREATE VIEW v_open_alerts AS
    SELECT al.id, al.rule_id, al.resource_id, al.state, al.opened_at, al.value_at_open,
           ar.{col}, ar.name AS rule_name, ar.severity, r.name AS resource_name
    FROM alerts al
    JOIN alert_rules ar ON ar.id = al.rule_id
    JOIN resources r ON r.id = al.resource_id
    WHERE al.state <> 'resolved'
"""


def _lock(tables) -> None:
    for t in tables:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
    names = ", ".join(tables)
    op.execute(
        f"""
        DO $$
        DECLARE r text;
        BEGIN
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON {names} FROM %I', r);
                END IF;
            END LOOP;
        END $$
        """
    )


def upgrade() -> None:
    op.execute("DROP VIEW v_open_alerts")
    op.execute("DROP VIEW v_account_uptime_7d")

    # --- workspaces: one per existing user, same id ---
    op.execute(
        """
        CREATE TABLE workspaces (
            id UUID DEFAULT gen_random_uuid() NOT NULL,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_workspaces PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        "INSERT INTO workspaces (id, name) "
        "SELECT id, split_part(email, '@', 1) || '''s workspace' FROM users"
    )
    op.execute("ALTER TABLE users ADD COLUMN workspace_id UUID")
    op.execute("UPDATE users SET workspace_id = id")
    op.execute("ALTER TABLE users ALTER COLUMN workspace_id SET NOT NULL")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT fk_users_workspace_id_workspaces "
        "FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX ix_users_workspace_id ON users (workspace_id)")

    # --- roles: user -> developer; existing users own their workspace, so they are its admin ---
    op.execute("ALTER TABLE roles DROP CONSTRAINT ck_roles_name_valid")
    op.execute("UPDATE roles SET name = 'developer' WHERE id = 2")
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_name_valid "
        "CHECK (name IN ('admin','developer','viewer'))"
    )
    op.execute("UPDATE users SET role_id = 1 WHERE role_id = 2")

    # --- owner_id -> workspace_id ---
    for t in OWNED:
        op.execute(f"ALTER TABLE {t} DROP CONSTRAINT fk_{t}_owner_id_users")
        op.execute(f"ALTER TABLE {t} RENAME COLUMN owner_id TO workspace_id")
        op.execute(f"ALTER INDEX ix_{t}_owner_id RENAME TO ix_{t}_workspace_id")
        op.execute(
            f"ALTER TABLE {t} ADD CONSTRAINT fk_{t}_workspace_id_workspaces "
            "FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE"
        )
    op.execute("ALTER TABLE agent_runs RENAME COLUMN owner_id TO user_id")
    op.execute("ALTER INDEX ix_agent_runs_owner_id RENAME TO ix_agent_runs_user_id")
    op.execute(
        "ALTER TABLE agent_runs RENAME CONSTRAINT fk_agent_runs_owner_id_users "
        "TO fk_agent_runs_user_id_users"
    )

    # --- invites ---
    op.execute(
        """
        CREATE TABLE workspace_invites (
            id BIGSERIAL NOT NULL,
            workspace_id UUID NOT NULL,
            email VARCHAR(320) NOT NULL,
            role_id SMALLINT NOT NULL,
            invited_by UUID,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            accepted_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT pk_workspace_invites PRIMARY KEY (id),
            CONSTRAINT ck_workspace_invites_member_role CHECK (role_id IN (2, 3)),
            CONSTRAINT ck_workspace_invites_email_lower CHECK (email = lower(email)),
            CONSTRAINT fk_workspace_invites_workspace_id_workspaces FOREIGN KEY (workspace_id)
                REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT fk_workspace_invites_role_id_roles FOREIGN KEY (role_id)
                REFERENCES roles (id),
            CONSTRAINT fk_workspace_invites_invited_by_users FOREIGN KEY (invited_by)
                REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_workspace_invites_workspace_id ON workspace_invites (workspace_id)")
    op.execute(
        "CREATE UNIQUE INDEX uq_workspace_invites_pending ON workspace_invites (email) "
        "WHERE accepted_at IS NULL"
    )
    op.execute(
        "CREATE TRIGGER trg_workspace_invites_audit AFTER INSERT OR UPDATE OR DELETE "
        "ON workspace_invites FOR EACH ROW EXECUTE FUNCTION write_audit()"
    )

    # --- VM action history ---
    op.execute(
        """
        CREATE TABLE vm_actions (
            id BIGSERIAL NOT NULL,
            resource_id UUID NOT NULL,
            requested_by UUID,
            action VARCHAR(12) NOT NULL,
            status VARCHAR(10) NOT NULL,
            from_state VARCHAR(15),
            to_state VARCHAR(15),
            error TEXT,
            requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_vm_actions PRIMARY KEY (id),
            CONSTRAINT ck_vm_actions_action_valid
                CHECK (action IN ('start','stop','restart','deallocate')),
            CONSTRAINT ck_vm_actions_status_valid CHECK (status IN ('succeeded','failed')),
            CONSTRAINT fk_vm_actions_resource_id_resources FOREIGN KEY (resource_id)
                REFERENCES resources (id) ON DELETE CASCADE,
            CONSTRAINT fk_vm_actions_requested_by_users FOREIGN KEY (requested_by)
                REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_vm_actions_resource_id ON vm_actions (resource_id)")

    op.execute(VIEW_UPTIME.format(col="workspace_id"))
    op.execute(VIEW_ALERTS.format(col="workspace_id"))
    _lock(NEW_TABLES)


def downgrade() -> None:
    op.execute("DROP VIEW v_open_alerts")
    op.execute("DROP VIEW v_account_uptime_7d")
    op.execute("DROP TABLE vm_actions")
    op.execute("DROP TABLE workspace_invites")
    op.execute(
        "ALTER TABLE agent_runs RENAME CONSTRAINT fk_agent_runs_user_id_users "
        "TO fk_agent_runs_owner_id_users"
    )
    op.execute("ALTER INDEX ix_agent_runs_user_id RENAME TO ix_agent_runs_owner_id")
    op.execute("ALTER TABLE agent_runs RENAME COLUMN user_id TO owner_id")
    # data a workspace shares can only go back to one user: its first admin
    for t in OWNED:
        op.execute(f"ALTER TABLE {t} DROP CONSTRAINT fk_{t}_workspace_id_workspaces")
        op.execute(
            f"UPDATE {t} x SET workspace_id = (SELECT u.id FROM users u "
            "WHERE u.workspace_id = x.workspace_id AND u.role_id = 1 "
            "ORDER BY u.created_at LIMIT 1)"
        )
        op.execute(f"DELETE FROM {t} WHERE workspace_id IS NULL")
        op.execute(f"ALTER INDEX ix_{t}_workspace_id RENAME TO ix_{t}_owner_id")
        op.execute(f"ALTER TABLE {t} RENAME COLUMN workspace_id TO owner_id")
        op.execute(
            f"ALTER TABLE {t} ADD CONSTRAINT fk_{t}_owner_id_users "
            "FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE"
        )
    op.execute("UPDATE users SET role_id = 2 WHERE role_id = 1")
    op.execute("ALTER TABLE roles DROP CONSTRAINT ck_roles_name_valid")
    op.execute("UPDATE roles SET name = 'user' WHERE id = 2")
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_name_valid "
        "CHECK (name IN ('admin','user','viewer'))"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT fk_users_workspace_id_workspaces")
    op.execute("DROP INDEX ix_users_workspace_id")
    op.execute("ALTER TABLE users DROP COLUMN workspace_id")
    op.execute("DROP TABLE workspaces")
    op.execute(VIEW_UPTIME.format(col="owner_id"))
    op.execute(VIEW_ALERTS.format(col="owner_id"))
