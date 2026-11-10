# PayoutSentinel planned API reference

> Updated implementation and deployment instructions: [RECOVERY_AND_EVIDENCE.md](RECOVERY_AND_EVIDENCE.md). This update supersedes the scaffold-only status and build-time PayPal configuration below.


Status: T3.1 implements POST /api/auth/login. T2.2 implements POST /api/payments/create-order, POST /api/payments/capture, GET /api/transactions and GET /api/transactions/{id}. All other routes remain T1.3 proposed mock contracts. Based on section 6 of PAYOUTSENTINEL_PLAN.md and docs/DIAGRAMS.md. All 17 planned routes below use `/api`. The four payment/transaction DTOs are implemented; remaining shapes are proposals for later tasks, not database schema changes.

## Current T2.2 behavior

The payment routes use uppercase `CREATED` and `VERIFIED` statuses. Login returns
an HS256 JWT with `expires_in: 43200` (12 hours). Passwords are stored as salted
scrypt hashes. All implemented API routes require a valid bearer token except
login. Missing, invalid or expired tokens return 401 with `WWW-Authenticate:
Bearer`. Transaction ownership is taken from the signed JWT subject; requests
for another merchant's transaction return 404. There is no demo-access bypass.
The future `/api/webhooks/paypal` route is exempt from JWT only, and must implement
signature verification before processing any event. Authentication error bodies
currently use FastAPI's string `detail` form; the structured errors below remain
planned examples where not yet implemented.

Create requires `Idempotency-Key`. Keys are scoped to the configured merchant and
reserved durably in `audit_log` with a payload fingerprint before calling PayPal.
A matching completed retry returns the same transaction (201); changed payloads
return 409 `idempotency_conflict`. An unfinished reservation older than five hours
returns 409 `reconciliation_required`. Both create and capture send stable PayPal
request IDs. Database row locks serialize concurrent operations.

Capture accepts only `order_id`; extra client status/amount/success fields are
rejected. A successful capture is followed by a separate PayPal order fetch.
Order ID, intent, order/capture completion, order/capture amounts and currencies
must match the stored transaction. Duplicate verified capture returns 200 with
the existing record and no PayPal call. Unknown local order is 404; PayPal state
conflict (including unapproved order) or verification mismatch is 409; upstream
failures, timeouts and malformed data are sanitized 502 responses. These are the
implemented codes; 504 below remains a future proposed timeout distinction.
FastAPI validation currently retains its standard 422 `detail` list; domain
errors use the structured code/message envelope shown below. JSON timestamps
are normalized to UTC. Missing database setup is an operational configuration
error; apply migrations before using the payment routes.

## Shared conventions

- Merchant endpoints require `Authorization: Bearer <JWT>` except login. Webhooks require PayPal signature verification instead. The planned login route is necessarily public.
- Local path `{id}` values are positive integer IDs scoped to the authenticated merchant. Use `1` for these examples. Return 404 for absent or inaccessible resources.
- JSON is the default content type; evidence upload uses multipart/form-data. A JSON `null` request sample means no body. Empty `{}` means a JSON object with no parameters.
- Amounts are decimal strings with explicit currency; timestamps use UTC ISO 8601. No raw PDF bytes, storage paths, credentials, or real IDs are exposed.
- Every sample is synthetic unless explicitly labeled as a redacted observed subset. All simulated disputes include `is_fixture: true`; render them as **Simulated**, including nested draft/approval/export views.
- Generic errors use `{"detail":{"code":"...","message":"..."}}` in this proposed contract. Framework validation errors will need normalization during implementation. Error messages must not include credentials or raw upstream bodies. Unexpected internal failures return a sanitized 500.
- The create-order `Idempotency-Key` is a proposed application header mapped to PayPal request IDs. Capture and webhook processing require unique stored PayPal IDs and safe replays. Application idempotency reservations now use the existing audit_log table; no extra table was introduced.
- The fixture score uses illustrative equal weights; finalize deterministic checklist weights in T3.4/T4.3. No extraction or scoring ran to generate these examples.
- Approval/edit/export behaviors here preserve merchant approval and the lifecycle in the diagrams. Actual submission remains conditional Sandbox functionality.

