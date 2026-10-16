# Deployment (Google Cloud)

| Part | Runs on | Cost guard |
|---|---|---|
| API | Cloud Run service `syncviewer-api` | max 1 instance, scales to zero, CPU only during requests |
| Generator (demo cloud) | Cloud Run service `syncviewer-gen` | same; protected by `GENERATOR_API_KEY` |
| Frontend | Cloud Run service `syncviewer-web` (nginx) | same |
| Collector | Cloud Run job `syncviewer-collector`, started by Cloud Scheduler | every 30 min, no retries, 15 min timeout |
| Database and login | Supabase | free plan |
| Images | Artifact Registry `syncviewer` | keeps the two newest builds of each image |

Everything runs in `asia-south1` (Mumbai), next to the Supabase database. Secrets stay in `.env`;
the deploy script hands them to Cloud Run through a temporary file outside the repo.

## One-time setup
1. Install the Google Cloud CLI (`winget install Google.CloudSDK`), open a new terminal and run
   `gcloud auth login`.
2. In the Google Cloud console create a project and link a billing account to it.
3. In `.env` set `GCP_PROJECT_ID`, and `BUDGET_AMOUNT` in your billing account's currency
   (for example `100INR`).
4. Budget alerts and the kill switch:
   ```bash
   backend/.venv/Scripts/python deploy/gcp/deploy.py budget
   ```

## Deploy (first time and after every change)
```bash
backend/.venv/Scripts/python deploy/gcp/deploy.py deploy
```
Add `--dry-run` to print the gcloud commands without running them. The script builds the three
images with Cloud Build, deploys the services and the collector job, schedules the job and checks
`/health`. It prints the app URL at the end.

After the first deploy, in Supabase > Authentication > URL Configuration set the Site URL to the app
URL and add `<app URL>/**` to the Redirect URLs.

Schema changes are applied from your machine before deploying:
```bash
cd backend && .venv/Scripts/alembic upgrade head
```

## Notes
- The first request after an idle period takes a few seconds while Cloud Run starts the service.
- The demo cloud keeps VM actions in memory, so they reset when the generator scales to zero.
- Keep the Gemini key in its own AI Studio project without billing, so chat stays on the free tier.
- If the budget is reached, billing is unlinked and the services stop. Re-link billing in the
  console and deploy again; the data in Supabase is unaffected.

## Backups
`scripts/backup.sh` / `scripts/restore.sh`. Run `backup.sh` regularly against the session-pooler
URL (`MIGRATION_DATABASE_URL`).
