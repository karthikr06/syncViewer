# Deployment

Targets: API on a container host (Render / Railway / Koyeb / Fly.io), frontend on a static host
(Netlify / Cloudflare Pages / Vercel, or the nginx image), collector local or in a container, database
and auth on Supabase.

## 1. Supabase
1. Create the project (Data API off, or "automatically expose new tables" off; the migrations lock
   the data API anyway).
2. Authentication -> Providers: enable Email and Google. Add your site URLs to *Redirect URLs*.
3. Copy into `.env`: project URL, JWKS URL (`<url>/auth/v1/.well-known/jwks.json`), anon key,
   the **session pooler** URL as `MIGRATION_DATABASE_URL`, the **transaction pooler** URL as
   `DATABASE_URL`.
4. Apply the schema (once, and after every release that adds migrations):
   ```bash
   docker compose run --rm migrate
   ```

## 2. API (container host)
Image: `<dockerhub-user>/syncviewer-backend` (built by CI). Start command is already
`uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`. Set these environment variables
on the host (never commit them):
`APP_ENV=production`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWKS_URL`,
`CREDENTIAL_ENCRYPTION_KEY`, `CORS_ORIGINS=https://<your-frontend>`, `ADMIN_EMAILS`,
`GENERATOR_URL` + `GENERATOR_API_KEY` (if you keep the demo provider), optional `GOOGLE_API_KEY`.
Health check path: `/health`. In production `/docs` and `/openapi.json` are disabled.
A ready-made `render.yaml` is in the repo root.

## 3. Frontend
Build with the public values (they are baked in at build time):
```bash
cd frontend
VITE_SUPABASE_URL=... VITE_SUPABASE_ANON_KEY=... VITE_API_URL=https://<api-host> npm run build
```
Deploy `dist/` to the static host. Keep `public/_headers` (edit the `connect-src` hosts) so the strict
CSP is sent. The nginx image does the same through `CSP_CONNECT_SRC`.

## 4. Collector
The collector is a separate process (`python -m app.collector.serve`). Run it with
`docker compose up -d collector` on any machine that can reach the database and the provider, or
trigger `app.collector.handler.handler` from a scheduler such as Zoho Catalyst Cron.

## 5. Custom domain (optional)
DuckDNS (or any DNS) -> a small VM running the compose stack behind Caddy for automatic HTTPS:
```
syncviewer.duckdns.org {
    reverse_proxy frontend:80
}
api.syncviewer.duckdns.org {
    reverse_proxy api:8000
}
```

## 6. Backups
`scripts/backup.sh` / `scripts/restore.sh` (see README). Schedule `backup.sh` with cron or Task
Scheduler against the session-pooler/direct URL.