## Coverage

| Method | Path | Fixture |
|---|---|---|
| POST | `/api/auth/login` | [auth-login.json](../fixtures/api/auth-login.json) |
| POST | `/api/payments/create-order` | [payments-create-order.json](../fixtures/api/payments-create-order.json) |
| POST | `/api/payments/capture` | [payments-capture.json](../fixtures/api/payments-capture.json) |
| GET | `/api/transactions` | [transactions-list.json](../fixtures/api/transactions-list.json) |
| GET | `/api/transactions/{id}` | [transactions-detail.json](../fixtures/api/transactions-detail.json) |
| POST | `/api/transactions/{id}/evidence` | [evidence-upload.json](../fixtures/api/evidence-upload.json) |
| GET | `/api/transactions/{id}/evidence` | [evidence-list.json](../fixtures/api/evidence-list.json) |
| POST | `/api/transactions/{id}/analyze` | [evidence-analyze.json](../fixtures/api/evidence-analyze.json) |
| GET | `/api/transactions/{id}/readiness` | [readiness-get.json](../fixtures/api/readiness-get.json) |
| GET | `/api/disputes` | [disputes-list.json](../fixtures/api/disputes-list.json) |
| POST | `/api/disputes/sync` | [disputes-sync.json](../fixtures/api/disputes-sync.json) |
| POST | `/api/disputes/{id}/draft` | [disputes-draft.json](../fixtures/api/disputes-draft.json) |
| PUT | `/api/disputes/{id}/response` | [disputes-edit-response.json](../fixtures/api/disputes-edit-response.json) |
| POST | `/api/disputes/{id}/approve` | [disputes-approve.json](../fixtures/api/disputes-approve.json) |
| POST | `/api/disputes/{id}/submit` | [disputes-submit.json](../fixtures/api/disputes-submit.json) |
| GET | `/api/dashboard/summary` | [dashboard-summary.json](../fixtures/api/dashboard-summary.json) |
| POST | `/api/webhooks/paypal` | [webhooks-paypal.json](../fixtures/api/webhooks-paypal.json) |

## POST /api/auth/login

Authenticate the demo merchant. Tokens and expiration shown here are illustrative; no usable credentials are included.

**Auth:** none.

**Sample:** [request, response and error bodies](../fixtures/api/auth-login.json).

**Request headers:**
```json
{
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{
  "email": "merchant@example.invalid",
  "password": "<PASSWORD_PLACEHOLDER>"
}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "access_token": "<JWT_PLACEHOLDER>",
  "token_type": "bearer",
  "expires_in": 43200
}
```

**Error cases:** 401: invalid credentials; 422: invalid email or missing password.
Machine-readable error body samples are in the linked fixture.

## POST /api/payments/create-order

Create a CAPTURE-intent Sandbox order and persist its ID. The approval URL shape matches the T1.2 smoke output; the ID is replaced. Amount is a decimal string, not a float.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/payments-create-order.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json",
  "Idempotency-Key": "example-create-order-001"
}
```

**Request body:**
```json
{
  "amount": "1.00",
  "currency": "USD",
  "description": "Simulated digital-service delivery"
}
```

**Response:** HTTP 201; `Content-Type: application/json`.
```json
{
  "transaction": {
    "id": 1,
    "merchant_id": 1,
    "paypal_order_id": "SANDBOX-ORDER-EXAMPLE",
    "paypal_capture_id": null,
    "amount": "1.00",
    "currency": "USD",
    "status": "CREATED",
    "payer_email": null,
    "description": "Simulated digital-service delivery",
    "created_at": "2026-11-03T10:00:00Z",
    "captured_at": null
  },
  "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=SANDBOX-ORDER-EXAMPLE"
}
```

**Error cases:** 422: invalid amount/currency; 409: same idempotency key with different payload; 502/504: PayPal failure/timeout. Reuse the same key and payload after uncertain outcomes.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/payments/capture

Capture a merchant-owned order; fetch from PayPal and compare stored amount/currency, order ID and completed capture status before marking verified. Repeated successful captures return the existing transaction with 200 and no duplicate row.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/payments-capture.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{
  "order_id": "SANDBOX-ORDER-EXAMPLE"
}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "id": 1,
  "merchant_id": 1,
  "paypal_order_id": "SANDBOX-ORDER-EXAMPLE",
  "paypal_capture_id": "SANDBOX-CAPTURE-EXAMPLE",
  "amount": "1.00",
  "currency": "USD",
  "status": "VERIFIED",
  "payer_email": "buyer@example.invalid",
  "description": "Simulated digital-service delivery",
  "created_at": "2026-11-03T10:00:00Z",
  "captured_at": "2026-11-03T10:05:00Z"
}
```

