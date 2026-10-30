# SyncViewer

Keeping an eye on virtual machines across Azure, AWS and Google Cloud usually means juggling three
consoles. SyncViewer puts them all in one place: which VMs are up, how busy they are, their uptime,
incidents and alerts. It also tells you what's worth fixing (an idle VM that's too big, a disk about
to fill up, a stopped VM you're still paying for), and you can ask its AI assistant things like
"which VM had the most downtime this week?".

I built it for the Database Systems course (BCSE307L) at VIT, so a lot of the interesting work lives
in the PostgreSQL database: triggers, a stored procedure for uptime, views and row-level security.

**Where the data comes from:** a built-in demo cloud with VMs that misbehave on purpose, or
**Prometheus** for real machines ([setup guide](docs/prometheus.md)).

## What's in each folder
| Folder | What it does |
|---|---|
| `frontend/` | The website (React). Keeps a copy of your data in the browser so it opens instantly, even offline. |
| `backend/` | The API (FastAPI) and the collector that fetches VM data every hour. Database migrations live in `backend/alembic/`. |
| `generator/` | The demo cloud: fake VMs with known problems, so you can try everything without a cloud account. |
| `deploy/` | Scripts for deploying to Azure, plus a local Prometheus setup in `deploy/monitoring/`. |
| `docs/` | Architecture, ER diagram, data dictionary and guides. |
| `scripts/` | Database backup and restore (`pg_dump` / `pg_restore`). |
| `.github/workflows/` | GitHub Actions: tests on every push, website publishing, the hourly collection. |

## Run it on your computer
You'll need Git, Python 3.12+, Node.js 20+ and a free [Supabase](https://supabase.com) project.

1. Clone the repo and add your settings:
   ```bash
   git clone https://github.com/karthikr06/syncViewer.git
   cd syncViewer
   copy .env.example .env      # then fill in your Supabase details
   ```
2. Install the backend and create the database tables:
   ```bash
   cd backend
   python -m venv .venv
   .venv\Scripts\pip install -e .
   .venv\Scripts\alembic upgrade head
   ```
3. Start everything: double-click `start-local.bat` (Windows), or run `docker compose up -d` if
   you have Docker.
4. Open http://localhost:5173 (or http://localhost:8080 with Docker), sign up, add a demo account
   and press **Collect now**.

## Run it in the cloud
SyncViewer is three pieces, so it runs on pretty much any cloud:

- **The backend** is a Docker image (`deploy/azure/Dockerfile`) that holds the API, the collector and
  the demo cloud. Any container host works: Azure Container Apps, Google Cloud Run, Render, Railway,
  Fly.io.
- **The website** is a static build (`npm run build` in `frontend/`), so any static host works:
  Azure Static Web Apps, Netlify, Vercel.
- **The database** is PostgreSQL on Supabase.

On Azure it's one command: `python deploy/azure/deploy.py`. The full walkthrough is in
[docs/deployment.md](docs/deployment.md).
