import logging
from dataclasses import dataclass
from app.config import settings

logger = logging.getLogger(__name__)

@dataclass
class SMSResult:
    ok: bool
    status: str
    provider: str
    response: str

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
    """Telesign SMS API."""
    import base64
    import urllib.request
    import json
    
    if not settings.telesign_customer_id or not settings.telesign_api_key:
        return SMSResult(
            ok=False,
            status="not_configured",
            provider="telesign",
            response="Telesign credentials not set",
        )
    
    # Normalize phone to E.164
    phone = to_phone.strip()
    if not phone.startswith("+"):
        phone = f"+{phone.lstrip('0')}"
    if len(phone) < 10:
        phone = "+30" + phone[-9:]  # Greece
    
    url = "https://rest-api.telesign.com/v1/messaging"
    auth = base64.b64encode(
        f"{settings.telesign_customer_id}:{settings.telesign_api_key}".encode()
    ).decode()
    
    payload = {
        "phone_number": phone,
        "message": body,
        "message_type": "ARN",  # Alert/Notification
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            ok = resp.get("status", {}).get("code") == 0
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
