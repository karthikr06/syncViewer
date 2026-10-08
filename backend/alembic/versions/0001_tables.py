"""baseline: 17 tables

Frozen DDL, generated once from the SQLAlchemy models as they were at this revision. Later schema
changes are separate migrations, so a fresh database always replays the same history.
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = ['audit_log', 'collector_runs', 'metric_definitions', 'providers', 'roles', 'resource_types', 'users', 'agent_runs', 'cloud_accounts', 'insight_digests', 'resources', 'alert_rules', 'incidents', 'metric_samples', 'recommendations', 'uptime_rollups', 'alerts']

DDL = [
    """
CREATE TABLE metric_definitions (
    id SMALLSERIAL NOT NULL,
    code VARCHAR(40) NOT NULL,
    unit VARCHAR(20) NOT NULL,
    CONSTRAINT pk_metric_definitions PRIMARY KEY (id),
    CONSTRAINT uq_metric_definitions_code UNIQUE (code)
)
    """,
    """
CREATE TABLE roles (
    id SMALLSERIAL NOT NULL,
    name VARCHAR(20) NOT NULL,
    CONSTRAINT pk_roles PRIMARY KEY (id),
    CONSTRAINT ck_roles_name_valid CHECK (name IN ('admin','user','viewer')),
    CONSTRAINT uq_roles_name UNIQUE (name)
)
    """,
    """
CREATE TABLE providers (
    id SMALLSERIAL NOT NULL,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(80) NOT NULL,
    is_enabled BOOLEAN DEFAULT 'true' NOT NULL,
    CONSTRAINT pk_providers PRIMARY KEY (id),
    CONSTRAINT ck_providers_code_valid CHECK (code IN ('azure','aws','gcp','mock')),
    CONSTRAINT uq_providers_code UNIQUE (code)
)
    """,
    """
CREATE TABLE collector_runs (
    id BIGSERIAL NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    accounts_processed INTEGER DEFAULT '0' NOT NULL,
    samples_inserted INTEGER DEFAULT '0' NOT NULL,
    errors INTEGER DEFAULT '0' NOT NULL,
    error_details JSONB,
    CONSTRAINT pk_collector_runs PRIMARY KEY (id)
)
    """,
    """
CREATE TABLE audit_log (
    id BIGSERIAL NOT NULL,
    actor_id UUID,
    action VARCHAR(10) NOT NULL,
    entity VARCHAR(60) NOT NULL,
    entity_id VARCHAR(80) NOT NULL,
    before JSONB,
    after JSONB,
    at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_audit_log PRIMARY KEY (id)
)
    """,
    """
CREATE TABLE users (
    id UUID NOT NULL,
    email VARCHAR(320) NOT NULL,
    role_id SMALLINT DEFAULT '2' NOT NULL,
    is_active BOOLEAN DEFAULT 'true' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    last_login_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT fk_users_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id)
)
    """,
    """
CREATE INDEX ix_users_role_id ON users (role_id)
    """,
    """
CREATE TABLE resource_types (
    id SMALLSERIAL NOT NULL,
    provider_id SMALLINT NOT NULL,
    code VARCHAR(40) NOT NULL,
    CONSTRAINT pk_resource_types PRIMARY KEY (id),
    CONSTRAINT uq_resource_types_code UNIQUE (provider_id, code),
    CONSTRAINT fk_resource_types_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id)
)
    """,
    """
CREATE TABLE cloud_accounts (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    owner_id UUID NOT NULL,
    provider_id SMALLINT NOT NULL,
    name VARCHAR(120) NOT NULL,
    external_ref VARCHAR(200) NOT NULL,
    config JSONB DEFAULT '{}' NOT NULL,
    credentials_encrypted BYTEA,
    status VARCHAR(10) DEFAULT 'active' NOT NULL,
    last_collected_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    deleted_at TIMESTAMP WITH TIME ZONE,
    version BIGINT DEFAULT '0' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_cloud_accounts PRIMARY KEY (id),
    CONSTRAINT ck_cloud_accounts_status_valid CHECK (status IN ('active','paused','error')),
    CONSTRAINT uq_cloud_accounts_ref UNIQUE (owner_id, provider_id, external_ref),
    CONSTRAINT fk_cloud_accounts_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_cloud_accounts_provider_id_providers FOREIGN KEY(provider_id) REFERENCES providers (id)
)
    """,
    """
CREATE INDEX ix_cloud_accounts_owner_id ON cloud_accounts (owner_id)
    """,
    """
CREATE INDEX ix_cloud_accounts_version ON cloud_accounts (version)
    """,
    """
