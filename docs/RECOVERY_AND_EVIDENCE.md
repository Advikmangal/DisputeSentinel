# Payment recovery and evidence workflow

This update implements runtime PayPal configuration, payment recovery from the transaction list, database readiness, signed payment webhook reconciliation, PDF evidence storage, Gemini quotation extraction, deterministic coverage scoring, dispute review and Markdown exports.

## Deployment

- Keep the existing Sandbox `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` on the backend. Checkout retrieves only the public client ID from authenticated `GET /api/payments/config`. `VITE_PAYPAL_CLIENT_ID` is no longer used.
- Keep `VITE_API_URL` and `FRONTEND_ORIGIN` pointing to the existing services.
- `/health` remains process liveness; `/ready` checks connectivity and the core migrated tables and returns 503 on failure. The browser probes `/ready`, and the Blueprint health check uses it.
- Register `https://<backend-origin>/api/webhooks/paypal` on the same Sandbox REST application for `PAYMENT.CAPTURE.COMPLETED`. Set its registration ID as `PAYPAL_WEBHOOK_ID`. Missing configuration fails closed with 503; unsigned deliveries fail with 400. Real signed deliveries are required; PayPal simulator events do not support postback verification.
- Set `GEMINI_API_KEY`. `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite` and may be overridden with a supported model for the account.
- No schema migration is needed: the existing nine tables are used. Two dependencies are added: python-multipart and pypdf.

## Behavior

- Every non-demo CREATED transaction has Retry verification, including after page reload. Retries target the existing order. Never create a replacement payment simply because verification timed out.
- API calls have a 90-second client deadline covering fetch and response decoding. They never automatically replay mutations. Aborting the browser request does not cancel an already-running server operation.
- Signed webhooks reconcile by fetching the PayPal order, validating it against local amount/currency and capture ID, and atomically marking the event processed. They never invoke capture. Failed reconciliation remains retryable. Other signed event types are logged without mutating payment status; refunds and reversals are not modeled by the current CREATED/VERIFIED schema.
- Evidence PDFs are stored in Postgres. Files are limited to 10 MB, 50 pages and 100,000 extracted characters, with up to 10 files per transaction. Scans without a text layer are rejected with an OCR explanation. All document routes enforce transaction ownership; download is authenticated.
- Analyze sends extracted text to Google Gemini only when invoked. Excerpts must match the cited page exactly. Unsupported quotations are discarded. Scores assign 20 points to each supported checklist category with confidence >= 0.7. Payment-match coverage additionally requires a locally verified capture ID in the quotation. Scores measure document coverage, not claim truth or outcome probability.
- Uploading new evidence invalidates the previous score. Model failure leaves the last successful analysis unchanged.
- Fixture mode creates one labeled simulated dispute per selected transaction. PayPal mode inspects the first page (50 disputes), matches capture ID and amount/currency, and imports only matches owned by the signed-in merchant. This is explicitly not a full-history sync.
- Drafts quote validated extracted facts. Edits reset approval; approval is audited. Export requires approval and is repeatable. All responses export Markdown; no automated PayPal submission is implemented. Simulated exports are labeled. Merchant edits are not semantically fact-checked.

## Validation

Backend regression tests cover signature rejection, event deduplication, failed-delivery recovery, ownership, public configuration, readiness failure, PDF rejection, citation filtering and the draft/edit/approve/export lifecycle. Existing mock payment tests and frontend API/build checks also run. These do not establish live PayPal capture, delivery of registered webhooks or account-specific Gemini availability.

References: [PayPal webhook integration](https://developer.paypal.com/api/rest/webhooks/rest/), [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).
