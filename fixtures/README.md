# PayoutSentinel API fixtures

`api/` contains one JSON envelope per section 6 endpoint. Each envelope includes
the HTTP method/path, auth requirement, request headers/body, success status/body
and representative error status/body samples. Frontend mocks should return
`response.body` with `response.status`, not the entire envelope. Replace `{id}`
with the local ID `1` in sample requests. No endpoints are implemented by these
files; these are proposed contracts for subsequent tasks.

- `paypal-smoke-observed.json`: redacted subset of the T1.2 observed approval
  link and empty dispute list. It is not a full raw PayPal response.
- `dispute-simulated.json`: synthetic dispute with `is_fixture: true`; display
  **Simulated** and never submit it to PayPal.
- `source-text.json`: synthetic page text backing the example fact and citation.
  No matching PDF was uploaded; the upload request is a multipart descriptor.

All other data is synthetic, including captures and webhook signatures. IDs are
descriptive placeholders, email domains are reserved `.invalid` examples, and
credential/token fields are unusable placeholders. Never send these fixtures to
PayPal or treat their signatures as valid. The only PayPal environment is Sandbox.

Samples describe successive stages, not one simultaneous snapshot: create order,
capture, upload, analyze, draft, approve, then export. The fixture dispute always
uses the export branch; `submitted_at` remains null. Scoring weights and dashboard
buckets are illustrative pending their planned implementation tasks.

See [API reference](../docs/api.md) for all requests, responses and errors, and
[partial T1.4 decision](../docs/DECISIONS.md) for the pending manual dispute test.