CREATE TABLE insight_digests (
    id BIGSERIAL NOT NULL,
    owner_id UUID NOT NULL,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    summary_md TEXT NOT NULL,
    generated_by VARCHAR(10) DEFAULT 'rules' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    version BIGINT DEFAULT '0' NOT NULL,
    CONSTRAINT pk_insight_digests PRIMARY KEY (id),
    CONSTRAINT ck_insight_digests_generated_by_valid CHECK (generated_by IN ('rules','agent')),
    CONSTRAINT ck_insight_digests_period_ordered CHECK (period_end >= period_start),
    CONSTRAINT fk_insight_digests_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
)
    """,
    """
CREATE INDEX ix_insight_digests_owner_id ON insight_digests (owner_id)
    """,
    """
CREATE INDEX ix_insight_digests_version ON insight_digests (version)
    """,
    """
CREATE TABLE agent_runs (
    id BIGSERIAL NOT NULL,
    owner_id UUID NOT NULL,
    trigger VARCHAR(40) NOT NULL,
    tools_called JSONB DEFAULT '[]' NOT NULL,
    model VARCHAR(80),
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,
    status VARCHAR(20) DEFAULT 'ok' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_agent_runs PRIMARY KEY (id),
    CONSTRAINT fk_agent_runs_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
)
    """,
    """
CREATE INDEX ix_agent_runs_owner_id ON agent_runs (owner_id)
    """,
    """
CREATE TABLE resources (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    account_id UUID NOT NULL,
    type_id SMALLINT NOT NULL,
    external_id VARCHAR(300) NOT NULL,
    name VARCHAR(200) NOT NULL,
    region VARCHAR(60),
    size_sku VARCHAR(80),
    power_state VARCHAR(15) DEFAULT 'unknown' NOT NULL,
    health_state VARCHAR(15) DEFAULT 'unknown' NOT NULL,
    tags JSONB DEFAULT '{}' NOT NULL,
    attributes JSONB DEFAULT '{}' NOT NULL,
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    version BIGINT DEFAULT '0' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_resources PRIMARY KEY (id),
    CONSTRAINT ck_resources_power_valid CHECK (power_state IN ('running','stopped','deallocated','unknown')),
    CONSTRAINT ck_resources_health_valid CHECK (health_state IN ('healthy','degraded','unavailable','unknown')),
    CONSTRAINT uq_resources_external UNIQUE (account_id, external_id),
    CONSTRAINT fk_resources_account_id_cloud_accounts FOREIGN KEY(account_id) REFERENCES cloud_accounts (id) ON DELETE CASCADE,
    CONSTRAINT fk_resources_type_id_resource_types FOREIGN KEY(type_id) REFERENCES resource_types (id)
)
    """,
    """
CREATE INDEX ix_resources_account_id ON resources (account_id)
    """,
    """
CREATE INDEX ix_resources_version ON resources (version)
    """,
    """
CREATE TABLE metric_samples (
    resource_id UUID NOT NULL,
    metric_id SMALLINT NOT NULL,
    ts TIMESTAMP WITH TIME ZONE NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_metric_samples PRIMARY KEY (resource_id, metric_id, ts),
    CONSTRAINT fk_metric_samples_resource_id_resources FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE,
    CONSTRAINT fk_metric_samples_metric_id_metric_definitions FOREIGN KEY(metric_id) REFERENCES metric_definitions (id)
)
    """,
    """
CREATE INDEX ix_metric_samples_resource_ts ON metric_samples (resource_id, ts)
    """,
    """
CREATE TABLE uptime_rollups (
    resource_id UUID NOT NULL,
    bucket_start TIMESTAMP WITH TIME ZONE NOT NULL,
    up_samples INTEGER NOT NULL,
    total_samples INTEGER NOT NULL,
    avg_cpu DOUBLE PRECISION,
    p95_cpu DOUBLE PRECISION,
    max_cpu DOUBLE PRECISION,
    avg_memory DOUBLE PRECISION,
    max_disk DOUBLE PRECISION,
    version BIGINT DEFAULT '0' NOT NULL,
    CONSTRAINT pk_uptime_rollups PRIMARY KEY (resource_id, bucket_start),
    CONSTRAINT ck_uptime_rollups_up_le_total CHECK (up_samples <= total_samples),
    CONSTRAINT fk_uptime_rollups_resource_id_resources FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE
)
    """,
    """
CREATE INDEX ix_uptime_rollups_version ON uptime_rollups (version)
    """,
    """
CREATE TABLE incidents (
    id BIGSERIAL NOT NULL,
    resource_id UUID NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    kind VARCHAR(10) DEFAULT 'outage' NOT NULL,
    version BIGINT DEFAULT '0' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_incidents PRIMARY KEY (id),
    CONSTRAINT ck_incidents_kind_valid CHECK (kind IN ('outage','degraded')),
    CONSTRAINT uq_incidents_start UNIQUE (resource_id, started_at, kind),
    CONSTRAINT fk_incidents_resource_id_resources FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE
)
    """,
    """
CREATE INDEX ix_incidents_resource_id ON incidents (resource_id)
    """,
    """
