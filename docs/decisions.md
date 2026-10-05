# Decisions

- **Python 3.13 locally, 3.12 in Docker.** `requires-python >=3.12`. Verify dependency wheels (psycopg, google-adk) on 3.13 in Phase 0.
- **pg_dump/pg_restore via Docker.** No local PostgreSQL install; backup scripts run the native tools in a `postgres:16` container.
- **Tests use `pgembed` (embedded PostgreSQL 17)** because Docker is not installed on the dev machine; CI will use the same. It also ships `pg_dump`/`pg_restore`.
- **Migration 0001 uses `Base.metadata.create_all`** to create the 17 tables from the models; triggers, procedure, views, seed and lockdown are explicit raw-SQL migrations 0002-0004.
- **Alert rule scope:** both `account_id` and `resource_id` NULL means "all of the owner's resources"; at most one may be set.
- **Alerts/incidents have no `owner_id`**; ownership is derived by join (3NF).
- **ER PNG export deferred** (needs Node/mermaid-cli); Mermaid source is in `docs/er-diagram.md`.
- **Generator package is `syncgen/`** (not `app/`) so backend tests can import it in-process without a name clash.
- **Small scenario has one idle VM**; medium/large add more idle VMs, a flaky VM (same-hour daily outage) and repeats. Stopped VMs emit no metrics; an unresponsive VM is `running` with availability 0.
- **Incidents need 2 consecutive failed samples** (`MIN_FAILED_SAMPLES`); a single failed probe is noise. Stopped VMs never get incidents.
- **Rules run on hourly rollups**, not raw rows: rightsizing needs >=18 hourly buckets (the 24 h first-run backfill yields ~25); capacity trend fits only the data after the last disk cleanup.
- **Recommendation lifecycle:** open recs are deduped by `dedupe_key`; dismissed/done ones are not re-raised for 7 days; rules never auto-close a rec.
- **Rollup bounds:** `compute_uptime_rollup` recomputes whole hourly buckets from raw samples, so it is idempotent; raw purge never touches rollups.
- **Collector `serve` runs one cycle at start**, then every `COLLECT_INTERVAL_SECONDS` (max 1 instance, coalesced).
- **Phase-by-phase delivery**, pausing after each phase for review.
