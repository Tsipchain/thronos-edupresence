import logging
import time
from dataclasses import dataclass
from app.config import settings

logger = logging.getLogger(__name__)

@dataclass
class SMSResult:
    ok: bool
    status: str
    provider: str
    response: str

def normalize_phone(phone: str) -> str:
    """Normalize to E.164. Assumes Greek numbers if no country code."""
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if p.startswith("+30"):
        return p
    if p.startswith("0030"):
        return "+30" + p[4:]
    if p.startswith("30") and len(p) == 12:
        return "+" + p
    if p.startswith("+"):
        return p  # already has a country code
    # bare Greek number: 69xxxxxxxx (10 digits) or 9xxxxxxxx (9 digits)
    digits = p.lstrip("0")
    if len(digits) == 10:
        return "+30" + digits
    if len(digits) == 9:
        return "+30" + digits
    return "+" + digits

def send_sms(to_phone: str, body: str) -> SMSResult:
    """Route to configured SMS provider: viber | telesign | mock."""
    provider = settings.sms_provider.strip().lower()

    if provider == "viber":
        return send_viber(to_phone, body)
    elif provider == "telesign":
        return send_telesign(to_phone, body)
    else:  # mock
        return send_mock(to_phone, body)

def send_viber(to_phone: str, body: str) -> SMSResult:
    """Viber Business Messages API."""
    from app.viber import send_viber_message
    ok, response = send_viber_message(to_phone, body)
    return SMSResult(
        ok=ok,
        status="sent" if ok else "failed",
        provider="viber",
        response=response,
    )

def send_telesign(to_phone: str, body: str) -> SMSResult:
    """Telesign SMS REST API v1 (form-encoded)."""
    import base64
    import urllib.request
    import urllib.parse
    import json

    if not settings.telesign_customer_id or not settings.telesign_api_key:
        return SMSResult(
            ok=False,
            status="not_configured",
            provider="telesign",
            response="Telesign credentials not set",
        )

    phone = normalize_phone(to_phone)

    url = "https://rest-api.telesign.com/v1/messaging"
    auth = base64.b64encode(
        f"{settings.telesign_customer_id}:{settings.telesign_api_key}".encode()
    ).decode()

    # Telesign REST v1 requires form-encoded body, NOT JSON
    payload = urllib.parse.urlencode({
        "phone_number": phone,
        "message": body,
        "message_type": "ARN",
    }).encode()

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
            # Telesign: status.code 290x = queued/sent
            code = resp.get("status", {}).get("code", -1)
            ok = 2900 <= code <= 2999
            return SMSResult(
                ok=ok,
                status="sent" if ok else "failed",
                provider="telesign",
                response=json.dumps(resp),
            )
    except Exception as exc:
        logger.error(f"Telesign SMS failed: {exc}")
        return SMSResult(
            ok=False,
            status="error",
            provider="telesign",
            response=str(exc),
        )

def send_mock(to_phone: str, body: str) -> SMSResult:
    """Mock SMS (testing)."""
    logger.info(f"[MOCK SMS] To: {to_phone} | Body: {body[:80]}...")
    return SMSResult(
        ok=True,
        status="sent",
        provider="mock",
        response=f"Mock SMS logged to {to_phone}",
    )