CREATE INDEX ix_incidents_version ON incidents (version)
    """,
    """
CREATE TABLE alert_rules (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    owner_id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    account_id UUID,
    resource_id UUID,
    metric_id SMALLINT NOT NULL,
    operator VARCHAR(2) NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    duration_minutes INTEGER DEFAULT '0' NOT NULL,
    severity VARCHAR(10) DEFAULT 'warning' NOT NULL,
    is_enabled BOOLEAN DEFAULT 'true' NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    version BIGINT DEFAULT '0' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_alert_rules PRIMARY KEY (id),
    CONSTRAINT ck_alert_rules_operator_valid CHECK (operator IN ('>','>=','<','<=')),
    CONSTRAINT ck_alert_rules_severity_valid CHECK (severity IN ('info','warning','critical')),
    CONSTRAINT ck_alert_rules_single_scope CHECK (NOT (account_id IS NOT NULL AND resource_id IS NOT NULL)),
    CONSTRAINT ck_alert_rules_duration_nonneg CHECK (duration_minutes >= 0),
    CONSTRAINT fk_alert_rules_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_alert_rules_account_id_cloud_accounts FOREIGN KEY(account_id) REFERENCES cloud_accounts (id) ON DELETE CASCADE,
    CONSTRAINT fk_alert_rules_resource_id_resources FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE,
    CONSTRAINT fk_alert_rules_metric_id_metric_definitions FOREIGN KEY(metric_id) REFERENCES metric_definitions (id)
)
    """,
    """
CREATE INDEX ix_alert_rules_account_id ON alert_rules (account_id)
    """,
    """
CREATE INDEX ix_alert_rules_resource_id ON alert_rules (resource_id)
    """,
    """
CREATE INDEX ix_alert_rules_owner_id ON alert_rules (owner_id)
    """,
    """
CREATE INDEX ix_alert_rules_version ON alert_rules (version)
    """,
    """
CREATE TABLE recommendations (
    id BIGSERIAL NOT NULL,
    owner_id UUID NOT NULL,
    resource_id UUID,
    category VARCHAR(15) NOT NULL,
    severity VARCHAR(10) DEFAULT 'info' NOT NULL,
    title VARCHAR(200) NOT NULL,
    detail TEXT DEFAULT '' NOT NULL,
    evidence JSONB DEFAULT '{}' NOT NULL,
    status VARCHAR(10) DEFAULT 'new' NOT NULL,
    source VARCHAR(10) DEFAULT 'rule' NOT NULL,
    dedupe_key VARCHAR(200) NOT NULL,
    version BIGINT DEFAULT '0' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_recommendations PRIMARY KEY (id),
    CONSTRAINT ck_recommendations_category_valid CHECK (category IN ('rightsizing','reliability','capacity','waste','pattern')),
    CONSTRAINT ck_recommendations_severity_valid CHECK (severity IN ('info','warning','critical')),
    CONSTRAINT ck_recommendations_status_valid CHECK (status IN ('new','dismissed','done')),
    CONSTRAINT ck_recommendations_source_valid CHECK (source IN ('rule','agent')),
    CONSTRAINT fk_recommendations_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_recommendations_resource_id_resources FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE
)
    """,
    """
CREATE INDEX ix_recommendations_resource_id ON recommendations (resource_id)
    """,
    """
CREATE INDEX ix_recommendations_version ON recommendations (version)
    """,
    """
CREATE INDEX ix_recommendations_owner_id ON recommendations (owner_id)
    """,
    """
CREATE UNIQUE INDEX uq_recommendations_open_dedupe ON recommendations (owner_id, dedupe_key) WHERE status = 'new'
    """,
    """
CREATE TABLE alerts (
    id BIGSERIAL NOT NULL,
    rule_id UUID NOT NULL,
    resource_id UUID NOT NULL,
    state VARCHAR(15) DEFAULT 'open' NOT NULL,
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,
    value_at_open DOUBLE PRECISION,
    version BIGINT DEFAULT '0' NOT NULL,
    CONSTRAINT pk_alerts PRIMARY KEY (id),
    CONSTRAINT ck_alerts_state_valid CHECK (state IN ('open','acknowledged','resolved')),
    CONSTRAINT fk_alerts_rule_id_alert_rules FOREIGN KEY(rule_id) REFERENCES alert_rules (id) ON DELETE CASCADE,
    CONSTRAINT fk_alerts_resource_id_resources FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE
)
    """,
    """
CREATE INDEX ix_alerts_version ON alerts (version)
    """,
    """
CREATE UNIQUE INDEX uq_alerts_active ON alerts (rule_id, resource_id) WHERE state <> 'resolved'
    """,
    """
CREATE INDEX ix_alerts_rule_id ON alerts (rule_id)
    """,
    """
CREATE INDEX ix_alerts_resource_id ON alerts (resource_id)
    """
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
