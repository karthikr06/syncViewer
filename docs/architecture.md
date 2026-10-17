# Architecture

```
Browser (React PWA)
  ├─ Supabase Auth (login only)
  ├─ IndexedDB (Dexie, one DB per user): resources, accounts, rules, alerts, recommendations,
  │     digests, incidents, rollups, 24 h samples, sync cursors
  └─ HTTPS ──► API (FastAPI + SQLAlchemy) ──► Supabase Postgres (source of truth)
                  │                                  ▲
                  └─ Agent (Google ADK, read-only,   │
                     workspace-scoped tools)         │
Collector (local loop, or a scheduled Container Apps job) ┘
   └─ ProviderAdapter ──► MockAdapter ──► Generator (fake cloud)
                      └─► AzureAdapter (planned)
```

| Process | Code | Talks to |
|---|---|---|
| API | `backend/app/main.py` (`create_app`) | Postgres, Supabase JWKS, generator (account discovery), Gemini |
| Collector | `backend/app/collector/` | Postgres, provider adapter |
| Generator | `generator/syncgen/` | nothing (pure function of time) |
| Frontend | `frontend/` | API, Supabase Auth |

The API and collector never call each other; both read/write Postgres through the same repositories.

## Layering (backend)
`api/` (routers, dependencies) → `services/` (business logic) → `repositories/` (the only place
queries are built; everything workspace-scoped) → `models/` (SQLAlchemy). Raw SQL exists only in
Alembic migrations (triggers, procedure, views, lockdown). The stored procedure is called through
one helper, `repositories/samples.compute_rollup`.

## Auth and RBAC
- The browser logs in with Supabase Auth (Google OAuth or email/password; Supabase hashes passwords
  server-side with bcrypt).
- The API verifies the JWT on every request (JWKS for asymmetric keys, HS256 secret for legacy
  projects): signature, expiry, audience `authenticated`, issuer `<SUPABASE_URL>/auth/v1`.
- Data belongs to a **workspace** (a team). Each user belongs to exactly one workspace with one role,
  read from `users.role_id`, never from the token.
- First sign-in provisions the `users` row: if a pending `workspace_invites` row exists for the email,
  the user joins that workspace with the invited role (developer or viewer); otherwise a new workspace
  is created and the user is its admin.
- `admin`: everything, plus inviting members, changing their role and removing access.
  `developer`: everything except team management, including VM power actions. `viewer`: read-only,
  plus the AI assistant (whose tools are read-only anyway).
- `ADMIN_EMAILS` marks platform operators, who may see cross-workspace collector health; they get no
  access to other workspaces' data.
- Tenant isolation: every repository method takes the workspace id; another workspace's id is a 404.
- Enforced in three places: API dependencies (authoritative), frontend route guards, menu items.

## Delta sync
Server side, every synced table has `version bigint` set by a `BEFORE INSERT OR UPDATE` trigger from
the single sequence `change_seq`. Deletes are soft (`deleted_at`) so they travel as tombstones.

Client side, per entity the browser stores a cursor (the largest `version` seen) in `sync_state`:

1. Request `GET /sync/changes?entity=X&since=<cursor - 500>&limit=500` and page while `has_more`.
2. Upsert each row idempotently, **only if its `version` is not older than the local row's**.
3. Rows with `deleted_at` delete the local row (and, for resources/accounts, everything hanging off
   them: incidents, alerts, rollups, samples).

**Why the overlap:** sequence values are assigned at statement time but become visible at commit
time. A transaction that took version 100 may commit after one that took 101. A reader that has
seen 101 and then asks for `version > 101` would skip 100 forever. Re-reading the last 500 versions
plus idempotent, version-guarded upserts closes the gap.
`tests/test_db_schema.py::test_out_of_order_commit_needs_overlap` reproduces the race.

Metric samples are append-only: cursor is the newest `ts`; the client asks from `cursor - 10 min`
(inclusive), bootstraps only the last 24 h (every 15 min, four metrics) and prunes older rows.

## Offline-first browser
- The app shell is precached by the service worker (vite-plugin-pwa); API and auth calls are never
  cached by it.
- The UI renders straight from IndexedDB (`useLiveQuery`); syncing happens in the background: on
  load, on reconnect, on tab focus and every 30 s while visible, with exponential backoff.
- Search, filters and pagination for monitoring views run client-side against IndexedDB; admin lists
  are server-paginated.
- Writes need a network. They update the local row optimistically (or with the server's answer) and
  reconcile on the next sync; offline they show "You're offline...".
- supabase-js persists the session. A network failure while refreshing never logs the user out; only
  an explicit logout, a `SIGNED_OUT` event, or a definitive 401 after a refresh does. Logout deletes
  the user's IndexedDB database and all Cache Storage entries.
- Security: strict CSP on the static host (`public/staticwebapp.config.json`, `frontend/nginx.conf.template`), no
  `dangerouslySetInnerHTML`, agent markdown rendered with `react-markdown` + `rehype-sanitize`.

## Collector cycle
Per active account (own transaction and failure domain, small random jitter between accounts):
list resources and upsert (missing ones are tombstoned) -> fetch metrics since `last_collected_at`
(24 h backfill on first run, 15 min overlap) -> insert samples with `ON CONFLICT DO NOTHING` ->
`compute_uptime_rollup` for the touched window -> update incidents (>= 2 consecutive failed
availability samples) -> evaluate alert rules -> run recommendation rules -> set
`last_collected_at` or `last_error`. Afterwards: daily/weekly digests per workspace, raw-sample purge
(`RAW_RETENTION_DAYS`), and a `collector_runs` row. Uptime = share of samples with `availability == 1`.

## Agent
"Code computes, the LLM explains." Tools are plain Python functions (`agent/tools/impl.py`) that
take the workspace id from the authenticated request (ADK session state) and use the same workspace-scoped
repositories as the API. A coordinator delegates to an **analyst** (uptime, incidents, trends,
anomalies) and an **advisor** (rightsizing, reliability, capacity, waste). The only write is
`save_recommendation`. With no `GOOGLE_API_KEY` the chat endpoint answers "not configured" and
everything else keeps working. Each run is recorded in `agent_runs`.

## VM power actions
`POST /resources/{id}/actions` (admins and developers) calls the provider adapter's
`perform_action` (start, stop, restart, deallocate). Every attempt is stored in `vm_actions` (who,
from/to state, result); on success the resource's power state is updated at once, so its version
bumps and every member's browser sees it on the next sync. A recommendation with a direct fix
("stopped but not deallocated" -> deallocate) can be fixed in one click, which also marks it done;
waste advice also closes itself on the next collection once the VM is no longer stopped.
