# Deployment (Azure)

SyncViewer runs on Azure with as little as possible: **one container app** (the API with the demo
cloud built in) and a **free Static Web App** for the website. Supabase keeps the database and
login. On an **Azure for Students** subscription nothing can be billed: usage comes out of the
student credit, and Azure switches services off if the credit runs out.

| Part | Runs on | Name |
|---|---|---|
| API + demo cloud (generator at `/gen`) | Container Apps, Central India | `syncviewer-api` |
| Hourly collection | GitHub Actions schedule calls the API (`.github/workflows/collect.yml`) | - |
| Website | Static Web Apps, free plan | `syncviewer-web` |
| Container image | Container Registry (Basic) | `syncviewer<id>` |
| Database and login | Supabase | - |

```
Browser ──► Static Web Apps (website)
   ├──► Supabase Auth (login)
   └──► syncviewer-api ──► Supabase Postgres
          └─ /gen: demo cloud, same process
GitHub Actions (hourly) ──► POST /api/v1/internal/collect ──► collection runs in the background
```

## Cost
- The app **scales to zero** when idle and runs **at most one replica** (0.5 vCPU, 1 GiB).
  Container Apps' free monthly grant (180,000 vCPU-seconds, 360,000 GiB-seconds, 2 million
  requests) covers normal use: the hourly collection keeps it awake for a few minutes each hour.
- **Hourly collection costs nothing**: GitHub Actions wakes the app with one request. Each run
  fetches what changed since the previous one; after a long pause it catches up on the last
  24 hours, so a run always finishes in about a minute.
- **Static Web Apps (Free)** costs nothing. **Log Analytics is off** (it charges per GB).
- **Container Registry (Basic)** is the only fixed cost, about USD 5 a month from the credit.

## 1. Tools
```bash
winget install Microsoft.AzureCLI
```
Open a new terminal, then `az login` (a browser opens; approve the two-step verification prompt).
Personal Microsoft accounts need two-step verification turned on first
(account.microsoft.com/security). Also needed: **Docker Desktop** (running), Node.js, and the
GitHub CLI logged in (`gh auth login`) so the deploy can set up the hourly schedule.

## 2. Settings in `.env`
The deploy reads the same `.env` as local runs.

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase **transaction pooler** URL (port 6543) |
| `GENERATOR_API_KEY` | a long random string; protects `/gen` |
| `COLLECTOR_TOKEN` | secret for the hourly trigger; the deploy creates it if missing |
| `AZURE_RESOURCE_GROUP` | `syncviewer-rg` (default) |
| `AZURE_LOCATION` | `centralindia` (default), next to the database |
| `AZURE_WEB_LOCATION` | `eastasia` (default); the site itself is served worldwide |
| `AZURE_WEB_DOMAIN` | optional custom domain for the website, e.g. `syncviewer.example.me` |

Secrets reach Azure through temporary files outside the repo and are stored as Container Apps
secrets; they never appear on the command line or in git.

## 3. Deploy
From the repo root:
```bash
backend/.venv/Scripts/python deploy/azure/deploy.py
```
Add `--dry-run` to print every command first. The script:

1. checks the login, registers the resource providers and creates the resource group;
2. builds one image (`deploy/azure/Dockerfile`: backend + generator) and pushes it;
3. creates the Container Apps environment (logs off) and the Static Web App if they are missing;
4. deploys `syncviewer-api` and stores the hourly trigger's secret and the API address in the
   GitHub repository;
5. builds the website with the API's address and uploads it, and stores the website's deploy
   token in GitHub so pushes to `main` republish it (`.github/workflows/web.yml`).

Run the same command after every change. `--skip-web` leaves the website alone; `--skip-image`
reuses the last image (settings only).

The two GitHub workflows run from the `main` branch: the hourly collection starts once
`collect.yml` is merged into `main`. Until then, use **Collect now** or run the workflow from the
repository's Actions tab.

## 4. The public link
`https://<name>.azurestaticapps.net`, printed at the end of the deploy. It is public and HTTPS;
every page needs a login, and each person only sees their own workspace. The first visit after a
quiet period takes a few seconds while the API starts.

**Custom domain (free HTTPS):**
1. At your domain's DNS provider add a **CNAME** record: host `syncviewer` (the subdomain), value
   the `<name>.azurestaticapps.net` address.
2. Set `AZURE_WEB_DOMAIN=syncviewer.<your-domain>` in `.env` and deploy again with
   `--skip-image --skip-web`. The script attaches the domain (Azure issues the certificate, which
   can take a few minutes) and lets the API accept requests from it.
3. Use the custom address in the Supabase URL configuration (step 5). The `azurestaticapps.net`
   address keeps working.

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
| Collect now (from the terminal) | `gh workflow run collect.yml` |
| Schema change | `cd backend && .venv/Scripts/alembic upgrade head`, then deploy |
| Remaining credit | Azure portal > Subscriptions > Azure for Students |
| Take everything down | `az group delete -n syncviewer-rg` |

## Troubleshooting
| Symptom | Fix |
|---|---|
| `az login`: "you must use multi-factor authentication" | Turn on two-step verification for the account, then `az login` in a normal terminal (not Cloud Shell). |
| A region is not allowed | Student subscriptions allow a fixed list of regions; set `AZURE_LOCATION` / `AZURE_WEB_LOCATION` to an allowed one. |
| `docker` errors | Start Docker Desktop. |
| API health check does not respond | `az containerapp logs show -n syncviewer-api -g syncviewer-rg --follow`; usually a missing `.env` value. |
| Website loads but data does not (CORS error in the browser console) | Open the site through its printed address; the API only accepts that origin. |
| Login emails link to localhost | Supabase URL Configuration (step 5). |

## Backups
`scripts/backup.sh` / `scripts/restore.sh`. Run `backup.sh` regularly against the session-pooler
URL (`MIGRATION_DATABASE_URL`); the free Supabase plan has no point-in-time recovery.
