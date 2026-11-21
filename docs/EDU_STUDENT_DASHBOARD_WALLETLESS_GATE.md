# EDU-owned Student Dashboard — walletless academic access

Status: **Draft / staging only**. The canonical student dashboard lives at
`/student-dashboard` in **Thronos EduPresence**, not on the ThronosChain wallet service.

## Scope implemented

- Uses the EDU's actual Student → Enrollment → Classroom and linked Course/Grade/Certificate records.
- Displays the authenticated learner's own enrollments, class attendance count, grades and issued certificates.
- Does not require, create, unlock or link any THR wallet.
- Does not issue THC/L2E, call financial endpoints, or enable Stripe.
- Reads no browser-supplied learner identity, unsigned cookie, wallet address or query parameter.
- Uses the existing EDU signed `session` cookie with an authenticated `student` identity.
- Denies mock Gov sessions, pending exchange sessions, teacher sessions, missing/expired sessions and ambiguous identity mappings.
- Stops private student data delivery when the server token secret is the default in production.

## P0: verified student login still required before production

**The existing `/auth/gov/callback` is not a completed governmental identity exchange.**
Even if `code` is present, it currently produces a `gov_pending_exchange` session
using mock tax ID/name. Neither `gov_pending_exchange` nor `mock_taxisnet`
may authorize student records. The new dashboard only permits a server-issued
`gov_verified` or `edu_verified_student` session with `role=student` and
a unique mapping to the EDU Student table.

These verified session types are an **integration contract**, not a claim that
an issuer is already live. Until a real OIDC/gov or approved identity verification
flow is implemented, production student sign-in to this page remains **NO-GO**.

The production server must use a high-entropy non-default token secret and
strict callback state/nonce/audience/issuer verification.

## L2E interoperability — separate, later gate

EDU publishes pseudonymous attendance/completion attestations through its L2E bridge
only once the receiver, authentication, tenant scope, deduplication and operational
approval are verified. `L2E_ENABLED` remains disabled by default.

A learner can view EDU classes without a wallet. A valid L2E claim is different:
it requires a verified learner-to-THR-wallet binding and authoritative reward
eligibility from the L2E backend. No claim button or auto-reward is exposed here.

Main-chain Draft PR #967 should **not** be merged as a student-facing dashboard.
A read-only redirect to the EDU route can be considered only after the EDU
session integration and real deployment exist.

## Acceptance checklist

- [x] EDU-local enrollment and academic results view, no wallet dependency
- [x] Student session bound to identity, not an arbitrary cookie or URL field
- [x] Deny mock/pending/teacher/missing/forged sessions
- [x] Two-student isolation, missing and ambiguous identity tests
- [ ] Verified real student login (Gov/OIDC) with approved issuer and callback checks
- [ ] Public-facing student sign-in UX and account recovery
- [ ] Real-device PWA/mobile accessibility and session expiry QA
- [ ] EDU/L2E bridge outbox, receiver and identity mapping acceptance
- [ ] Production operator approval

No deployment, production database migration, reward issuance, pledge or wallet changes.