**Error cases:** 404: unknown or another merchant’s order; 409: unapproved order, amount/currency mismatch or non-completed capture; 422: invalid ID; 502/504: PayPal failure/timeout. Never accept amount or success assertions from the browser.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## GET /api/transactions

List only the authenticated merchant’s transactions. Empty result: {"items": []}. No query parameters are specified for this initial contract.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/transactions-list.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>"
}
```

**Request body:**
```json
null
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "items": [
    {
      "id": 1,
      "merchant_id": 1,
      "paypal_order_id": "SANDBOX-ORDER-EXAMPLE",
      "paypal_capture_id": "SANDBOX-CAPTURE-EXAMPLE",
      "amount": "1.00",
      "currency": "USD",
      "status": "VERIFIED",
      "payer_email": "buyer@example.invalid",
      "description": "Simulated digital-service delivery",
      "created_at": "2026-11-03T10:00:00Z",
      "captured_at": "2026-11-03T10:05:00Z"
    }
  ]
}
```

**Error cases:** No request body. 401: missing/invalid JWT.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## GET /api/transactions/{id}

Fetch a merchant-owned transaction. Path id is a positive local integer; use 1 for this sample.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/transactions-detail.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>"
}
```

**Request body:**
```json
null
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "id": 1,
  "merchant_id": 1,
  "paypal_order_id": "SANDBOX-ORDER-EXAMPLE",
  "paypal_capture_id": "SANDBOX-CAPTURE-EXAMPLE",
  "amount": "1.00",
  "currency": "USD",
  "status": "VERIFIED",
  "payer_email": "buyer@example.invalid",
  "description": "Simulated digital-service delivery",
  "created_at": "2026-11-03T10:00:00Z",
  "captured_at": "2026-11-03T10:05:00Z"
}
```

**Error cases:** No request body. 404: absent or inaccessible transaction; 422: invalid path ID.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/transactions/{id}/evidence

Upload a PDF for transaction 1 using multipart/form-data field file. The JSON request body is a descriptor of multipart parts, not a JSON payload to send. Max 10 MB; validate actual PDF content. Store bytes in Postgres file_data and extract page text. The PDF itself is not included in this task.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/evidence-upload.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "multipart/form-data; boundary=<GENERATED_BY_CLIENT>"
}
```

**Request body:**
```json
{
  "file": {
    "filename": "simulated-delivery.pdf",
    "content_type": "application/pdf",
    "content": "<BINARY_PDF_BYTES>"
  }
}
```

**Response:** HTTP 201; `Content-Type: application/json`.
```json
{
  "id": 1,
  "transaction_id": 1,
  "filename": "simulated-delivery.pdf",
  "mime_type": "application/pdf",
  "size": 2048,
  "uploaded_at": "2026-11-03T10:10:00Z"
}
```

**Error cases:** 404: transaction absent/inaccessible; 413: too large; 415: non-PDF; 422: missing file or malformed/unreadable PDF. Response excludes file_data, storage_path and private content.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## GET /api/transactions/{id}/evidence

List metadata for transaction 1. Empty result: {"items": []}. No public storage URLs or raw bytes are exposed.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/evidence-list.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>"
}
```

**Request body:**
```json
null
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "items": [
    {
      "id": 1,
      "transaction_id": 1,
      "filename": "simulated-delivery.pdf",
      "mime_type": "application/pdf",
      "size": 2048,
      "uploaded_at": "2026-11-03T10:10:00Z"
    }
  ]
}
```

**Error cases:** No request body. 404: transaction absent/inaccessible; 422: invalid path ID.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/transactions/{id}/analyze

