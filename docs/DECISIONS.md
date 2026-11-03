# PayoutSentinel decisions

## 2026-11-03 IST — dispute source (T1.4 PARTIAL; NOT COMPLETE)

**Current default: `DISPUTE_SOURCE=fixture`.** Both `Settings.dispute_source`
in `backend/app/config.py` and `.env.example` retain this default. A deployment
environment can override it; this decision does not modify private `.env` values.
The source interface and synchronization are future work, not implemented here.

### Observed evidence

The T1.2 smoke check successfully created an unapproved PayPal Sandbox order,
printed its approval link, and listed disputes. Listing returned **0 items** on
the first page without error. Repeating the same request ID returned the same
order. No payment was captured. See the redacted observed subset in
`fixtures/paypal-smoke-observed.json`; no credentials or real IDs are retained.

This establishes that dispute listing works for the tested Sandbox app/account.
It does not establish that a real dispute can be created or submitted against.

### Decision and remaining work

Use labeled fixtures for now so dispute screens and drafts can be developed
without claiming a real dispute exists. Every fixture dispute must have
`is_fixture = true`, and the UI must show **Simulated**. Fixture disputes must
never be submitted to PayPal. Keep fixtures available even if PayPal is selected
later. The sample lives in `fixtures/dispute-simulated.json`.

**TODO — finish T1.4 after the first real Sandbox captured payment in T2.3:**

- [ ] Complete a Sandbox buyer payment and confirm its verified capture.
- [ ] Using the Sandbox buyer and business accounts, attempt manual dispute
      creation for that captured payment.
- [ ] List disputes again and fetch the created dispute, checking that it can
      be matched to the captured transaction. Record supported states/access.
- [ ] Record the outcome and reason for the final demo source choice here;
      update the config default and `.env.example` together if choosing `paypal`.
- [ ] Only then mark T1.4 complete. Retain the labeled fixture fallback either way.

Manual dispute creation is **pending**, because it needs a captured payment.
No manual creation attempt or capability failure is claimed by this decision.
