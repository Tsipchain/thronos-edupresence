from __future__ import annotations

import base64, hashlib, hmac, json, time
from typing import Any
from io import BytesIO
import qrcode
from qrcode.image.pil import PilImage
from fastapi import HTTPException
from app.config import settings

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))

def sign_payload(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body.setdefault("iss", settings.token_issuer)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(settings.token_secret.encode(), raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(sig)}"

def verify_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _unb64(raw_b64)
        supplied_sig = _unb64(sig_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid token format") from exc
    expected_sig = hmac.new(settings.token_secret.encode(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(supplied_sig, expected_sig):
        raise HTTPException(status_code=403, detail="Invalid token signature")
    payload = json.loads(raw.decode())
    if payload.get("iss") != settings.token_issuer:
        raise HTTPException(status_code=403, detail="Invalid token issuer")
    if expected_type and payload.get("typ") != expected_type:
        raise HTTPException(status_code=403, detail="Invalid token type")
    if payload.get("exp") and int(payload["exp"]) < int(time.time()):
        raise HTTPException(status_code=410, detail="Token expired")
    return payload

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def hash_identity(prefix: str, value: str | int) -> str:
    return sha256_text(f"{prefix}:{value}")

def qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data, image_factory=PilImage)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
