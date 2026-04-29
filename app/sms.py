from __future__ import annotations

from dataclasses import dataclass
import requests
from app.config import settings

@dataclass
class SmsResult:
    ok: bool
    provider: str
    status: str
    response: str = ""


def normalize_phone(phone: str) -> str:
    """Keep this simple for MVP. Accept +30..., 69..., 0030..."""
    p = (phone or "").strip().replace(" ", "").replace("-", "")
    if not p:
        return ""
    if p.startswith("0030"):
        return "+30" + p[4:]
    if p.startswith("69") and len(p) == 10:
        return "+30" + p
    return p


def send_sms(to_phone: str, body: str) -> SmsResult:
    to = normalize_phone(to_phone)
    provider = settings.sms_provider.lower().strip()

    if not to:
        return SmsResult(False, provider, "no_phone", "No phone number")

    if provider in {"", "mock", "console", "dry_run"} or settings.sms_dry_run:
        print(f"[SMS MOCK] to={to} body={body}")
        return SmsResult(True, "mock", "mock_sent", body)

    if provider == "twilio":
        if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_from_number:
            return SmsResult(False, "twilio", "missing_config", "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
        try:
            resp = requests.post(
                url,
                data={"To": to, "From": settings.twilio_from_number, "Body": body},
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                timeout=15,
            )
            ok = 200 <= resp.status_code < 300
            return SmsResult(ok, "twilio", "sent" if ok else "failed", resp.text[:1000])
        except Exception as exc:
            return SmsResult(False, "twilio", "error", str(exc))

    if provider == "http_get":
        if not settings.generic_sms_url:
            return SmsResult(False, "http_get", "missing_config", "Set GENERIC_SMS_URL")
        try:
            resp = requests.get(
                settings.generic_sms_url,
                params={"to": to, "text": body, "token": settings.generic_sms_token},
                timeout=15,
            )
            ok = 200 <= resp.status_code < 300
            return SmsResult(ok, "http_get", "sent" if ok else "failed", resp.text[:1000])
        except Exception as exc:
            return SmsResult(False, "http_get", "error", str(exc))

    return SmsResult(False, provider, "unknown_provider", f"Unknown SMS_PROVIDER={provider}")
