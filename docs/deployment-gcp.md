# Deployment on Google Cloud (alternative)

SyncViewer runs on Google Cloud Run in Mumbai (`asia-south1`), next to the Supabase database. One
script builds and deploys everything; the result is a public HTTPS link anyone can open.

## What runs where
| Part | Runs on | Name |
|---|---|---|
| Website (React app, served by nginx) | Cloud Run service | `syncviewer-web` |
| API | Cloud Run service | `syncviewer-api` |
| Demo cloud (generator) | Cloud Run service | `syncviewer-gen` |
| Collector | Cloud Run job, started by Cloud Scheduler | `syncviewer-collector` / `syncviewer-collect` |
| Container images | Artifact Registry | `syncviewer` |
| Database and login | Supabase (unchanged) | - |

```
Browser ──► syncviewer-web  (static app)
   │
   ├──► Supabase Auth (login)
   └──► syncviewer-api ──► Supabase Postgres
                 │
Cloud Scheduler ─┼─► syncviewer-collector (every 30 min) ──► Supabase Postgres
                 └──────────────┴──► syncviewer-gen (demo cloud)
```

## Cost
Everything is set up to stay inside Google Cloud's free tier:

- Each service runs **at most one instance** and **scales to zero** when idle.
- CPU is billed **only while a request is handled**.
- The collector runs every 30 minutes, never retries, and times out after 15 minutes.
- Artifact Registry keeps only the **two newest builds** of each image.
- Optional **budget kill switch**: email alerts at 50%, 90% and 100% of a monthly budget, and billing
  is unlinked (everything stops) when the budget is reached.

Expected cost: nothing. If anything, a few rupees a month for image storage above the free 0.5 GB.
Budget figures reach Google's billing system a few hours late, so the kill switch can overshoot the
budget slightly.

## 1. Prerequisites
- A Google account with a payment method. Google requires one even for free-tier use.
- The Google Cloud CLI:
  ```bash
  winget install Google.CloudSDK
  ```
  Open a new terminal afterwards so `gcloud` is on the PATH, then sign in:
  ```bash
  gcloud auth login
  ```
- The backend virtual environment (`backend/.venv`), already used for local runs.
- `.env` filled in for local use (Supabase URLs, keys, `CREDENTIAL_ENCRYPTION_KEY`, ...).

## 2. Create the Google Cloud project
1. Open https://console.cloud.google.com and create a project, for example `syncviewer`.
   Note the **project ID** shown under the name (it can differ from the name).
2. Billing > Link a billing account to the project. A new account may be offered free trial credit;
   accepting it is fine.

## 3. Settings in `.env`
| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | the project ID from step 2 |
| `GCP_REGION` | `asia-south1` (keep the app next to the database) |
| `COLLECT_SCHEDULE` | `*/30 * * * *` (cron, India time) |
| `BUDGET_AMOUNT` | monthly budget in the billing account's currency, e.g. `100INR` |
| `GENERATOR_API_KEY` | a long random string; the demo cloud is public and checks it |
| `DATABASE_URL` | Supabase **transaction pooler** URL (port 6543) |

Everything else (`SUPABASE_URL`, `SUPABASE_JWKS_URL`, `VITE_SUPABASE_ANON_KEY`,
`CREDENTIAL_ENCRYPTION_KEY`, `ADMIN_EMAILS`, `GOOGLE_API_KEY`, `GEMINI_MODEL`) is read from the
same file. Secrets are passed to Cloud Run through a temporary file outside the repo; they never
appear on the command line or in git.

Use the Gemini key from your own AI Studio project **without billing**. A key created inside the
billed Google Cloud project would make chat usage chargeable.

## 4. Budget and kill switch (once)
```bash
backend/.venv/Scripts/python deploy/gcp/deploy.py budget
```
This enables the billing APIs, creates the `syncviewer` budget with email alerts, and deploys a
small function that unlinks billing from the project when the budget is reached. Run it before the
first deploy.

## 5. Deploy
```bash
backend/.venv/Scripts/python deploy/gcp/deploy.py deploy
```
Add `--dry-run` to print the gcloud commands without running anything. The script:

1. checks the CLI login and that billing is enabled, and enables the required APIs;
2. creates the image registry with its cleanup policy and two service accounts with no
   permissions on the project (one runs the services, one may only start the collector job);