Analyze existing PDFs for transaction 1. Accept only facts whose exact excerpts occur on the cited document page. Discard fabricated excerpts. Calculate readiness in deterministic code, not Gemini. The example score/weights are illustrative until T3.4/T4.3.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/evidence-analyze.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "transaction_id": 1,
  "facts": [
    {
      "id": 1,
      "document_id": 1,
      "fact_type": "delivery_date",
      "value": "2026-11-03",
      "page": 1,
      "excerpt": "The project files were delivered on November 3, 2026.",
      "confidence": 0.95
    }
  ],
  "readiness": {
    "id": 1,
    "transaction_id": 1,
    "score": 20,
    "breakdown": [
      {
        "item": "proof_of_delivery",
        "status": "present",
        "points": 20,
        "max_points": 20
      },
      {
        "item": "communication_with_buyer",
        "status": "missing",
        "points": 0,
        "max_points": 20
      },
      {
        "item": "terms_agreement",
        "status": "missing",
        "points": 0,
        "max_points": 20
      },
      {
        "item": "proof_of_payment_match",
        "status": "missing",
        "points": 0,
        "max_points": 20
      },
      {
        "item": "usage_access_logs",
        "status": "missing",
        "points": 0,
        "max_points": 20
      }
    ],
    "missing_items": [
      "communication_with_buyer",
      "terms_agreement",
      "proof_of_payment_match",
      "usage_access_logs"
    ],
    "recommendations": [
      "Add buyer communication, the agreement, payment-matching evidence and usage logs."
    ],
    "computed_at": "2026-11-03T10:15:00Z"
  }
}
```

**Error cases:** 404: absent/inaccessible transaction; 409: no evidence uploaded; 422: invalid path ID; 503: model failure after retries; 504: upstream timeout. Do not replace prior valid analysis with fabricated fallback facts.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## GET /api/transactions/{id}/readiness

Read the latest computed score for transaction 1, including checklist states and recommendations. The sample uses equal illustrative weights, not an implemented scoring rule.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/readiness-get.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>"
}
```

**Request body:**
```json
null
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "id": 1,
  "transaction_id": 1,
  "score": 20,
  "breakdown": [
    {
      "item": "proof_of_delivery",
      "status": "present",
      "points": 20,
      "max_points": 20
    },
    {
      "item": "communication_with_buyer",
      "status": "missing",
      "points": 0,
      "max_points": 20
    },
    {
      "item": "terms_agreement",
      "status": "missing",
      "points": 0,
      "max_points": 20
    },
    {
      "item": "proof_of_payment_match",
      "status": "missing",
      "points": 0,
      "max_points": 20
    },
    {
      "item": "usage_access_logs",
      "status": "missing",
      "points": 0,
      "max_points": 20
    }
  ],
  "missing_items": [
    "communication_with_buyer",
    "terms_agreement",
    "proof_of_payment_match",
    "usage_access_logs"
  ],
  "recommendations": [
    "Add buyer communication, the agreement, payment-matching evidence and usage logs."
  ],
  "computed_at": "2026-11-03T10:15:00Z"
}
```

**Error cases:** No request body. 404: transaction inaccessible or readiness not yet computed; 422: invalid ID.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## GET /api/disputes

