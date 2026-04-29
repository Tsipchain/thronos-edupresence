from __future__ import annotations

import json
import requests
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Attestation, AuditEvent
from app.security import sha256_text

def canonical_hash(payload: dict) -> tuple[str, str]:
    payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return payload_json, sha256_text(payload_json)

def write_audit(db: Session, action: str, target_type: str = "", target_id: str = "", actor: str = "system", detail: dict | None = None) -> AuditEvent:
    event = AuditEvent(actor=actor, action=action, target_type=target_type, target_id=str(target_id), detail_json=json.dumps(detail or {}, ensure_ascii=False, sort_keys=True))
    db.add(event); db.commit(); db.refresh(event)
    return event

def record_attestation(db: Session, event_type: str, payload: dict, service: str = "edu_presence") -> Attestation:
    payload_json, payload_hash = canonical_hash(payload)
    chain_response = ""
    if settings.thronos_attest_url:
        try:
            headers = {"Content-Type": "application/json"}
            if settings.thronos_attest_api_key:
                headers["X-API-Key"] = settings.thronos_attest_api_key
            resp = requests.post(settings.thronos_attest_url, json={"service": service, "event_type": event_type, "payload_hash": payload_hash, "payload": payload}, headers=headers, timeout=5)
            chain_response = resp.text[:4000]
        except Exception as exc:
            chain_response = f"ATTEST_SEND_FAILED: {type(exc).__name__}: {exc}"
    row = Attestation(service=service, event_type=event_type, payload_json=payload_json, payload_hash=payload_hash, chain_response=chain_response)
    db.add(row); db.commit(); db.refresh(row)
    return row