3. builds the three images with Cloud Build (a few minutes, within its free build minutes);
4. deploys the demo cloud, API and website;
5. deploys the collector job and schedules it;
6. checks `/health` and prints the public link.

The first deploy takes about 10 minutes. Run the same command after every change; it only
replaces what changed. Schema changes (new Alembic migrations) are applied from your machine
before deploying:
```bash
cd backend && .venv/Scripts/alembic upgrade head
```

## 6. The public link
The website's address is printed at the end of the deploy:
```
https://syncviewer-web-<project-number>.asia-south1.run.app
```
It is public and HTTPS, it does not change between deploys, and anyone with the link can open it.
Data stays private: every page needs a login, and each person only sees their own workspace.

Share that link. The first visit after a quiet period takes a few seconds while Cloud Run starts
the services; after that the app (a PWA) loads instantly from the browser's cache.

### A shorter or custom link
- **Free, shorter link:** Firebase Hosting can serve the website at `https://<project-id>.web.app`
  and supports a custom domain with free HTTPS. This is a separate, optional step; the deploy
  script would build the website for Firebase instead of Cloud Run.
- **Own domain on Cloud Run in Mumbai:** Cloud Run's built-in domain mapping is not available in
  `asia-south1`; the alternative is a load balancer, about USD 18 a month. Not recommended here.

If you change the link, add the new address to the Supabase URL configuration below and to
`CORS_ORIGINS`.

## 7. Supabase settings
Supabase > your project:

1. **Authentication > URL Configuration**
   - Site URL: the public link from step 6.
   - Redirect URLs: add `<public link>/**`. Keep `http://localhost:5173/**` for local work.

   Without this, password-reset emails link to localhost.
2. **Authentication > Sign In / Providers > Email**: turn **Confirm email** back on for a public
   site, so nobody can sign up with someone else's address.
3. **Authentication > Emails > SMTP Settings** (recommended once others use the app): Supabase's
   built-in sender only allows a few emails per hour. A free SMTP provider (for example Resend or
   Brevo) removes that limit.
4. **Sign-ups:** anyone with the link can sign up and gets an empty workspace of their own. Invited
   teammates need sign-ups enabled, so leave them on unless the app is private to your team.
5. **Database password:** if it was ever shared, reset it (Project Settings > Database) and update
   `DATABASE_URL` and `MIGRATION_DATABASE_URL` in `.env`, then deploy again.

## 8. Day-to-day
| Task | Command |
|---|---|
| API logs | `gcloud run services logs read syncviewer-api --region=asia-south1 --limit=50` |
| Run the collector now | `gcloud run jobs execute syncviewer-collector --region=asia-south1 --wait` |
| Recent collector runs | `gcloud run jobs executions list --job=syncviewer-collector --region=asia-south1` |
| Pause the schedule | `gcloud scheduler jobs pause syncviewer-collect --location=asia-south1` |
| Resume the schedule | `gcloud scheduler jobs resume syncviewer-collect --location=asia-south1` |
| List API revisions | `gcloud run revisions list --service=syncviewer-api --region=asia-south1` |
| Roll back the API | `gcloud run services update-traffic syncviewer-api --to-revisions=<revision>=100 --region=asia-south1` |

The same information is in the console under Cloud Run (services, jobs, logs, metrics).

## 9. If the budget is reached
The kill switch unlinks billing and all services stop. Data is in Supabase and is not affected. To
restart: Billing > Account management > link the billing account to the project again, then run
the deploy command.

## 10. Taking it down
Delete the project to stop everything and every possible charge at once:
```bash
gcloud projects delete <project-id>
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| `billing is not enabled` | Link a billing account to the project (step 2). |
| A step fails right after an API was enabled | Wait a minute and run the deploy again. |
| Cloud Build: permission denied pushing the image | Grant the Cloud Build service account the *Artifact Registry Writer* role, then deploy again. |
| Login page works, data does not load (CORS error in the browser console) | Open the app through the printed link; another address must be added to `CORS_ORIGINS`. |
| Password-reset email opens localhost | Supabase URL configuration (step 7). |
| Health check says NOT RESPONDING | `gcloud run services logs read syncviewer-api --region=asia-south1`; usually a missing value in `.env`. |

## Backups
`scripts/backup.sh` / `scripts/restore.sh`. Run `backup.sh` regularly against the session-pooler
URL (`MIGRATION_DATABASE_URL`); the free Supabase plan has no point-in-time recovery.
