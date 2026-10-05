"""version trigger, audit trigger, uptime rollup procedure, views"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SYNCED = (
    "resources", "cloud_accounts", "alert_rules", "alerts",
    "recommendations", "insight_digests", "incidents", "uptime_rollups",
)
AUDITED = ("users", "cloud_accounts", "alert_rules", "recommendations")
HAS_UPDATED_AT = ("resources", "cloud_accounts", "alert_rules", "recommendations", "incidents")


def upgrade() -> None:
    op.execute("CREATE SEQUENCE change_seq")
    op.execute(
        """
        CREATE FUNCTION bump_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.version := nextval('change_seq');
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END $$
        """
    )
    for t in SYNCED:
        op.execute(
            f"CREATE TRIGGER trg_{t}_version BEFORE INSERT OR UPDATE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION bump_version()"
        )
    for t in HAS_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER trg_{t}_touch BEFORE UPDATE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION touch_updated_at()"
        )

    # Audit: never copies encrypted credentials.
    op.execute(
        """
        CREATE FUNCTION write_audit() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            actor uuid := NULLIF(current_setting('app.user_id', true), '')::uuid;
            old_row jsonb;
            new_row jsonb;
        BEGIN
            IF TG_OP <> 'INSERT' THEN old_row := to_jsonb(OLD) - 'credentials_encrypted'; END IF;
            IF TG_OP <> 'DELETE' THEN new_row := to_jsonb(NEW) - 'credentials_encrypted'; END IF;
            INSERT INTO audit_log(actor_id, action, entity, entity_id, before, after)
            VALUES (actor, TG_OP, TG_TABLE_NAME,
                    COALESCE(new_row ->> 'id', old_row ->> 'id'), old_row, new_row);
            RETURN COALESCE(NEW, OLD);
        END $$
        """
    )
    for t in AUDITED:
        op.execute(
            f"CREATE TRIGGER trg_{t}_audit AFTER INSERT OR UPDATE OR DELETE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION write_audit()"
        )

    # Hourly rollups from raw samples; idempotent (recomputes touched buckets in full).
    op.execute(
        """
        CREATE FUNCTION compute_uptime_rollup(from_ts timestamptz, to_ts timestamptz)
        RETURNS integer LANGUAGE plpgsql AS $$
        DECLARE affected integer;
        BEGIN
            INSERT INTO uptime_rollups AS r (resource_id, bucket_start, up_samples, total_samples,
                                             avg_cpu, p95_cpu, max_cpu, avg_memory, max_disk)
            SELECT s.resource_id,
                   date_trunc('hour', s.ts) AS bucket_start,
                   count(*) FILTER (WHERE m.code = 'availability' AND s.value = 1)::int,
                   count(*) FILTER (WHERE m.code = 'availability')::int,
                   avg(s.value) FILTER (WHERE m.code = 'cpu_percent'),
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY s.value)
                       FILTER (WHERE m.code = 'cpu_percent'),
                   max(s.value) FILTER (WHERE m.code = 'cpu_percent'),
                   avg(s.value) FILTER (WHERE m.code = 'memory_percent'),
                   max(s.value) FILTER (WHERE m.code = 'disk_used_percent')
            FROM metric_samples s
            JOIN metric_definitions m ON m.id = s.metric_id
            WHERE s.ts >= date_trunc('hour', from_ts)
              AND s.ts <  date_trunc('hour', to_ts) + interval '1 hour'
            GROUP BY s.resource_id, date_trunc('hour', s.ts)
            ON CONFLICT (resource_id, bucket_start) DO UPDATE SET
                up_samples = EXCLUDED.up_samples,
                total_samples = EXCLUDED.total_samples,
                avg_cpu = EXCLUDED.avg_cpu,
                p95_cpu = EXCLUDED.p95_cpu,
                max_cpu = EXCLUDED.max_cpu,
                avg_memory = EXCLUDED.avg_memory,
                max_disk = EXCLUDED.max_disk;
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN affected;
        END $$
        """
    )

    op.execute(
        """
        CREATE VIEW v_resource_latest AS
        SELECT s.resource_id,
               max(s.ts) AS last_ts,
               max(l.value) FILTER (WHERE m.code = 'availability')       AS availability,
               max(l.value) FILTER (WHERE m.code = 'cpu_percent')        AS cpu_percent,
               max(l.value) FILTER (WHERE m.code = 'memory_percent')     AS memory_percent,
               max(l.value) FILTER (WHERE m.code = 'disk_used_percent')  AS disk_used_percent
        FROM (SELECT DISTINCT ON (resource_id, metric_id) resource_id, metric_id, ts, value
              FROM metric_samples ORDER BY resource_id, metric_id, ts DESC) l
        JOIN metric_samples s ON s.resource_id = l.resource_id
                             AND s.metric_id = l.metric_id AND s.ts = l.ts
        JOIN metric_definitions m ON m.id = l.metric_id
        GROUP BY s.resource_id
        """
    )
    op.execute(
        """
        CREATE VIEW v_account_uptime_7d AS
        SELECT a.id AS account_id, a.owner_id,
               COALESCE(sum(u.up_samples), 0)::bigint AS up_samples,
               COALESCE(sum(u.total_samples), 0)::bigint AS total_samples,
               CASE WHEN COALESCE(sum(u.total_samples), 0) = 0 THEN NULL
                    ELSE 100.0 * sum(u.up_samples) / sum(u.total_samples) END AS uptime_percent
        FROM cloud_accounts a
        LEFT JOIN resources r ON r.account_id = a.id AND r.deleted_at IS NULL
        LEFT JOIN uptime_rollups u ON u.resource_id = r.id
                                  AND u.bucket_start >= now() - interval '7 days'
        WHERE a.deleted_at IS NULL
        GROUP BY a.id, a.owner_id
        """
    )
    op.execute(
        """
        CREATE VIEW v_open_alerts AS
        SELECT al.id, al.rule_id, al.resource_id, al.state, al.opened_at, al.value_at_open,
               ar.owner_id, ar.name AS rule_name, ar.severity, r.name AS resource_name
        FROM alerts al
        JOIN alert_rules ar ON ar.id = al.rule_id
        JOIN resources r ON r.id = al.resource_id
        WHERE al.state <> 'resolved'
        """
    )


def downgrade() -> None:
    for v in ("v_open_alerts", "v_account_uptime_7d", "v_resource_latest"):
        op.execute(f"DROP VIEW IF EXISTS {v}")
    op.execute("DROP FUNCTION IF EXISTS compute_uptime_rollup(timestamptz, timestamptz)")
    for t in AUDITED:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{t}_audit ON {t}")
    op.execute("DROP FUNCTION IF EXISTS write_audit()")
    for t in HAS_UPDATED_AT:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{t}_touch ON {t}")
    for t in SYNCED:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{t}_version ON {t}")
    op.execute("DROP FUNCTION IF EXISTS touch_updated_at()")
    op.execute("DROP FUNCTION IF EXISTS bump_version()")
    op.execute("DROP SEQUENCE IF EXISTS change_seq")
