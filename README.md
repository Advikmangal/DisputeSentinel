# DisputeSentinel

PayPal Sandbox payment evidence and dispute management for digital-service merchants.
Implemented: the T1.1 scaffold and the T1.2 PayPal Sandbox REST service.
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
The four navigation items are disabled placeholders. No backend integration is
implemented yet, and no credentials belong in frontend environment variables.

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
The service returns raw PayPal data: database uniqueness constraints (T2.1), and
server-side amount/currency/capture verification before persisting a verified
transaction (T2.2), are still required. No payment endpoints are exposed yet.

Tests use `httpx.MockTransport`; external network connections are blocked during
unit tests. Gemini is not invoked by T1.2. Run tests from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

API references: [OAuth](https://developer.paypal.com/api/rest/authentication),
[Orders](https://developer.paypal.com/api/orders/v2),
[Disputes](https://developer.paypal.com/api/customer-disputes/v1), and
[idempotency](https://developer.paypal.com/api/rest/reference/idempotency/).

## License

MIT; see [LICENSE](LICENSE).