List disputes for this merchant. Every fixture dispute carries is_fixture=true; the UI must display Simulated. Empty result: {"items": []}. This sample is invented, not an observed Sandbox dispute.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/disputes-list.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>"
}
```

**Request body:**
```json
null
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "items": [
    {
      "id": 1,
      "transaction_id": 1,
      "paypal_dispute_id": "FIXTURE-DISPUTE-001",
      "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
      "status": "WAITING_FOR_SELLER_RESPONSE",
      "amount": "1.00",
      "response_due_at": "2026-11-10T10:00:00Z",
      "is_fixture": true,
      "raw": {
        "dispute_id": "FIXTURE-DISPUTE-001",
        "dispute_amount": {
          "currency_code": "USD",
          "value": "1.00"
        }
      }
    }
  ]
}
```

**Error cases:** No request body. Never include another merchant’s disputes; do not hide the fixture flag.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/disputes/sync

Sync from the server-configured DISPUTE_SOURCE; callers cannot select arbitrary sources. Match capture IDs to merchant-owned transactions, or leave transaction_id null when unmatched. Upsert by unique dispute ID.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/disputes-sync.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "source": "fixture",
  "synced_count": 1,
  "items": [
    {
      "id": 1,
      "transaction_id": 1,
      "paypal_dispute_id": "FIXTURE-DISPUTE-001",
      "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
      "status": "WAITING_FOR_SELLER_RESPONSE",
      "amount": "1.00",
      "response_due_at": "2026-11-10T10:00:00Z",
      "is_fixture": true,
      "raw": {
        "dispute_id": "FIXTURE-DISPUTE-001",
        "dispute_amount": {
          "currency_code": "USD",
          "value": "1.00"
        }
      }
    }
  ]
}
```

**Error cases:** 502/504: Sandbox source failure/timeout. Do not silently disguise fixtures as PayPal results. Repeat sync updates existing records without duplicates.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/disputes/{id}/draft

Generate a draft for dispute 1 from verified excerpts only. The synthetic claim cites source-text.json page 1. Missing evidence is explicitly disclosed. Empty evidence must produce an insufficient-evidence draft with no unsupported claims.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/disputes-draft.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "dispute": {
    "id": 1,
    "transaction_id": 1,
    "paypal_dispute_id": "FIXTURE-DISPUTE-001",
    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "amount": "1.00",
    "response_due_at": "2026-11-10T10:00:00Z",
    "is_fixture": true,
    "raw": {
      "dispute_id": "FIXTURE-DISPUTE-001",
      "dispute_amount": {
        "currency_code": "USD",
        "value": "1.00"
      }
    }
  },
  "response": {
    "id": 1,
    "dispute_id": 1,
    "draft_text": "The project files were delivered on November 3, 2026. [1] Evidence is insufficient to establish buyer acknowledgement, agreed terms, payment match, or usage.",
    "citations": [
      {
        "document_id": 1,
        "page": 1,
        "excerpt": "The project files were delivered on November 3, 2026."
      }
    ],
    "status": "draft",
    "approved_at": null,
    "submitted_at": null
  }
}
```

**Error cases:** 404: absent/inaccessible dispute; 409: response already submitted/exported; 503/504: model failure/timeout. Draft generation never submits anything.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## PUT /api/disputes/{id}/response

Edit the draft for dispute 1. Validate citation document ownership, page and exact excerpt. Editing an approved response returns it to draft and clears approved_at; require approval again.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/disputes-edit-response.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{
  "draft_text": "The project files were delivered on November 3, 2026. [1] Evidence is insufficient to establish buyer acknowledgement, agreed terms, payment match, or usage.",
  "citations": [
    {
      "document_id": 1,
      "page": 1,
      "excerpt": "The project files were delivered on November 3, 2026."
    }
  ]
}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "dispute": {
    "id": 1,
    "transaction_id": 1,
    "paypal_dispute_id": "FIXTURE-DISPUTE-001",
    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "amount": "1.00",
    "response_due_at": "2026-11-10T10:00:00Z",
    "is_fixture": true,
    "raw": {
      "dispute_id": "FIXTURE-DISPUTE-001",
      "dispute_amount": {
        "currency_code": "USD",
        "value": "1.00"
      }
    }
  },
  "response": {
    "id": 1,
    "dispute_id": 1,
    "draft_text": "The project files were delivered on November 3, 2026. [1] Evidence is insufficient to establish buyer acknowledgement, agreed terms, payment match, or usage.",
    "citations": [
      {
        "document_id": 1,
        "page": 1,
        "excerpt": "The project files were delivered on November 3, 2026."
      }
    ],
    "status": "draft",
    "approved_at": null,
    "submitted_at": null
  }
}
```

**Error cases:** 404: dispute/response absent or inaccessible; 409: already submitted/exported; 422: invalid citation or unsupported factual claims. Submitted content cannot be edited in place.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/disputes/{id}/approve

