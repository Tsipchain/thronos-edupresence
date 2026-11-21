# Thronos EDU — Product boundary and acceptance

## Original product mismatch
The old EduPresence root is a QR attendance pilot built around nodes, classrooms, Greek-government-style branding and mock Gov authentication. It is not a complete Learn-2-Earn learning management system. Green security regression tests do not make it a finished student course dashboard.

The new learning product must be the public entry. Students must not choose a legacy training-center node, use a mock Gov identity, or create a THR wallet merely to find a course.

## Changes in this stacked Draft PR
- /: independent responsive Thronos EDU learner-first landing
- /learn/courses: read-only catalog of only explicitly published and active academic courses; existing active/demo academic courses are not publicly enrollable
- /learn/login: honest, non-interactive student authentication gate until verified OIDC/approved issuer is integrated
- /student-dashboard: EDU learning design; verified academic results first, old attendance secondary
- /presence: preserves the original QR pilot, its forms, data, attestations and existing URLs
- Legacy UI no longer asserts government endorsement and correctly labels mock identity as experimental

## P0 missing functions — not claimed as delivered
- Verified student login and account enrollment independent of wallet and pledge
- Real published course details, lesson player, progress persistence
- Quizzes, grading, certificates, course progress
- Fiat payments only with verified provider and receipts; no fake purchase
- Optional linked THR wallet and verified L2E claim gates
- Teacher course authoring, publishing, enrollment moderation
- Real EDU -> L2E receiver integration, consent, identity binding and deduplication
- Separate completion of the historical QR attendance proof flow

## Release gates
- Keep both EDU #26 and this stacked UI PR Draft until genuine student identity and learner E2E exist.
- Do not merge/replace production homepage or deploy without owner acceptance.
- No public-government affiliation claims, no fake enrollments, no auto L2E or financial transactions.
- Acceptance requires real login -> enrollment -> lessons -> quiz -> certificate, with optional wallet, tested at 375px and 1280px.
