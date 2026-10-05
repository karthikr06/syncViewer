# SyncViewer

A multi-cloud VM monitor (BCSE307L Database Systems, VIT). Add cloud accounts and see every VM in one
place: inventory, health, uptime, metrics and alerts. Rule-based recommendations and an AI assistant
explain uptime and suggest improvements. The browser keeps a local copy of your data (IndexedDB), so
the app opens instantly and keeps working on slow or no network.

Data source for now is a **generator** that behaves like a fake cloud provider; a real Azure adapter
is planned, along with support for other cloud providers.

## Problem statement and objectives
Teams with VMs in several clouds check several consoles to answer "is everything up, and what should
we fix?". SyncViewer collects inventory and metrics from provider adapters into one relational
database, computes uptime/incidents/alerts, derives evidence-backed recommendations and exposes it
all through a secure API and an offline-first web app.

**Scope:** VM inventory, metrics (availability, CPU, memory, disk, network), uptime rollups,
incidents, alert rules, recommendations, daily/weekly digests, AI chat, RBAC (admin/user/viewer).

## Architecture
| Process | Dir | Role | Port |
|---|---|---|---|
| API | `backend/` | FastAPI: auth, CRUD, delta sync, AI agent | 8000 |
| Collector | `backend/app/collector/` | Scheduled ingestion, rollups, incidents, alerts, rules | - |
| Generator | `generator/` | Fake cloud provider (deterministic, with ground truth) | 8100 |
| Frontend | `frontend/` | React PWA, IndexedDB cache | 5173 dev / 8080 docker |
| Supabase | managed | Postgres + Auth only | - |

Diagram and design notes: [docs/architecture.md](docs/architecture.md). Database:
[ER diagram](docs/er-diagram.md), [data dictionary](docs/data-dictionary.md).

## Tech stack
Python 3.12+ (FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, APScheduler, Google ADK), PostgreSQL
(Supabase), React + Vite + TypeScript + Tailwind, TanStack Query, Dexie, vite-plugin-pwa, Recharts,
Docker, GitHub Actions.
