# Decisions

## Tooling and tests
- **Python 3.13 locally, 3.12 in Docker.** `requires-python >=3.12`.
- **pg_dump/pg_restore** run from a local install if present, otherwise from the `postgres:17-alpine` Docker image.
- **Tests use `pgembed` (embedded PostgreSQL 17)** so tests and CI need no Docker or database server.
- **Tests are hermetic**: `conftest.py` blanks `GENERATOR_API_KEY`, `GOOGLE_API_KEY` etc. so a developer's `.env` never leaks into test runs.
- **Backups via Git Bash/Docker**: `scripts/*.sh` set `MSYS_NO_PATHCONV=1` for Windows.
- **Dependencies are locked** (`uv.lock`) and installed exactly in Docker and CI.

## Database
- **Alert rule scope:** both `account_id` and `resource_id` NULL means "all of the workspace's resources"; at most one may be set.
- **Alerts/incidents have no `workspace_id`**; ownership is derived by join (3NF).
- **Rollup bounds:** `compute_uptime_rollup` recomputes whole hourly buckets from raw samples, so it is idempotent; raw purge never touches rollups.
- **Migration 0005 keeps existing data in place:** each existing user becomes admin of a workspace whose id equals their user id, so the old `owner_id` values are already valid workspace ids (column renamed and re-pointed, no rows rewritten).
- **Migration 0001 is frozen DDL**, so replaying the history never depends on the current models; 0004 uses a fixed table list.
- **Sync pages use the global `version`** (not per-table), clients re-read `cursor - 500`; samples are thinned to 15-minute points and limited to cpu/memory/disk/availability for the browser cache.

## Demo cloud and collector
- **Generator package is `syncgen/`** (not `app/`) so backend tests can import it in-process without a name clash.
- **Small scenario has one idle VM**; medium/large add more idle VMs, a flaky VM (same-hour daily outage) and repeats. Stopped VMs emit no metrics; an unresponsive VM is `running` with availability 0.
- **Large demo scenario is for load testing only**: 300 VMs is about 520k samples a day, more than Supabase's free 500 MB over the 14-day retention.
- **Incidents need 2 consecutive failed samples** (`MIN_FAILED_SAMPLES`); a single failed probe is noise. Stopped VMs never get incidents.
- **Rules run on hourly rollups**, not raw rows: rightsizing needs >=18 hourly buckets (the 24 h first-run backfill yields ~25); capacity trend fits only the data after the last disk cleanup.
- **Recommendation lifecycle:** open recs are deduped by `dedupe_key`; dismissed/done ones are not re-raised for 7 days; rules never auto-close a rec.
- **Collector `serve` runs one cycle at start**, then every `COLLECT_INTERVAL_SECONDS` (max 1 instance, coalesced).
- **Account creation = account + first discovery in one transaction**; if the provider can't be reached, nothing is saved (502). Metrics arrive via collect-now or the next collector cycle.
- **Deleting an account soft-deletes its resources too** so tombstones reach every client; the client cascades to incidents, alerts, rollups and samples.
- **Digests are deterministic** (no LLM narrative).

## Teams, roles and actions
- **Teams are workspaces.** All monitored data belongs to a workspace; a user belongs to one workspace with one role (admin, developer, viewer). A first sign-up creates a workspace with that person as admin; an admin's invite by email makes the next sign-up with that email a developer or viewer there. One workspace per user keeps scoping simple; joining a second team needs a separate account.
- **Viewers are read-only.** Writer roles (admin, developer) pass `require_writer`; viewers get 403 on writes.
- **`ADMIN_EMAILS` lists platform operators**, who see collector health across workspaces. Workspace admins are whoever created the workspace.
- **VM power actions go through the provider adapter** and are recorded in `vm_actions`; the generator keeps an in-memory action log so demo VMs really change state and metrics. The AI assistant stays read-only (it cannot take VM actions).
- **One-click fixes:** only advice with a single safe, reversible action gets a fix button (stopped-but-billed -> deallocate). Waste advice closes itself when the VM is no longer stopped; the re-raise cooldown applies to dismissed advice only, so a fixed problem that comes back is reported again.

