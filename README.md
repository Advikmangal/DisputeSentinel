# PayoutSentinel

A payment evidence and dispute-response workspace for digital-service merchants.
Built with React, TypeScript, FastAPI, PostgreSQL, PayPal Sandbox, and Gemini.

## What it does

1. Create a PayPal Sandbox order and verify its capture on the server.
2. Attach private PDF delivery records, agreements, communications, or usage logs.
3. Use Gemini to extract facts with exact document/page quotations.
4. Inspect a deterministic evidence-coverage checklist and conflicting evidence.
5. Sync disputes, generate a cited draft, edit it, approve it, and export Markdown.

The Dashboard, Payments, Evidence Vault, and Dispute Agent share one authenticated
merchant workspace. The dashboard uses database records and supports filtering by
coverage. Payment retries reuse the original order; signed webhooks reconcile
completed captures without initiating another payment.

**Demo boundaries:** PayPal is Sandbox only. Fixture disputes are labeled Simulated.
Exports are never submitted to PayPal. Coverage is not a probability of winning.
Quotation matching confirms source text, not document authenticity or AI accuracy.
The draft is assembled deterministically from AI-extracted quotations; there is no
unconstrained model-generated dispute narrative.

## Try the public demo

Open https://payoutsentinel-web-nf5z.onrender.com/ and choose **Create an account**.
Register with an email and a 12-128 character password, then enter your own workspace
automatically. Three clearly labeled simulated transactions are included so you can
try Evidence Vault and fixture dispute workflows without making a Sandbox payment.
Existing accounts can sign in normally. Sample transactions cannot be captured.

Registration is `POST /api/auth/register` with `email` and `password`; it returns
the same bearer-token response as login. Duplicate emails return 409. Passwords
are salted and hashed with scrypt; workspace ownership is enforced by merchant ID.
Signup is limited per process to five attempts per client address and thirty total
per minute (429 with Retry-After). This basic demo limit resets on restart and is
not a distributed abuse-prevention system. Email ownership is not verified and
password reset is not provided. Use synthetic documents, not sensitive information.
All checkouts use the project's shared PayPal Sandbox app; signup does not link a
visitor's own merchant PayPal account. No real money moves.

## Run locally

Requirements: Python 3.12, Node 22.12+ or 24, PostgreSQL.

```sh
cp .env.example .env
# Fill the private .env values described below.
python -m venv backend/.venv
# Activate backend/.venv using your platform's activation script.
pip install -r backend/requirements.txt
cd backend
python -m alembic upgrade head
python -m app.seed_merchant
python -m uvicorn app.main:app --reload
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the Vite URL, normally http://localhost:5173. On Windows, activate the backend
with `backend\.venv\Scripts\Activate.ps1`. Never overwrite an existing `.env` when
updating your checkout.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string; never a browser variable |
| `JWT_SECRET` | Random secret of at least 32 characters |
| `DEMO_MERCHANT_EMAIL`, `DEMO_MERCHANT_PASSWORD` | Initial merchant; password at least 12 characters |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | Credentials for the same Sandbox REST application |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` only |
| `PAYPAL_WEBHOOK_ID` | Registered Sandbox webhook ID for verified notifications |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Valid key and a structured-output model available to your account |
| `DISPUTE_SOURCE` | `fixture` for labeled simulated cases, or `paypal` for matched Sandbox disputes |
| `FRONTEND_ORIGIN` | Exact frontend origin, no trailing slash |
| `ENVIRONMENT` | `development` locally; `production` on Render |
| `VITE_API_URL` | Empty locally; backend HTTPS origin for hosted builds |

The checkout fetches its public client ID from `/api/payments/config`; no separate
frontend PayPal ID is needed. Never put secrets in `VITE_` variables. The seed is
insert-only: changing the password environment variable does not reset an existing
merchant's password.

## Evidence and scoring

PDFs are stored in PostgreSQL BYTEA, not temporary server storage. Limits are 10 MB,
50 pages, and 100,000 extracted characters per document; 10 documents and 100,000
combined characters per analysis. Scanned/image PDFs require OCR before upload.
Analysis sends extracted text to Google Gemini and atomically replaces facts only
after a valid response. Fabricated excerpts, wrong pages, and wrong document IDs
are rejected. Provider failures preserve the previous analysis.

Coverage weights: delivery 30, buyer communication 20, agreement 20, verified payment
15, access logs 15. Strong extracted support receives the category's points;
weak support receives half (rounded down); contradictory evidence flags review and
receives zero. Payment coverage comes from server-verified status. Users must review
AI classification and source relevance.

Existing PDFs from the earlier page-string storage format remain readable. Editing
a response invalidates approval; approval and export validate its source quotations.
Audit records track upload, analysis, drafting, edits, approvals, exports, and syncs.

## Tests

```sh
cd backend
python -m pytest -q
cd ../frontend
npm run build
node --test tests/api.test.mjs
```

GitHub Actions also runs `scripts/check_postgres.py` against a disposable PostgreSQL
service, covering migrations, constraints, binary storage, and concurrent payment
retries. Do not point that destructive acceptance script at an application database.

API documentation: `/docs` and `/openapi.json` on the backend; endpoint guide in
[docs/api.md](docs/api.md). Import [docs/postman_collection.json](docs/postman_collection.json)
into Postman. Deployment and hosted acceptance: [docs/DEPLOY.md](docs/DEPLOY.md).

## Portfolio scope and remaining limits

This is a public portfolio demo with separate merchant workspaces, not a production
payment processor. It does not provide email verification, password reset, live payments, OCR, automatic
PayPal response submission, or background AI jobs. Sandbox dispute sync is bounded
to ten pages per invocation. Capture webhooks are verified and deduplicated; dispute
updates use explicit sync. Keep demo credentials private, and use synthetic documents
for public demonstrations.

MIT license. AI coding assistance was used in implementation; Gemini performs
runtime evidence extraction. No real payment or hosted AI success is implied by
mocked tests.