Approve the current reviewed response for dispute 1 and atomically write audit_log. The merchant identity comes from JWT. Approval alone does not send evidence to PayPal.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/disputes-approve.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "dispute": {
    "id": 1,
    "transaction_id": 1,
    "paypal_dispute_id": "FIXTURE-DISPUTE-001",
    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "amount": "1.00",
    "response_due_at": "2026-11-10T10:00:00Z",
    "is_fixture": true,
    "raw": {
      "dispute_id": "FIXTURE-DISPUTE-001",
      "dispute_amount": {
        "currency_code": "USD",
        "value": "1.00"
      }
    }
  },
  "response": {
    "id": 1,
    "dispute_id": 1,
    "draft_text": "The project files were delivered on November 3, 2026. [1] Evidence is insufficient to establish buyer acknowledgement, agreed terms, payment match, or usage.",
    "citations": [
      {
        "document_id": 1,
        "page": 1,
        "excerpt": "The project files were delivered on November 3, 2026."
      }
    ],
    "status": "approved",
    "approved_at": "2026-11-03T10:20:00Z",
    "submitted_at": null
  },
  "audit_log": {
    "id": 1,
    "merchant_id": 1,
    "action": "dispute_response.approved",
    "entity_type": "dispute_response",
    "entity_id": 1,
    "detail": {
      "dispute_id": 1,
      "is_fixture": true
    },
    "created_at": "2026-11-03T10:20:00Z"
  }
}
```

**Error cases:** 404: absent/inaccessible response; 409: no reviewable draft or already submitted/exported; 422: invalid citations. A repeat approval of the unchanged approved response returns its existing approval and audit entry.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/disputes/{id}/submit

For fixture disputes, never call PayPal: after approval return a Markdown export labeled Simulated. Only real Sandbox disputes in permitted states may be submitted; otherwise export. This sample follows the fixture branch; submitted_at remains null. For permitted real submission, response.status becomes submitted, submitted_at is set and delivery.mode is paypal.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/disputes-submit.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>",
  "Content-Type": "application/json"
}
```

**Request body:**
```json
{}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "dispute": {
    "id": 1,
    "transaction_id": 1,
    "paypal_dispute_id": "FIXTURE-DISPUTE-001",
    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "amount": "1.00",
    "response_due_at": "2026-11-10T10:00:00Z",
    "is_fixture": true,
    "raw": {
      "dispute_id": "FIXTURE-DISPUTE-001",
      "dispute_amount": {
        "currency_code": "USD",
        "value": "1.00"
      }
    }
  },
  "response": {
    "id": 1,
    "dispute_id": 1,
    "draft_text": "The project files were delivered on November 3, 2026. [1] Evidence is insufficient to establish buyer acknowledgement, agreed terms, payment match, or usage.",
    "citations": [
      {
        "document_id": 1,
        "page": 1,
        "excerpt": "The project files were delivered on November 3, 2026."
      }
    ],
    "status": "exported",
    "approved_at": "2026-11-03T10:20:00Z",
    "submitted_at": null
  },
  "delivery": {
    "mode": "export",
    "format": "markdown",
    "filename": "simulated-dispute-001.md",
    "content": "# Simulated dispute response\n\nThe project files were delivered on November 3, 2026. [1] Evidence is insufficient to establish buyer acknowledgement, agreed terms, payment match, or usage.\n\n[1] Document 1, page 1: The project files were delivered on November 3, 2026."
  }
}
```

**Error cases:** 404: absent/inaccessible response; 409: not approved or edited since approval; 502/504: PayPal failure/timeout. Repeated export/submission must return the recorded result without sending again; never label a timeout as submitted.
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## GET /api/dashboard/summary

Return merchant-scoped totals, readiness distribution, unresolved disputes and top evidence gaps. Separate currencies instead of summing unlike amounts. Display simulated dispute counts explicitly. Buckets are a proposed presentation contract.

**Auth:** merchant JWT.

**Sample:** [request, response and error bodies](../fixtures/api/dashboard-summary.json).

**Request headers:**
```json
{
  "Authorization": "Bearer <JWT_PLACEHOLDER>"
}
```