## Prometheus
- **One read-only adapter instead of one per cloud for monitoring:** Prometheus already discovers VMs in Azure, AWS and GCP (or receives them from OpenTelemetry Collectors), so `PrometheusAdapter` covers all three for inventory and metrics. VM actions would still need a cloud API.
- **Two presets, node_exporter by default:** scraping gives a real `up` signal; OpenTelemetry pushes work behind firewalls but a quiet VM can only be read as "down". OTel inventory is the VMs that sent data in the last 7 days, and the newest 2 minutes are not read so late data never becomes a stored 0.
- **An empty target list is an error, not "all VMs deleted":** a wrong job or a Prometheus outage would otherwise tombstone every VM.
- **One range query per metric for the whole account** (5-minute steps), so a collection costs six requests however many VMs there are.
- **Disk is measured like `df`** (root-reserved blocks count as neither used nor free) and OTel memory leaves out the overlapping `slab_*` states; both checked against node_exporter on the same machine.
- **URL guard:** the API calls a URL that users type in, so outside development it must be HTTPS and resolve to a public address (no `169.254.169.254` metadata service, no private networks); no redirects; responses capped at 20 MB. `ALLOW_PRIVATE_URLS` turns the address check off for local Prometheus servers.
- **No power state from Prometheus by default:** a VM that does not answer is "running" and unavailable, so it gets incidents. A `power_state` target label (from cloud discovery) overrides it; stopped AWS/GCP instances map to "deallocated" because they are not billed for compute.

## API and AI assistant
- **App factory:** `uvicorn app.main:create_app --factory`, so tests build the app with explicit settings/session factory/adapters.
- **In-memory rate limiting** (per process, per user): fine for a single API instance; use a shared store if the API is scaled out.
- **Chat authenticates in its own short transaction** (`current_user_detached`) so no pooled connection (a real server connection behind Supabase's transaction pooler) is held while the model thinks; tools open short sessions of their own.
- **ADK runs on one long-lived event loop** in a daemon thread (`agent/runner.py`): google-genai keeps async HTTP clients bound to the loop that created them, so `asyncio.run` per request breaks the second chat. Chat turns time out after 120 s; 429/503 from Gemini become a friendly "busy" reply.
- **Discovery agent tools**: `list_resources` (the model must discover ids/names) and `get_fleet_uptime` (answers "most downtime" without N calls). All tools accept id or exact name and are workspace-scoped.
- **Fleet-wide agent tools** `compare_metric` and `forecast_fleet_disk` answer "which VM…" questions in one call instead of one call per VM (the model otherwise loops `get_metric_stats` 25 times and hits free-tier rate limits).
- **The agent's only write (`save_recommendation`) checks the caller's role** from session state, so viewers stay read-only through chat too.
- **Model-in-the-loop eval questions name VMs** (`{leak}`, `{idle}` placeholders) where a real user would; questions about "which VM" accept any VM with that role.
- **Default model `gemini-3.5-flash-lite`** for the larger free quota.

## Frontend
- **Sync runs once at start-up and on every explicit "sync now" even in a hidden tab**; only the periodic loop pauses while hidden. `applyRows` batches into one transaction (`bulkGet`/`bulkPut`).
- **Signing in deletes other users' local databases** on that device (covers sessions that expired instead of signing out).
- **Google sign-in is hidden** until `VITE_ENABLE_GOOGLE_AUTH=true`. Email reset uses Supabase's `resetPasswordForEmail` and lands on `/account/password`.
- **Theme:** semantic colour tokens (CSS variables, WCAG AA text contrast) with a light/dark/system switch; the pre-paint theme script is a static file because the CSP forbids inline scripts.
- **VM names in recommendations, AI answers and digests are links** to the VM's page (whole-name matching; code spans and fenced code are left alone except an inline code span that is exactly a VM name).

## Hosting
- **Hosting on Azure, one container** (Azure for Students: credit-limited, so nothing can be billed): the API runs with the demo cloud mounted at `/gen` (`app/combined.py`) as a single Container App in Central India, next to the Supabase database; it scales to zero with at most one replica, and Log Analytics is off. The website is on Static Web Apps (free).
- **Hourly collection through a free GitHub Actions schedule** calling `POST /api/v1/internal/collect` (token-protected), which starts the cycle in a background thread and answers 202. Cheaper than a Container Apps job, and the environment Azure created ("express") does not support jobs. After a long pause a cycle catches up on the last 24 hours only, so it always finishes within the minutes the app stays awake.
