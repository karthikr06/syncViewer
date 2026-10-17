# Deployment (Azure)

SyncViewer's backend and website run on Azure; the database and login stay on Supabase. On an
**Azure for Students** subscription nothing can be billed: usage comes out of the student credit,
and Azure switches services off if the credit runs out.

| Part | Runs on | Name |
|---|---|---|
| API | Container Apps (Central India) | `syncviewer-api` |
| Demo cloud (generator) | Container Apps, internal only | `syncviewer-gen` |
| Collector | Container Apps job, hourly | `syncviewer-collector` |
| Website | Static Web Apps, free plan | `syncviewer-web` |
| Container images | Container Registry (Basic) | `syncviewer<id>` |
| Database and login | Supabase | - |

```
Browser ──► Static Web Apps (website)
   ├──► Supabase Auth (login)
   └──► syncviewer-api ──► Supabase Postgres
              │
              └──► syncviewer-gen (demo cloud, not reachable from the internet)
syncviewer-collector (hourly) ──► Supabase Postgres, syncviewer-gen
```

## Cost
- Container Apps give every subscription a free monthly grant (180,000 vCPU-seconds,
  360,000 GiB-seconds, 2 million requests). The apps **scale to zero** when idle and run **at most
  one replica**, so normal use stays inside it.
- The **collector runs hourly**. Each run fetches everything since the previous one, so no data is
  lost; **Collect now** on the Accounts page fetches fresh data at any time.
- **Static Web Apps (Free)** costs nothing.
- **Container Registry (Basic)** is the only fixed cost, about USD 5 a month from the credit.
- **Log Analytics is off** (it charges per GB). Live logs still work (see Day-to-day).

## 1. Tools
```bash
winget install Microsoft.AzureCLI
```
Open a new terminal, then:
```bash
az login
```
Also needed: **Docker Desktop** (running) and Node.js. If you have several subscriptions, put the
student one in `.env` as `AZURE_SUBSCRIPTION_ID`.

## 2. Settings in `.env`
The deploy reads the same `.env` as local runs. Check these:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase **transaction pooler** URL (port 6543) |
| `GENERATOR_API_KEY` | a long random string |
| `AZURE_RESOURCE_GROUP` | `syncviewer-rg` (default) |
| `AZURE_LOCATION` | `centralindia` (default), next to the database |
| `AZURE_WEB_LOCATION` | `eastasia` (default); Static Web Apps only exists in a few regions, the site is served worldwide |
| `COLLECT_SCHEDULE` | `0 * * * *` (hourly, UTC) |

Secrets reach Azure through temporary files outside the repo and are stored as Container Apps
secrets; they never appear on the command line or in git.

## 3. Deploy
From the repo root:
```bash
backend/.venv/Scripts/python deploy/azure/deploy.py
```
Add `--dry-run` to print every command first. The script:

1. checks the login, adds the Container Apps CLI extension, registers the resource providers and
   creates the resource group;
2. creates the registry, builds the backend and generator images with Docker and pushes them;
3. creates the Container Apps environment (logs off) and the Static Web Apps site;
4. deploys the demo cloud (internal ingress only) and the API (public HTTPS);
5. deploys the hourly collector job;
6. builds the website with the API's address and uploads it; if the GitHub CLI is logged in, it
   also stores the site's deploy token and settings in the repository, so every push to `main`
   republishes the website (`.github/workflows/web.yml`).

It prints the website and API addresses at the end. Run the same command after backend changes;
use `--skip-web` to leave the website alone, or `--skip-images` to only change settings.

## 4. The public link
The website address looks like `https://<name>.azurestaticapps.net`. It is public and HTTPS,
anyone with the link can open it, and every page needs a login. Each person only sees their own
workspace. A custom domain can be added for free in the portal (Static Web Apps > Custom domains).

## 5. Supabase settings
Supabase > your project > **Authentication**:

1. **URL Configuration**
   - Site URL: the website address.
   - Redirect URLs: add `<website address>/**`; keep `http://localhost:5173/**` for local work.
   Confirmation and password-reset emails link here.
2. **Sign In / Providers > Email**
   - **Confirm email: on**, so nobody can sign up with someone else's address. The sign-up page
     already tells new users to check their inbox.
   - **Secure email change: on**; minimum password length 8 or more.
3. **Emails > SMTP Settings**: Supabase's built-in sender allows only a few emails an hour. For
   real users add a free SMTP provider (Resend, Brevo or Zoho ZeptoMail).
4. Leave **sign-ups enabled**: invited teammates join by signing up with the invited email.

If the database password was ever shared, reset it (Project Settings > Database), update
`DATABASE_URL` and `MIGRATION_DATABASE_URL` in `.env`, and deploy again with `--skip-web`.

## 6. Day-to-day
| Task | Command |
|---|---|
| Live API logs | `az containerapp logs show -n syncviewer-api -g syncviewer-rg --follow` |
| Run the collector now | `az containerapp job start -n syncviewer-collector -g syncviewer-rg` |
| Recent collector runs | `az containerapp job execution list -n syncviewer-collector -g syncviewer-rg -o table` |
| Schema change | `cd backend && .venv/Scripts/alembic upgrade head`, then deploy |
| Remaining credit | Azure portal > Subscriptions > Azure for Students |
| Take everything down | `az group delete -n syncviewer-rg` |

## Troubleshooting
| Symptom | Fix |
|---|---|
| A region is not allowed | Student subscriptions allow a fixed list of regions; set `AZURE_LOCATION` / `AZURE_WEB_LOCATION` to an allowed one. |
| `docker` errors | Start Docker Desktop. |
| API health check does not respond | `az containerapp logs show -n syncviewer-api -g syncviewer-rg --follow`; usually a missing `.env` value. |
| Website loads but data does not (CORS error in the browser console) | Open the site through its printed address; the API only accepts that origin. |
| Login emails link to localhost | Supabase URL Configuration (step 5). |

## Backups
`scripts/backup.sh` / `scripts/restore.sh`. Run `backup.sh` regularly against the session-pooler
URL (`MIGRATION_DATABASE_URL`); the free Supabase plan has no point-in-time recovery.