**Request body:**
```json
null
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "transaction_count": 1,
  "verified_transaction_count": 1,
  "verified_amount_by_currency": {
    "USD": "1.00"
  },
  "readiness_distribution": {
    "not_analyzed": 0,
    "low_0_39": 1,
    "medium_40_69": 0,
    "high_70_100": 0
  },
  "unresolved_disputes": {
    "total": 1,
    "paypal": 0,
    "simulated": 1
  },
  "top_missing_evidence": [
    {
      "item": "communication_with_buyer",
      "transaction_count": 1
    },
    {
      "item": "terms_agreement",
      "transaction_count": 1
    },
    {
      "item": "proof_of_payment_match",
      "transaction_count": 1
    },
    {
      "item": "usage_access_logs",
      "transaction_count": 1
    }
  ]
}
```

**Error cases:** No request body. With no data all counts are zero, currency totals are {}, and top_missing_evidence is [].
All requests also return 401 for a missing, invalid or expired JWT.
Machine-readable error body samples are in the linked fixture.

## POST /api/webhooks/paypal

Receive a signed PayPal Sandbox webhook, not a merchant JWT. This event is synthetic and its placeholder signature cannot verify. Validate PayPal’s signature against the configured webhook ID before any state change; deduplicate by unique event ID; reconcile the capture server-side against stored order and amount.

**Auth:** PayPal signature verification; no JWT.

**Sample:** [request, response and error bodies](../fixtures/api/webhooks-paypal.json).

**Request headers:**
```json
{
  "Content-Type": "application/json",
  "PAYPAL-AUTH-ALGO": "SHA256withRSA",
  "PAYPAL-CERT-URL": "https://api-m.sandbox.paypal.com/v1/notifications/certs/EXAMPLE",
  "PAYPAL-TRANSMISSION-ID": "SANDBOX-TRANSMISSION-EXAMPLE",
  "PAYPAL-TRANSMISSION-SIG": "<SIGNATURE_PLACEHOLDER>",
  "PAYPAL-TRANSMISSION-TIME": "2026-11-03T10:00:00Z"
}
```

**Request body:**
```json
{
  "id": "SANDBOX-EVENT-EXAMPLE",
  "event_type": "PAYMENT.CAPTURE.COMPLETED",
  "resource_type": "capture",
  "resource": {
    "id": "SANDBOX-CAPTURE-EXAMPLE",
    "status": "COMPLETED",
    "amount": {
      "currency_code": "USD",
      "value": "1.00"
    },
    "supplementary_data": {
      "related_ids": {
        "order_id": "SANDBOX-ORDER-EXAMPLE"
      }
    }
  }
}
```

**Response:** HTTP 200; `Content-Type: application/json`.
```json
{
  "status": "ok",
  "duplicate": false
}
```

**Error cases:** 400: invalid signature or malformed event; 502/504: signature-verification or reconciliation failure (retryable, do not mark processed). Valid duplicate: 200 with {"status":"ok","duplicate":true}; valid unsupported event: 200 after logging, with no payment mutation. Failed processing must remain retryable rather than being discarded merely because event ID was stored.
Machine-readable error body samples are in the linked fixture.

## Scope and provenance

The redacted [smoke subset](../fixtures/paypal-smoke-observed.json) preserves the observed approval-link shape and successful empty dispute listing from T1.2. All other payment captures, webhook payloads, disputes, extracted facts and business DTOs are synthetic proposals. No fresh Sandbox request was needed for this documentation task.

T3.3 also calls for authenticated evidence downloads, but section 6 does not specify that route. Choose its path when implementing T3.3; this reference does not invent an additional endpoint. The JSON export above avoids introducing an unplanned export URL. No public evidence URL is provided.

T1.4 is **partial**, not complete. See [DECISIONS.md](DECISIONS.md) for the pending manual dispute test after T2.3.

## Synthetic deployment demo transactions

Transaction responses also include `is_demo` (boolean), derived from the reserved
`DEMO-` order ID prefix without a database schema change. The demo rebuild command
creates only `CREATED` synthetic rows, never verified payments. Capture of a demo
order returns HTTP 409 with `detail.code` = `demo_transaction`; it makes no PayPal
request. Ordinary PayPal orders have `is_demo: false`.

