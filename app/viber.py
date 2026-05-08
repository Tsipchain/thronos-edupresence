"""Viber Business Messages API notification provider."""
from __future__ import annotations

import requests
from app.config import settings

VIBER_API_URL = "https://chatapi.viber.com/pa/send_message"


def send_viber_message(to_phone: str, text: str) -> tuple[bool, str]:
    """Send a text message via Viber Business API. Returns (ok, response_text)."""
    if not settings.viber_bot_token:
        return False, "VIBER_BOT_TOKEN not configured"

    # Viber expects phone in E.164 without '+' prefix
    phone = to_phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("0030"):
        phone = "30" + phone[4:]
    elif phone.startswith("69") and len(phone) == 10:
        phone = "30" + phone

    payload = {
        "receiver": phone,
        "min_api_version": settings.viber_min_api_version,
        "sender": {"name": settings.viber_sender_name},
        "tracking_data": "thronos_edu",
        "type": "text",
        "text": text,
    }

    try:
        resp = requests.post(
            VIBER_API_URL,
            json=payload,
            headers={"X-Viber-Auth-Token": settings.viber_bot_token},
            timeout=15,
        )
        data = resp.json()
        ok = data.get("status") == 0
        return ok, str(data.get("status_message", resp.text))[:500]
    except Exception as exc:
        return False, str(exc)
