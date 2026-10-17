# Deployment (Zoho Catalyst)

The backend runs on **Catalyst AppSail** and the website on **Catalyst Slate**; the database and
login stay on Supabase. With **Catalyst for Students** this is free: no card is needed, and when the
student allowance runs out the apps are stopped instead of billed.
(A Google Cloud setup is also available: [deployment-gcp.md](deployment-gcp.md).)

| Part | Runs on | Name |
|---|---|---|
| API | AppSail service (container image `backend/Dockerfile`) | `syncviewerapi` |
| Demo cloud (generator) | AppSail service (container image `generator/Dockerfile`) | `syncviewergen` |
| Collector | Catalyst Job Scheduling: a cron calls the API every 30 minutes | - |
| Website | Slate, built from this GitHub repo (`frontend/`) | - |
| Database and login | Supabase | - |

```
Browser ──► Slate (website) ──► AppSail syncviewerapi ──► Supabase Postgres
   └──► Supabase Auth              ▲          └──► AppSail syncviewergen (demo cloud)
Job Scheduling (every 30 min) ─────┘  POST /api/v1/internal/collect
```

### How AppSail shapes the setup
- **Requests end after 30 seconds.** The scheduled collector therefore calls
  `POST /api/v1/internal/collect`, which starts the cycle in the background and answers at once.
  AI chat answers within 25 seconds (`AGENT_TIMEOUT_SECONDS`).
- **Idle apps sleep.** An instance stops a few minutes after its last request; the next visit
  takes a few seconds while it starts.
- **Development environment.** New projects run in Catalyst's Development environment, which is
  free and gives each app a public URL. Production requires a payment method; a student project
  can stay in Development.

## 1. Accounts and tools
1. **Catalyst account**: sign up at https://catalyst.zoho.com/students/. Choose the **India** data
   centre if asked (catalyst.zoho.in), so the backend runs close to the Supabase database in Mumbai.
   There is no student switch in the console: the Development environment is free, and without a
   card on file nothing can be charged. For more usage than the free limits, email
   support@zohocatalyst.com with your student details and project description.
2. **Catalyst CLI** (Node.js is already installed):
   ```bash
   npm install -g zcatalyst-cli
   ```
   ```bash
   catalyst login
   ```
3. **Docker Desktop**: start it before building the images.
4. **Supabase**: the project must be active (restore it from the dashboard if it was paused).

## 2. Create the Catalyst project
1. Catalyst console > **Create Project**, name it `SyncViewer`.
2. Link this folder to it (once):
   ```bash
   cd deploy/catalyst
   ```
   ```bash
   catalyst init
   ```
   Select the `SyncViewer` project. No other features need to be set up here; the backend is
   deployed as standalone AppSail services. `catalyst init` creates `catalyst.json` and
   `.catalystrc` in this folder.

## 3. Deploy the backend (AppSail)
From the repo root:
```bash
backend/.venv/Scripts/python deploy/catalyst/deploy.py build
```
```bash
backend/.venv/Scripts/python deploy/catalyst/deploy.py deploy
```
`build` creates the two images for linux/amd64; `deploy` uploads them as `syncviewerapi`
(port 8000) and `syncviewergen` (port 8100). Add `--dry-run` to see the commands first.

In the console, open **AppSail** and for each service:
- note its **URL**;
- **Configuration > Memory**: 1024 MB for `syncviewerapi`, 256 MB for `syncviewergen`.

The API will not start until its environment variables are set in step 5.

## 4. Deploy the website (Slate, from GitHub)
1. Console > **Slate** > create an app > **Deploy from Git** > connect GitHub and pick the
   `syncViewer` repository and the branch to publish (`main`).
2. Framework **React / Vite**; root path **`frontend`**; build command `npm run build`; output
   path **`dist`**.
3. **Configuration > Environment Variables**: add `VITE_API_URL` (the `syncviewerapi` URL),
   `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` and `VITE_ENABLE_GOOGLE_AUTH=false`.
4. Deploy, and note the website URL (`https://<name>.onslate.in`). Turn on **auto-deploy** so every
   push to the branch publishes the site.

