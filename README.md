# DisputeSentinel

PayPal Sandbox payment evidence and dispute management for digital-service merchants.
Implemented: the scaffold, PayPal Sandbox REST service, T2.1 database models and
migration, and T2.2 payment/transaction endpoints. The frontend remains a placeholder.
The source-of-truth implementation plan is [PAYOUTSENTINEL_PLAN.md](PAYOUTSENTINEL_PLAN.md),
with architecture in [docs/DIAGRAMS.md](docs/DIAGRAMS.md).

## Local setup (PowerShell)

Use Python **3.12.11** and Node.js **22.12+** (validated with Node.js 24).
From the repository root:

```powershell
Copy-Item .env.example .env
cd backend
uv venv --python 3.12.11 --seed .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The setup command uses the `uv` Python environment manager to select the exact
Python version. If you already have native Python 3.12.11, you can instead use
that interpreter's `-m venv .venv` command.

Health: http://127.0.0.1:8000/health returns `{"status":"ok"}`.
API docs: http://127.0.0.1:8000/docs.
Settings load the root `.env`, with environment variables taking precedence.
The health endpoint needs no credentials or database connection. Replace placeholders
only in your private `.env` when implementing the later integrations; never commit it.
Only the PayPal Sandbox base URL is accepted by settings.

In a second terminal, from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally http://localhost:5173).
The four navigation items are disabled placeholders. No frontend/backend integration
is implemented yet, and no credentials belong in frontend environment variables.

Production build check:

```powershell
cd frontend
npm run build
```

Future integration settings (webhook ID, Gemini model, dispute source, upload
directory, frontend origin) are listed in `.env.example`; their services are not
implemented in this scaffold. The plan uses Postgres BYTEA for production uploads.

## T1.2 PayPal Sandbox check

Set `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` in your private root `.env`.
Use credentials from a Sandbox REST app. From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe scripts/paypal_smoke.py --request-id YOUR-UNIQUE-REQUEST-ID
```

This creates a USD 1.00 Sandbox order, prints its approval link, and lists one
page of disputes. It does not approve or capture a payment. Reuse the same request
ID for retries of the same check; choose a new ID for a new order. PayPal retains
idempotency IDs for a limited time, so do not treat them as permanent deduplication.
An empty dispute list is a successful access check, not proof that a dispute can
be created. The dispute-source decision belongs to T1.4.

`PayPalClient` is a synchronous context manager with a 30-second HTTP timeout.
Reuse an instance to benefit from its locked, expiry-aware OAuth token cache.
It refreshes once after an HTTP 401; other errors are surfaced without automatic
retries or response-body logging. Call it from synchronous routes or a worker
thread when async routes are introduced.

Creation requires a caller-supplied idempotency key. Capture derives a stable key
from the order ID and returns an already completed order without another capture.
The PayPal REST client returns raw data. The payment service now verifies a fresh
order fetch after capture and persists a VERIFIED transaction only when the order
and capture IDs, completed statuses, amounts and currencies agree with stored data.

Tests use `httpx.MockTransport`; external network connections are blocked during
unit tests. Gemini is not invoked by T1.2. Run tests from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

API references: [OAuth](https://developer.paypal.com/api/rest/authentication),
[Orders](https://developer.paypal.com/api/orders/v2),
[Disputes](https://developer.paypal.com/api/customer-disputes/v1), and
[idempotency](https://developer.paypal.com/api/rest/reference/idempotency/).

## T2.1 / T2.2 database and payments

Dependencies added for these tasks: SQLAlchemy 2.x and Alembic (both planned),
plus the required PostgreSQL driver `psycopg[binary]`. No database or credentials
are bundled. Set `DATABASE_URL` in the private root `.env` or environment.
`postgresql://` and `postgresql+psycopg://` URLs are accepted; the backend uses
psycopg 3. The application does not create tables automatically.

From `backend`, install requirements and migrate your development database:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
```

On a disposable database only, reverse the initial migration using
`.\.venv\Scripts\python.exe -m alembic downgrade base`; it removes all nine tables
and their data. `alembic check` verifies that models match the migrated schema.
Evidence bytes compile to PostgreSQL BYTEA; JSON fields and all planned unique
PayPal-ID constraints are included. No actual evidence/upload API is built yet.

JWT authentication is scheduled for T3.1. Payment routes currently return 503 unless
`DEMO_MERCHANT_ID` is explicitly set to an existing merchant and the connection
is from loopback. For local development, create a non-login merchant in your local
database with this SQL and use the returned ID:

```sql
INSERT INTO merchants (email, password_hash)
VALUES ('merchant@example.invalid', '!login-disabled-until-T3.1')
RETURNING id;
```

`password_hash` here is a disabled marker, not a password or usable login hash.
Set `DEMO_MERCHANT_ID` to that ID in your terminal environment, then run Uvicorn
bound to `127.0.0.1` with `--no-proxy-headers`. This bridge is not authentication;
leave it unset on hosted deployments and replace it with JWT in T3.1.

The four implemented endpoints are listed in [docs/api.md](docs/api.md).
Create requires `Idempotency-Key` (1–38 letters, digits, underscores or hyphens).
Use the same key and payload for retries. It reserves the key/payload in the
existing audit table before contacting PayPal, and retains the resulting local
transaction/approval URL for replay. Unfinished requests older than five hours
require reconciliation instead of risking a second remote order after PayPal's
idempotency retention expires. Merchant-row locks serialize creates; transaction-row
locks serialize captures across backend processes. Keep network calls bounded by
the PayPal client's timeout. Capture errors leave the local order CREATED so a
retry can reconcile a capture that may already have succeeded remotely.

Unit tests use in-memory SQLite only for isolation and mock PayPal HTTP with
`httpx.MockTransport`; they do not contact Postgres, PayPal or Gemini. PostgreSQL
migration and concurrency acceptance is a separate check. Set `TEST_DATABASE_URL`
in the environment to a **fresh disposable PostgreSQL database**, then run from
the repository root:

```powershell
.\backend\.venv\Scripts\python.exe scripts/check_postgres.py
```

The check refuses an existing schema, upgrades, verifies all tables/constraints
and BYTEA storage, exercises concurrent creation/capture with mocked PayPal, then
downgrades to base. It repeats the migration cycle and leaves the database empty.

## License

MIT; see [LICENSE](LICENSE).
