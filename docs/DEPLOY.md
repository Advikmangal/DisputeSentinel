# Deploy on Render Free only

This is deployment preparation; no hosted deployment has been verified. All three
resources in `render.yaml` are free: the database and API declare `plan: free`;
the static site is inherently free and does not support a `plan` field. There is no disk, pre-deploy
command, paid worker, or paid service. Keep the workspace on the free Hobby plan.
Do not attach a payment method for this demo: bandwidth/build overages can be
charged when one exists. Without one, excess usage suspends services/builds.
If Render asks for a paid upgrade, stop instead of choosing it.

## 1. Create the Blueprint

1. Push this commit to `Advikmangal/DisputeSentinel`, branch `master`.
2. Sign in at https://dashboard.render.com and select your free workspace.
3. Click **New > Blueprint**, connect GitHub, and select **DisputeSentinel**.
4. Select branch **master**, Blueprint path **render.yaml**, and a name for the Blueprint.
5. Review the resources: **payoutsentinel-db** (Free Postgres),
   **payoutsentinel-api** (Free Python web service), and **payoutsentinel-web**
   (free static site). Confirm there are no paid resources or disks.
6. Enter the environment values below privately in Render. Never put credentials
   in the repository, screenshots, support logs, or chat.
7. Click **Deploy Blueprint**. Watch each service's **Events** and **Logs**.

The API uses `backend` as its root, Python **3.12.11**, and
`pip install -r requirements.txt` as its build command. Its start command is:

```sh
alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Every start applies migrations, validates production settings, and creates the
merchant if missing before accepting requests. Startup failure prevents a healthy
deployment. There is no Shell or pre-deploy step. An existing merchant's password
is never changed by seeding, including after changing the environment password.

## 2. Enter environment values

The Blueprint uses `sync: false` for manually supplied variables. It contains no
credentials. Set the API service values as follows:

| Variable | Value to enter privately |
| --- | --- |
| PAYPAL_CLIENT_ID | Sandbox REST application's client ID |
| PAYPAL_CLIENT_SECRET | Same Sandbox application's secret |
| PAYPAL_BASE_URL | `https://api-m.sandbox.paypal.com` only |
| GEMINI_API_KEY | Your Gemini API key |
| JWT_SECRET | Independently generated random secret, at least 32 characters; no placeholder |
| DEMO_MERCHANT_EMAIL | Email you will use to sign in |
| DEMO_MERCHANT_PASSWORD | Strong password of 12–1024 characters; no default |
| FRONTEND_ORIGIN | Exact frontend HTTPS origin, no path or trailing slash |

`DATABASE_URL` is wired to the database's internal connection string by the
Blueprint. Do not replace it with a local file or SQLite URL. The app converts
`postgres://` and `postgresql://` into `postgresql+psycopg://`. The Blueprint also
sets `ENVIRONMENT=production`, `PYTHON_VERSION=3.12.11`, and
`DISPUTE_SOURCE=fixture`. Missing/short JWT secrets prevent production startup.
CORS permits only `FRONTEND_ORIGIN`; there is no wildcard.

For the static frontend:

| Variable | Value |
| --- | --- |
| VITE_API_URL | API HTTPS origin without a trailing slash or `/api` suffix |
| VITE_PAYPAL_CLIENT_ID | Public client ID of the same Sandbox app |

Vite embeds these two public values at build time. Never use a secret in a
`VITE_` variable. The build is `npm ci && npm run build`, published from `dist`
under root `frontend`. The `/*` rewrite serves `/index.html` for SPA routes.

## 3. Wire the assigned URLs

1. If URLs are unknown during creation, use `https://frontend.example.invalid`
   and `https://api.example.invalid` temporarily for the two origins.
2. Open **payoutsentinel-api** and copy its assigned HTTPS URL.
3. Open **payoutsentinel-web > Environment > Edit**, set `VITE_API_URL` to that
   API origin, and choose **Save, rebuild, and deploy**.