## 5. Connect the pieces
1. Add to `.env`:
   ```
   CATALYST_API_URL=<syncviewerapi URL>
   CATALYST_GEN_URL=<syncviewergen URL>
   CATALYST_WEB_URL=<Slate website URL>
   COLLECTOR_TOKEN=<long random string>
   ```
   Make sure `GENERATOR_API_KEY` is a long random string too; the demo cloud is public.
2. Generate the console values:
   ```bash
   backend/.venv/Scripts/python deploy/catalyst/deploy.py env
   ```
   This writes `deploy/catalyst/.secrets/console-values.txt` (git-ignored). It lists every
   environment variable for each AppSail service and for Slate, and the scheduled job's settings.
3. Paste each section into the matching console screen (**AppSail > service > Configuration >
   Environment Variables**, and Slate's), save, and redeploy or restart the services.
4. Delete `console-values.txt` when you are done; it contains secrets.

## 6. Schedule the collector
Console > **Job Scheduling**:
1. Create a **Job Pool** of type **Webhook**.
2. Create a **Pre-defined Cron**, every 30 minutes, that submits a job to that pool with:
   - Method `POST`
   - URL `<syncviewerapi URL>/api/v1/internal/collect`
   - Header `X-Collector-Token: <COLLECTOR_TOKEN>`

   If headers cannot be set, use the URL
   `<syncviewerapi URL>/api/v1/internal/collect?token=<COLLECTOR_TOKEN>` instead.

The endpoint answers `202 started` (or `already running`); without the right token it answers 404.
Use **Collect now** on the Accounts page for fresh data between runs. Regular runs also keep the
free Supabase project from pausing.

## 7. Supabase settings
Supabase > your project > **Authentication**:

1. **URL Configuration**
   - **Site URL**: the Slate website URL. Confirmation and reset emails link here.
   - **Redirect URLs**: add `<website URL>/**`, and keep `http://localhost:5173/**` for local work.
2. **Sign In / Providers > Email**
   - **Confirm email: on.** New users must click the link in their email before they can log in,
     so nobody can sign up with someone else's address. The sign-up page already tells them to
     check their inbox.
   - **Secure email change: on** (both the old and the new address must confirm).
   - Minimum password length 8 or more.
3. **Emails > SMTP Settings**: Supabase's built-in sender is meant for testing and allows only a
   few emails per hour. For real users, add a free SMTP provider (Resend, Brevo or Zoho
   ZeptoMail): host, port, username and password from the provider, and a sender address on a
   domain you control.
4. **Emails > Templates** (optional): adjust the confirmation and reset emails' wording.
5. **Rate Limits**: keep the defaults.
6. **Sign-ups** stay enabled: invited teammates join by signing up with the invited email.

Also: Project Settings > Database > **reset the database password** if it was ever shared, update
`DATABASE_URL` and `MIGRATION_DATABASE_URL` in `.env`, run `deploy.py env` again and paste the new
`DATABASE_URL` into the API's environment variables.

## 8. Updating
| Change | What to do |
|---|---|
| Frontend | Push to the published branch; Slate rebuilds automatically. |
| Backend or generator | `deploy.py build` then `deploy.py deploy`. |
| Database schema (new migration) | `cd backend && .venv/Scripts/alembic upgrade head`, then deploy the backend. |
| Settings | Change them in the console (or `.env` + `deploy.py env`) and restart the service. |

## Troubleshooting
| Symptom | Fix |
|---|---|
| `docker build` fails to connect | Start Docker Desktop. |
| The CLI cannot find the image | Run `docker images` and check the tag; build again with `deploy.py build`. |
| API URL shows an error page | Environment variables missing: AppSail > syncviewerapi > Logs, then step 5. |
| Website loads but data does not (CORS error in the browser console) | `CORS_ORIGINS` must be exactly the Slate URL (no trailing slash). |
| Login emails link to localhost | Supabase URL Configuration (step 7). |
| Opening a deep link such as `/team` directly shows 404 | Open the site root once; the installed app then handles every page. |
| Chat says it could not answer | It has 25 seconds per question on AppSail; ask a narrower question. |

## Backups
`scripts/backup.sh` / `scripts/restore.sh`. Run `backup.sh` regularly against the session-pooler
URL (`MIGRATION_DATABASE_URL`); the free Supabase plan has no point-in-time recovery.
