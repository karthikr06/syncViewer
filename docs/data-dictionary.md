# Data dictionary

Authoritative definitions are the SQLAlchemy models in `backend/app/models/` and the migrations in `backend/alembic/versions/`. "Synced" tables carry `version bigint NOT NULL` (indexed), set by the `bump_version()` trigger from sequence `change_seq`.

| Table | Purpose | Key columns / constraints |
|---|---|---|
| roles | admin / user / viewer | PK id; UNIQUE name; CHECK name |
| users | One row per Supabase user (id = auth user id) | PK id; UNIQUE email; FK role_id (default 2 = user); is_active |
| providers | azure, aws, gcp, mock | UNIQUE code; is_enabled |
| cloud_accounts (synced) | A user's connected cloud account | FK owner_id (CASCADE), provider_id; UNIQUE(owner, provider, external_ref); CHECK status; credentials_encrypted is Fernet ciphertext, never returned/audited; soft delete |
| resource_types | e.g. `vm` per provider | UNIQUE(provider_id, code) |
| resources (synced) | Inventory (VMs) | FK account_id, type_id; UNIQUE(account_id, external_id); CHECK power_state, health_state; JSONB tags/attributes; soft delete |
| metric_definitions | availability, cpu_percent, memory_percent, disk_used_percent, network_in/out_bytes | UNIQUE code |
| metric_samples | Raw time series, append-only | PK(resource_id, metric_id, ts); index(resource_id, ts); purged after RAW_RETENTION_DAYS |
| uptime_rollups (synced) | Hourly summary (up/total samples, cpu avg/p95/max, memory avg, disk max) | PK(resource_id, bucket_start); CHECK up<=total |
| incidents (synced) | Outage / degraded periods | UNIQUE(resource_id, started_at, kind); ended_at NULL while open |
| alert_rules (synced) | User-defined thresholds | scope: account_id XOR resource_id (CHECK, both NULL = all of owner's resources); CHECK operator, severity; soft delete |
| alerts (synced) | Fired alerts | partial UNIQUE(rule_id, resource_id) WHERE state <> 'resolved'; CHECK state |
| recommendations (synced) | Rule/agent advice | CHECK category, severity, status, source; partial UNIQUE(owner_id, dedupe_key) WHERE status='new' |
| insight_digests (synced) | Daily/weekly summaries | CHECK generated_by, period order |
| agent_runs | Agent audit (tools, tokens, duration) | FK owner_id |
| collector_runs | One row per collection cycle | counts + error details |
| audit_log | Trigger-written change history for users, cloud_accounts, alert_rules, recommendations | before/after JSONB (credentials stripped); actor from `app.user_id` setting if set |

## Database objects
- Sequence `change_seq`; trigger fn `bump_version()` (BEFORE INSERT/UPDATE on every synced table); `touch_updated_at()`.
- Trigger fn `write_audit()` on the four audited tables.
- Function `compute_uptime_rollup(from_ts, to_ts) -> int`: upserts hourly rollups for all buckets touched by the window.
- Views: `v_resource_latest`, `v_account_uptime_7d`, `v_open_alerts`.
- Lockdown migration: RLS enabled on every table; privileges revoked from `anon`/`authenticated` when those roles exist.

## Indexes
`version` on all synced tables; `owner_id` on all owner-FK tables; `account_id` on resources; `(resource_id, ts)` on metric_samples; partial unique indexes listed above.