4. Copy the static site's assigned HTTPS URL. Open **payoutsentinel-api >
   Environment > Edit**, set `FRONTEND_ORIGIN` to that exact origin, and save
   with redeployment. Do not leave the temporary origins in place.
5. Open the API URL followed by `/health`; expect HTTP 200 and `{"status":"ok"}`.
6. Open the frontend, sign in using the configured demo merchant, and confirm
   the transactions page loads. An empty list is expected until a payment or
   the optional synthetic rebuild below. Logged-out API requests must get 401.
7. Approve a small Sandbox payment with a Sandbox buyer distinct from the
   seller. Success is shown only after the backend returns `VERIFIED`.

After idle time, the first API operation probes `/health`. If slow, the UI says
**Waking up the server, this can take a minute** and retries the health check.
Create/capture POSTs are sent only after readiness, not automatically replayed by
this retry loop. After bounded retries, a clear error allows a manual retry.

## 4. Rebuild demo data without Render Shell

This optional local command restores the merchant plus three synthetic sample
transactions. It also applies migrations to an empty database. Rows have
`DEMO-` order IDs, `[DEMO - SIMULATED]` descriptions, and `is_demo: true` in API
responses. They stay `CREATED`, have no capture ID, display a Demo label, and
cannot be captured. They are not proof of a PayPal payment. Rerunning preserves
all existing transactions and passwords and adds only missing demo rows.

1. On your computer, install the existing backend requirements in its Python
   3.12.11 virtual environment if not already installed.
2. In Render, open the Postgres database and its **Networking** access controls.
   The Blueprint initially blocks external access (`ipAllowList: []`). Temporarily
   allow only your current public IP with `/32`; never allow `0.0.0.0/0`.
3. In the database's **Info/Connections** section, copy its **External Database
   URL** privately. Set it as `DATABASE_URL` in the local process environment,
   with TLS (`sslmode=require`). Set `DEMO_MERCHANT_EMAIL` and
   `DEMO_MERCHANT_PASSWORD` in that same process environment. Use your secret
   manager or secure prompt; do not save real values in a file or shell history.
4. From the repository root, run this one command:

```powershell
.\backend\.venv\Scripts\python.exe scripts/seed_demo_data.py
```

5. Expect `Demo data ready: 3 synthetic transactions added; existing records
   unchanged.` A repeat reports 0 added. Refresh the frontend transaction list.
6. Remove your temporary external IP rule in Render and clear the local process
   environment values. Keep the hosted API on its internal database URL.

## 5. When the free database expires

Free Postgres expires after **30 days**, has **1 GB** storage, and permits only
one active free database per workspace. It is not a permanent store for this demo.
Rebuilding sample data cannot recover expired payment history or evidence.

1. In the Blueprint, replace the expired database resource name with a new unique
   name in both `databases[].name` and the API's `DATABASE_URL.fromDatabase.name`.
   Keep `plan: free`, region, and all other resource plans unchanged.
2. Commit/push that configuration and open **Blueprint > Manual Sync**. Review
   the proposed new database as **Free** before applying. If the expired database
   blocks creation, remove only that expired database after confirming its data
   is no longer needed; never delete an active database to bypass the limit.
3. Wait for the replacement database, then redeploy the API. The Blueprint wires
   its new internal URL. Startup migrates it and creates the demo merchant from
   the existing environment settings.
4. Repeat section 4 against the replacement database to restore synthetic rows.
   Perform a new Sandbox checkout if you need a genuinely VERIFIED transaction.

## Free-tier operating limits

The API sleeps after **15 minutes** idle and takes about a minute to wake. Free
web services have no Shell, SSH, one-off jobs, or persistent disk. All persistent
application data belongs in Postgres; future evidence belongs in BYTEA, not local
uploads. The workspace shares **750 free instance hours/month**. Monitor usage
under **Billing > Monthly Included Usage**; accept suspension instead of upgrading.

Sources: [Render Free limits](https://render.com/docs/free) and
[Blueprint reference](https://render.com/docs/blueprint-spec). Check the deployment
review screen before applying; no paid fallback is authorized.
