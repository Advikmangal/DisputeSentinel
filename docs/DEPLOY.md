# Deploy PayoutSentinel on Render

Use the existing Blueprint and services when updating this project. Do not create
a duplicate database or replace the existing database connection. The repository's
`render.yaml` declares Free API and database plans plus a static frontend. Keep
these plans; no paid upgrade is required or authorized for this demo. Check current
limits in [Render documentation](https://render.com/docs/free) before relying on
free hosting for long-term storage.

## Update an existing deployment

1. Merge the tested branch into the tracked `master` branch. If automatic deploys
   are enabled, both services rebuild. Otherwise use Deploy latest commit.
2. API root: `backend`; build: `pip install -r requirements.txt`; start:
   `alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
   Health check: `/ready`. This release needs no new schema migration.
3. Frontend root: `frontend`; build: `npm ci && npm run build`; output: `dist`.
   Keep the `/*` to `/index.html` rewrite.
4. Preserve the existing database URL and merchant credentials. Startup seeds a
   merchant only if absent; changing the environment password does not reset an
   existing merchant's password.

## Environment values

Enter secrets privately in Render, never in source control or chat.

| Service | Variable | Value |
| --- | --- | --- |
| API | `DATABASE_URL` | Existing internal PostgreSQL connection, wired by Blueprint |
| API | `ENVIRONMENT` | `production` |
| API | `FRONTEND_ORIGIN` | Exact static site's HTTPS origin, no trailing slash |
| API | `JWT_SECRET` | Independently generated random secret, at least 32 characters |
| API | `DEMO_MERCHANT_EMAIL`, `DEMO_MERCHANT_PASSWORD` | Initial login, password at least 12 characters |
| API | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | Same PayPal Sandbox REST app |
| API | `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` |
| API | `PAYPAL_WEBHOOK_ID` | Registered Sandbox webhook ID |
| API | `GEMINI_API_KEY`, `GEMINI_MODEL` | Key and supported structured-output model available to your account |
| API | `DISPUTE_SOURCE` | `fixture` for simulated demo cases; `paypal` for matched Sandbox cases |
| Frontend | `VITE_API_URL` | API HTTPS origin without `/api` or trailing slash |

Checkout gets its public client ID from the authenticated backend. Remove obsolete
`VITE_PAYPAL_CLIENT_ID`; it is no longer needed. Changing `VITE_API_URL` requires a
frontend rebuild. Register the PayPal Sandbox webhook at
`https://YOUR_API/api/webhooks/paypal` for capture notifications. PDF analysis sends
extracted document text to Google Gemini; use synthetic documents for demos.

## First deployment

Connect this repository using New > Blueprint, select `master` and `render.yaml`,
and review the plans before creating resources. Supply the private variables above.
After URLs are assigned, set the frontend's `VITE_API_URL` and backend's
`FRONTEND_ORIGIN`, then rebuild/redeploy. The database must be PostgreSQL; evidence
is stored as BYTEA and does not require a persistent disk.

## Hosted acceptance

- `/health` and `/ready` return HTTP 200. `/ready` checks the database.
- Anonymous `/api/transactions` returns 401. Sign in with the configured merchant.
- Complete one Sandbox checkout with a buyer distinct from the seller. Confirm
  VERIFIED after reload, and confirm retry does not duplicate the transaction.
- Upload a text PDF in Evidence Vault, analyze, and inspect the exact page quotes.
  Test a failure without a configured AI key: a clear error must retain old facts.
- Sync simulated disputes, generate a draft, edit, approve and export Markdown.
  Editing after approval must require approval again. Nothing is sent to PayPal.
- Check desktop and mobile navigation and empty/error states.

A successful CI run verifies mocked provider paths, PostgreSQL migrations and
concurrency, and the production frontend build. It does not prove that hosted
PayPal or Gemini credentials work; record those acceptance checks separately.

## Recovery

The frontend probes `/ready` before requests to accommodate a sleeping API. If
readiness fails, check deployment logs, database availability, and exact CORS
origin. If payment approval succeeds but verification times out, use the pending
payment's Retry verification action rather than paying again.

Keep backups of evidence and database records before a free database expires or is
replaced. The optional `scripts/seed_demo_data.py` creates synthetic transactions;
it cannot recover real history. Never run `scripts/check_postgres.py` against the
hosted database: it is a destructive test for disposable databases only.
