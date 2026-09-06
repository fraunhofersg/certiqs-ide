QDB is the QKD security-compliance workbench bundled as `certiqs-qdb`.

The extension host starts the FastAPI service in `python/`, mints a short-TTL Internal JWT, and proxies `/internal/*` for the Vite webviews. The webview never holds `INTERNAL_AUTH_SECRET` and never opens Postgres.

Configure `DATABASE_URL` and related secrets in HQ Settings → QDB. Do not put live credentials in `.env.local.example`.
