# Deploy PayoutSentinel on Render

This is deployment preparation. No services have been provisioned and there is
no verified public health URL yet. T2.4's hosted acceptance remains pending until
you follow these steps and record the successful URL in README.md.

## 1. Create the Blueprint

1. Sign in to [Render Dashboard](https://dashboard.render.com/) and select your workspace.
2. Click **New +**, then **Blueprint**.
3. Connect GitHub if prompted and grant access to
   `Advikmangal/DisputeSentinel`. Select that repository and click **Connect**.
4. Choose branch **master**, name the Blueprint **PayoutSentinel**, and use
   **render.yaml** as the Blueprint path.
5. Review the three resources: `payoutsentinel-db` (managed Postgres),
   `payoutsentinel-api` (Python web service), and `payoutsentinel-web` (static site).
   The API and database use Singapore. The API uses paid **Starter** for Shell
   access; the database uses paid **0.1c-256mb**. Review Render's displayed charges
   before applying. This file does not create or authorize resources by itself.
6. Supply the prompted environment values below. `sync: false` means you enter
   values in Render; none are embedded in the Blueprint. Render's creation button
   may be labeled **Apply** or **Deploy Blueprint**. Click it after reviewing all settings.

The initial frontend/backend URLs might not be known yet. Use
`https://frontend-pending.invalid` for FRONTEND_ORIGIN and
`https://api-pending.invalid` for VITE_API_URL if the form needs values before
creation. These intentionally do not connect anywhere. Replace them with the
actual assigned URLs in step 2 before trying login. Do not guess Render subdomains.

### API service environment

| Name | Enter in Render |
|---|---|
| PAYPAL_CLIENT_ID | Sandbox REST app client ID |
| PAYPAL_CLIENT_SECRET | Secret for that same Sandbox app |
| PAYPAL_BASE_URL | Exactly `https://api-m.sandbox.paypal.com` |
| GEMINI_API_KEY | Your Gemini API key; never expose it to the frontend |
| JWT_SECRET | A random value of at least 32 characters; use a password manager to generate/store it |
| DEMO_MERCHANT_EMAIL | Email you want to use for merchant login |
| DEMO_MERCHANT_PASSWORD | Unique password of 12–1024 characters; no default exists |
| FRONTEND_ORIGIN | Exact frontend HTTPS origin, with no trailing slash, path, query or wildcard |

The Blueprint supplies `ENVIRONMENT=production`, `PYTHON_VERSION=3.12.11`, and
`DISPUTE_SOURCE=fixture`. `DATABASE_URL` is populated automatically from the
managed database's internal connection string. Do not replace it with a public
URL or commit it. External database access is disabled by `ipAllowList: []`;
the API connects on Render's private network.

### Static site environment

| Name | Enter in Render |
|---|---|
| VITE_API_URL | API HTTPS origin only, without `/api`; a final slash is tolerated |
| VITE_PAYPAL_CLIENT_ID | Public client ID of the same **Sandbox** app as the backend |

Only public build-time configuration belongs on the static site. Never add
JWT_SECRET, database URLs, merchant passwords or PayPal client secrets under a
`VITE_` name. Node is pinned to 24.13.0 in the Blueprint. Vite embeds both VITE_
values at build time; changing them requires a fresh frontend build/deploy.

## 2. Connect the assigned service URLs

1. Open **payoutsentinel-api** from the Dashboard. Copy its HTTPS `onrender.com`
   URL from the service page. On **payoutsentinel-web → Environment → Edit**, set
   `VITE_API_URL` to that URL, excluding a trailing `/api` or other path.
2. Open **payoutsentinel-web** and copy its HTTPS URL. On
   **payoutsentinel-api → Environment → Edit**, set `FRONTEND_ORIGIN` to exactly
   that origin with no trailing slash.
3. Save both changes. Choose the save option that rebuilds/redeploys the static
   site; if saving alone, use **Manual Deploy → Deploy latest commit** afterward.
   Redeploy the API after changing FRONTEND_ORIGIN so CORS reloads its setting.
4. If you later add a custom frontend domain, repeat the FRONTEND_ORIGIN update
   using the one intended frontend origin. Alternate origins are deliberately
   not allowed. CORS is not authentication; JWTs still protect the API.

## 3. Confirm builds and migrations

1. Open **payoutsentinel-api → Events/Logs**. Its root directory is `backend`.
   Confirm Python **3.12.11** and successful `pip install -r requirements.txt`.
2. Its start command is:

   ```sh
   alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

   Migration failure stops startup. Keep this blueprint at one API instance;
   do not launch overlapping migration/deploy operations. Never run
   `alembic downgrade base` on your deployed database because it deletes data.
3. Missing/short/placeholder JWT_SECRET makes production startup fail with a
   configuration message. Set a valid secret in **Environment**, then redeploy.
   Production also requires an HTTPS FRONTEND_ORIGIN. The application accepts
   Render's `postgres://` or `postgresql://` database URL and uses the psycopg
   driver while preserving its connection details.
4. Open the API URL followed by `/health`. Confirm HTTP 200 and
   `{"status":"ok"}`. This is also the configured Render health check.
5. Open **payoutsentinel-web → Events/Logs**. Root directory is `frontend`, build
   command is `npm ci && npm run build`, and publish directory is `dist` relative
   to that root. The rewrite `/* → /index.html` serves the SPA on nested paths.

## 4. Seed the demo merchant

1. Ensure the API is running and migrations have succeeded.
2. Open **payoutsentinel-api → Environment** and confirm both DEMO_MERCHANT_EMAIL
   and DEMO_MERCHANT_PASSWORD are set. Do not paste them into source files or shell commands.
3. Open the API's **Shell** tab. From the service root (`backend`), run:

   ```sh
   python -m app.seed_merchant
   ```

4. Expect `Demo merchant seeded.` or
   `Merchant already exists; password unchanged.` The command reads Render's
   environment, stores only a salted hash, and does not print the password.
   Existing real password hashes are not reset by rerunning the command.
5. If seeding fails, check environment values and migration logs; rerun once corrected.

The seed implementation is inside `backend/app` because Render excludes files
outside `rootDir`. Do **not** run `python ../scripts/seed_merchant.py` on Render.
The repository-root wrapper remains available for local development.
Shell is available on the selected paid web-service plan, not free web services.
If you change to Free, you will need to return to a Shell-capable plan to use
these instructions; do not add seeding to every server startup.

## 5. Verify the hosted application

1. Open the static-site URL and sign in using the seeded merchant account.
2. Confirm the transactions page loads. A new database should show an empty state.
3. In browser developer tools, confirm API requests go to the API service and
   carry `Authorization: Bearer ...`. Never copy tokens into issue reports.
4. Check that an unauthenticated request to `/api/transactions` returns 401.
5. Complete a payment using a separate Sandbox buyer account and confirm the
   table shows VERIFIED only after backend capture verification. This is still
   a pending live checkout acceptance check; deployment preparation did not run it.
6. Log out, confirm the login screen returns, then test a page reload.
7. Record the actual public health and frontend URLs in README.md only after
   confirming them. No URLs are invented in this preparation task.

If login fails with a CORS error, compare the browser's exact origin with
FRONTEND_ORIGIN. If API calls hit the static site, set VITE_API_URL to the backend
origin and rebuild the frontend. If PayPal fails to load, verify the frontend
and backend use the same Sandbox app and rebuild after changing its public ID.
`sync: false` values added to an existing Blueprint later should be set manually
in that service's Environment page before redeploying.

## References

- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Monorepo roots and relative build paths](https://render.com/docs/monorepo-support)
- [Render Shell access and supported plans](https://render.com/docs/ssh)
- [Deploy FastAPI](https://render.com/docs/deploy-fastapi)
