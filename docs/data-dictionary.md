# Data dictionary

Authoritative definitions are the SQLAlchemy models in `backend/app/models/` and the migrations in `backend/alembic/versions/`. "Synced" tables carry `version bigint NOT NULL` (indexed), set by the `bump_version()` trigger from sequence `change_seq`.

| Table | Purpose | Key columns / constraints |
|---|---|---|
| roles | admin / developer / viewer | PK id; UNIQUE name; CHECK name |
| workspaces | A team; owns all monitored data | PK id; name |
| users | One row per Supabase user (id = auth user id), in one workspace | PK id; UNIQUE email; FK workspace_id (CASCADE); FK role_id (default 2 = developer); is_active |
| workspace_invites | Email invited into a workspace as developer or viewer | FK workspace_id (CASCADE), role_id, invited_by; CHECK role_id IN (2,3); CHECK email lower-case; partial UNIQUE(email) WHERE accepted_at IS NULL |
| providers | azure, aws, gcp, mock | UNIQUE code; is_enabled |
| cloud_accounts (synced) | A workspace's connected cloud account | FK workspace_id (CASCADE), provider_id; UNIQUE(workspace, provider, external_ref); CHECK status; credentials_encrypted is Fernet ciphertext, never returned/audited; soft delete |
| resource_types | e.g. `vm` per provider | UNIQUE(provider_id, code) |
| vm_actions | Power actions taken from SyncViewer | FK resource_id (CASCADE), requested_by (SET NULL); CHECK action, status |
| resources (synced) | Inventory (VMs) | FK account_id, type_id; UNIQUE(account_id, external_id); CHECK power_state, health_state; JSONB tags/attributes; soft delete |
| metric_definitions | availability, cpu_percent, memory_percent, disk_used_percent, network_in/out_bytes | UNIQUE code |
| metric_samples | Raw time series, append-only | PK(resource_id, metric_id, ts); index(resource_id, ts); purged after RAW_RETENTION_DAYS |
| uptime_rollups (synced) | Hourly summary (up/total samples, cpu avg/p95/max, memory avg, disk max) | PK(resource_id, bucket_start); CHECK up<=total |
| incidents (synced) | Outage / degraded periods | UNIQUE(resource_id, started_at, kind); ended_at NULL while open |
| alert_rules (synced) | Workspace thresholds | FK workspace_id; scope: account_id XOR resource_id (CHECK, both NULL = all of the workspace's resources); CHECK operator, severity; soft delete |
| alerts (synced) | Fired alerts | partial UNIQUE(rule_id, resource_id) WHERE state <> 'resolved'; CHECK state |
| recommendations (synced) | Rule/agent advice | CHECK category, severity, status, source; partial UNIQUE(workspace_id, dedupe_key) WHERE status='new' |
| insight_digests (synced) | Daily/weekly summaries | CHECK generated_by, period order |
| agent_runs | Agent audit (who asked, tools, tokens, duration) | FK user_id |
| collector_runs | One row per collection cycle | counts + error details |
| audit_log | Trigger-written change history for users, cloud_accounts, alert_rules, recommendations, workspace_invites | before/after JSONB (credentials stripped); actor from `app.user_id` setting if set |

## Database objects
- Sequence `change_seq`; trigger fn `bump_version()` (BEFORE INSERT/UPDATE on every synced table); `touch_updated_at()`.
- Trigger fn `write_audit()` on the four audited tables.
- Function `compute_uptime_rollup(from_ts, to_ts) -> int`: upserts hourly rollups for all buckets touched by the window.
- Views: `v_resource_latest`, `v_account_uptime_7d`, `v_open_alerts`.
- Lockdown migration: RLS enabled on every table; privileges revoked from `anon`/`authenticated` when those roles exist.

## Indexes
`version` on all synced tables; `workspace_id` on all workspace-owned tables; `account_id` on resources; `(resource_id, ts)` on metric_samples; partial unique indexes listed above.
