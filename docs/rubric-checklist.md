# Rubric checklist

Status: done = implemented and verified here; todo = needs your input or an external account.

## Documentation
| Item | Where | Status |
|---|---|---|
| Problem statement, objectives, scope, stack | `README.md` | done |
| Team table | `README.md` | todo (fill in names) |
| Deliverables | `README.md`, this file | done |
| Gantt chart | `docs/gantt.md` | done (adjust dates) |
| ER diagram (Mermaid; PNG export optional) | `docs/er-diagram.md` | done |
| Relational schema, keys, constraints, 3NF, indexes | `docs/data-dictionary.md`, `docs/er-diagram.md` | done |

## Database
| Item | Where | Status |
|---|---|---|
| 17 tables (>= 8), 4+ primary entities, 3+ relationships | `backend/app/models/`, `alembic/versions/0001_tables.py` | done |
| Triggers (version bump, updated_at, audit) | `alembic/versions/0002_db_objects.py` | done |
| Stored procedure/function | `compute_uptime_rollup` in `0002`; wrapper `repositories/samples.py` | done |
| Views | `v_resource_latest`, `v_account_uptime_7d`, `v_open_alerts` in `0002` | done |
| Joins / aggregates | `repositories/owned.py`, `repositories/insights.py` | done |
| Transactions | per-request commit/rollback (`api/deps.get_db`), per-account collector transaction, account+discovery in `api/accounts.py` | done |
| ORM everywhere | all of `backend/app/` (raw SQL only in migrations) | done |
| Indexes, constraints (NOT NULL/UNIQUE/CHECK/DEFAULT, partial uniques) | models + `docs/data-dictionary.md` | done |
| Backup and recovery (`pg_dump`/`pg_restore`) | `scripts/backup.sh`, `scripts/restore.sh`, README | done (verified on a local Postgres) |

## Application
| Item | Where | Status |
|---|---|---|
| Responsive UI, dashboard, CRUD, search, filter, pagination | `frontend/src/pages/` | done |
| Form validation, error handling | zod + react-hook-form, `ErrorBoundary`, `friendlyError` | done |
| Login, logout, user info | `frontend/src/pages/Login.tsx`, `components/Layout.tsx` | done (needs Supabase project) |
| Auth + RBAC (single `users` table, 3 roles; menus/pages/API) | `api/deps.py`, `App.tsx`, `Layout.tsx` | done |
| Password hashing story | Supabase Auth (bcrypt, server-side) | done (state in report) |
| SQL-injection prevention | ORM only, bound parameters, `icontains(autoescape=True)` | done |
| Secrets in `.env` | `.env`, `.env.example`, `.gitignore` | done |
| Offline-first PWA | `frontend/src/lib/sync.ts`, `db.ts`, vite-plugin-pwa | done |
| AI agent + evals | `backend/app/agent/`, `tests/test_agent_evals.py` | done (chat needs `GOOGLE_API_KEY`) |

## Delivery
| Item | Where | Status |
|---|---|---|
| Git: `main` + `dev`, feature branches, 10+ commits | `git log --graph --all` | done |
| Private GitHub repo, collaborators, PRs | GitHub | todo (`gh repo create --private`) |
| Docker for every service | `*/Dockerfile`, `docker-compose.yml` | done (compose verified with local Postgres) |
| Images on Docker Hub | `.github/workflows/ci.yml` (`publish` job) | todo (add `DOCKERHUB_*` secrets) |
| Cloud deployment with live URL | `docs/deployment.md`, `render.yaml` | todo (needs accounts) |
| GitHub Actions CI/CD | `.github/workflows/ci.yml` | done (runs on first push) |
| Custom domain | `docs/deployment.md` (DuckDNS + Caddy) | optional |
| Extra best practice | audit log trigger, automated tests, managed Supabase DB | done |
