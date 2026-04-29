# Thronos EduPresence

Gov-style MVP for attendance, QR proof, SMS links, makeups, standby allocation, and hash-only attestations.

## What it includes

- Node → departments/classes → beneficiaries, matching the practical platform flow.
- Selected beneficiaries, standby beneficiaries, and inability-to-attend workflow.
- Admin approval/rejection for inability to attend.
- Allocation of next standby beneficiary after approval.
- Lesson/session creation with date/time, duration, teaching hours.
- Student SMS/mobile link.
- Student QR generated on phone.
- Teacher QR scanner.
- Teacher manual truth entry with reason for people without phone or with technical issues.
- Locked daily attendance sheet.
- Makeup attendance as a new document; it does not rewrite the old absence.
- Mock gov.gr/TaxisNet login scaffold, with future env slots for real OAuth/OIDC provider.
- Mock SMS outbox by default; Twilio and generic HTTP SMS are already supported by config.
- Hash-only attestation payloads. Do not put PII on-chain.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```txt
http://127.0.0.1:8000
```

## Field test tomorrow

Default SMS mode is mock. Press **Αποστολή SMS links σε όλους** and copy links from the SMS outbox.

For phone testing on the same Wi-Fi, set:

```env
PUBLIC_BASE_URL=http://YOUR_LAPTOP_LAN_IP:8000
SMS_PROVIDER=mock
```

For phone testing over mobile data, run ngrok:

```bash
ngrok http 8000
```

Set:

```env
PUBLIC_BASE_URL=https://YOUR-NGROK-URL
SMS_PROVIDER=mock
```

## Real SMS later

```env
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=...
PUBLIC_BASE_URL=https://edupresence.thronoschain.org
```

## Gov/TaxisNet later

The app currently has a mock login that behaves like a future gov.gr/TaxisNet entrypoint. When real provider details are available:

```env
AUTH_PROVIDER=gov
AUTH_REQUIRED=true
GOV_OAUTH_AUTHORIZE_URL=...
GOV_OAUTH_TOKEN_URL=...
GOV_OAUTH_USERINFO_URL=...
GOV_OAUTH_CLIENT_ID=...
GOV_OAUTH_CLIENT_SECRET=...
GOV_OAUTH_REDIRECT_URI=https://edupresence.thronoschain.org/auth/gov/callback
```

The callback is scaffolded. The actual token exchange/userinfo validation must be completed once the provider contract is known.

## Upgrade note

v4 uses a new local SQLite file: `data/edupresence_v4.db`, so it will not collide with older v1-v3 demo databases.
