# ER diagram

Crow's-foot diagram (renders on GitHub). A Chen-notation version is in [SyncViewer_ER_Diagram.png](SyncViewer_ER_Diagram.png).

```mermaid
erDiagram
    roles ||--o{ users : "has"
    workspaces ||--o{ users : "has members"
    workspaces ||--o{ workspace_invites : "issues"
    workspaces ||--o{ cloud_accounts : "owns"
    providers ||--o{ cloud_accounts : "type of"
    providers ||--o{ resource_types : "defines"
    cloud_accounts ||--o{ resources : "contains"
    resource_types ||--o{ resources : "classifies"
    resources ||--o{ metric_samples : "emits"
    metric_definitions ||--o{ metric_samples : "measured as"
    resources ||--o{ uptime_rollups : "summarised by"
    resources ||--o{ incidents : "suffers"
    workspaces ||--o{ alert_rules : "defines"
    metric_definitions ||--o{ alert_rules : "watches"
    cloud_accounts |o--o{ alert_rules : "scopes"
    resources |o--o{ alert_rules : "scopes"
    alert_rules ||--o{ alerts : "raises"
    resources ||--o{ alerts : "subject of"
    workspaces ||--o{ recommendations : "receives"
    resources |o--o{ recommendations : "about"
    workspaces ||--o{ insight_digests : "receives"
    resources ||--o{ vm_actions : "acted on"
    users |o--o{ vm_actions : "requests"
    users ||--o{ agent_runs : "triggers"

    roles { smallint id PK
            text name UK }
    workspaces { uuid id PK
                 text name }
    workspace_invites { bigint id PK
                        uuid workspace_id FK
                        text email
                        smallint role_id FK
                        timestamptz accepted_at }
    vm_actions { bigint id PK
                 uuid resource_id FK
                 uuid requested_by FK
                 text action
                 text status }
    users { uuid id PK
            text email UK
            uuid workspace_id FK
            smallint role_id FK
            bool is_active
            timestamptz created_at
            timestamptz last_login_at }
    providers { smallint id PK
                text code UK
                text name
                bool is_enabled }
    cloud_accounts { uuid id PK
                     uuid workspace_id FK
                     smallint provider_id FK
                     text name
                     text external_ref
                     jsonb config
                     bytea credentials_encrypted
                     text status
                     timestamptz last_collected_at
                     text last_error
                     timestamptz deleted_at
                     bigint version }
    resource_types { smallint id PK
                     smallint provider_id FK
                     text code }
    resources { uuid id PK
                uuid account_id FK
                smallint type_id FK
                text external_id
                text name
                text region
                text size_sku
                text power_state
                text health_state
                jsonb tags
                jsonb attributes
                timestamptz deleted_at
                bigint version }
    metric_definitions { smallint id PK
                         text code UK
                         text unit }
    metric_samples { uuid resource_id PK
                     smallint metric_id PK
                     timestamptz ts PK
                     double value }
    uptime_rollups { uuid resource_id PK
                     timestamptz bucket_start PK
                     int up_samples
                     int total_samples
                     double avg_cpu
                     double p95_cpu
                     bigint version }
    incidents { bigint id PK
                uuid resource_id FK
                timestamptz started_at
                timestamptz ended_at
                text kind
                bigint version }
    alert_rules { uuid id PK
                  uuid workspace_id FK
                  uuid account_id FK
                  uuid resource_id FK
                  smallint metric_id FK
                  text operator
                  double threshold
                  int duration_minutes
                  text severity
                  bigint version }
    alerts { bigint id PK
             uuid rule_id FK
             uuid resource_id FK
             text state
             timestamptz opened_at
             timestamptz resolved_at
             bigint version }
    recommendations { bigint id PK
                      uuid workspace_id FK
                      uuid resource_id FK
                      text category
                      text severity
                      text status
                      text source
                      text dedupe_key
                      jsonb evidence
                      bigint version }
    insight_digests { bigint id PK
                      uuid workspace_id FK
                      timestamptz period_start
                      timestamptz period_end
                      text summary_md
                      text generated_by
                      bigint version }
    agent_runs { bigint id PK
                 uuid user_id FK
                 text trigger
                 jsonb tools_called
                 text status }
    collector_runs { bigint id PK
                     timestamptz started_at
                     int accounts_processed
                     int samples_inserted
                     int errors }
    audit_log { bigint id PK
                uuid actor_id
                text action
                text entity
                text entity_id
                jsonb before
                jsonb after }
```

`audit_log` and `collector_runs` have no foreign keys by design: they must survive deletion of the rows they describe.

## Normalization (3NF)
- Every table has a single-attribute or minimal composite primary key; non-key columns depend on the whole key and nothing else.
- Roles, providers, resource types and metric definitions are separate lookup tables, so names/units are stored once (no transitive dependency such as `resource -> provider name`).
- Ownership is stored once, on `cloud_accounts.workspace_id`. Resources, alerts and incidents reach their owner through joins instead of duplicating `workspace_id` (which would create a transitive dependency).
- `uptime_rollups` is deliberately a derived (denormalized) summary table for read performance; it is regenerable from `metric_samples` by `compute_uptime_rollup`.
- JSONB columns (`tags`, `attributes`, `config`, `evidence`) hold provider-specific, schema-less data that is never joined or filtered relationally.
