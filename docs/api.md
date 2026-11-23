# API guide

All `/api` routes require a merchant bearer JWT except login and the signed PayPal
webhook receiver. `/health` reports process liveness; `/ready` checks database access.
FastAPI `/docs` and `/openapi.json` contain generated request schemas.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/api/auth/login` | JSON email/password; returns token |
| GET | `/api/payments/config` | Public Sandbox client ID, never the secret |
| POST | `/api/payments/create-order` | JSON amount/currency/description and `Idempotency-Key` |
| POST | `/api/payments/capture` | JSON order_id; verifies remotely before persisting |
| GET | `/api/transactions` | Current merchant's transactions |
| GET | `/api/transactions/{id}` | Owned transaction details |
| POST | `/api/transactions/{id}/evidence?filename=delivery.pdf` | Raw PDF body, `Content-Type: application/pdf`; not multipart |
| GET | `/api/transactions/{id}/evidence` | Document metadata and extracted facts |
| GET | `/api/evidence/{document_id}/download` | Authenticated original PDF download |
| POST | `/api/transactions/{id}/analyze` | Source-checked Gemini extraction and deterministic score |
| GET | `/api/transactions/{id}/readiness` | Current coverage, breakdown, missing items |
| POST | `/api/disputes/sync` | Bodyless; sync owned transactions from configured source |
| GET | `/api/disputes` | Owned cases with latest response |
| POST | `/api/disputes/{id}/draft` | New cited response version; no-evidence message when insufficient |
| PUT | `/api/disputes/{id}/response` | JSON draft_text; edits invalidate approval |
| POST | `/api/disputes/{id}/approve` | Validate citations and record merchant approval |
| GET | `/api/disputes/{id}/export` | Approved Markdown attachment; never submits to PayPal |
| GET | `/api/dashboard/summary` | Merchant totals, cases, coverage |
| POST | `/api/webhooks/paypal` | Original event JSON and PayPal signature headers |

## Client upgrade notes

The dedicated workspace replaces the old embedded evidence/dispute panels. Upload
uses raw PDF bytes, sync takes no transaction_id body, and analysis returns coverage
directly. Download is `/api/evidence/{document_id}/download`. Export uses the explicit
`/export` route instead of the old `/submit` export alias. Deploy frontend and backend
together. Existing database tables and evidence are retained; no new migration is
required for this release. Historical JSON files under `fixtures/api` describe the
original design and are not the current API contract.

## Errors and limits

401: missing/expired login or invalid authorization. 404: unavailable or non-owned
resource. 409: invalid workflow state, document limit, or idempotency conflict.
413: oversized payload. 415: unsupported media type. 422: unreadable/unsupported
PDF or invalid input. 502/503: upstream unavailable or configuration missing.

A timed-out payment request may have succeeded remotely. Retry verification for the
same order rather than creating a replacement payment. Analysis errors preserve old
facts. Fixture cases and exported documents stay labeled Simulated. Webhooks require
a registered ID and signature verification; duplicate notifications are safe no-ops.
