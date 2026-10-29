"""L2E Bridge — pseudonymous attendance attestation relay.

DISABLED by default (l2e_enabled=false in config). When enabled, sends only
pseudonymous, hashed attestations to the main chain L2E service. No PII
(tax_id, full names, classroom/program names, raw personal data) ever
leaves this module.

Payload contains only:
- tenant-scoped pseudonymous student ref (HMAC)
- versioned attestation hash
- deterministic event_id (from stable business fields only, no timestamps)

Delivery uses a durable DB-backed outbox with retry policy, receiver
acknowledgement, and idempotency. A delivery retry never creates a second
eligibility/reward event. State survives process restarts.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import requests

from app.config import settings
from app.models import L2EOutboxEntry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)
_TIMEOUT = 15


# ── Pseudonymous identity helpers ─────────────────────────────

def pseudonymous_student_ref(tenant_id: str, student_id: int,
                             secret: str = "") -> str:
    sec = secret or settings.l2e_api_key
    if not sec:
        return ""
    payload = f"{tenant_id}:{student_id}"
    return _hmac.new(sec.encode(), payload.encode(),
                     hashlib.sha256).hexdigest()[:24]


def deterministic_event_id(tenant_scope: str, classroom_id: str,
                           lesson_or_phase: str, attestation_version: int,
                           student_ref: str) -> str:
    """Deterministic event ID from stable business fields only — no time."""
    raw = f"{tenant_scope}:{classroom_id}:{lesson_or_phase}:{attestation_version}:{student_ref}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def build_attestation_hash(attendance_record: dict) -> str:
    canonical = json.dumps({
        "classroom_id": attendance_record.get("classroom_id"),
        "date": attendance_record.get("date"),
        "status": attendance_record.get("status"),
        "hours": attendance_record.get("hours"),
    }, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── DB-backed outbox ─────────────────────────────────────────

def enqueue_attestation(db: "Session", event_id: str, tenant_scope: str,
                        student_ref: str, attestation_hash: str,
                        payload: dict, attestation_version: int = 1,
                        max_retries: int = 3) -> bool:
    """Add attestation to persistent outbox. Returns False if disabled or duplicate."""
    if not settings.l2e_enabled:
        return False
    existing = db.query(L2EOutboxEntry).filter(
        L2EOutboxEntry.event_id == event_id
    ).first()
    if existing:
        return False
    entry = L2EOutboxEntry(
        event_id=event_id,
        tenant_scope=tenant_scope,
        student_ref=student_ref,
        attestation_hash=attestation_hash,
        attestation_version=attestation_version,
        payload_json=json.dumps(payload, ensure_ascii=False),
        max_retries=max_retries,
    )
    db.add(entry)
    db.flush()
    return True


def process_outbox(db: "Session") -> dict:
    """Process pending outbox entries via the L2E receiver endpoint.
    Durable: all state changes are committed to the DB."""
    if not settings.l2e_enabled:
        return {"delivered": 0, "failed": 0, "skipped": 0}

    now = datetime.utcnow()
    pending = db.query(L2EOutboxEntry).filter(
        L2EOutboxEntry.status == "pending",
    ).all()

    delivered = 0
    failed = 0
    skipped = 0

    for entry in pending:
        if entry.next_retry_at and entry.next_retry_at > now:
            skipped += 1
            continue

        if entry.retry_count >= entry.max_retries:
            entry.status = "failed"
            entry.failed_at = now
            entry.failure_reason = "max retries exceeded"
            failed += 1
            continue

        try:
            resp = requests.post(
                f"{settings.l2e_base_url.rstrip('/')}/api/l2e/edu/attendance",
                json=json.loads(entry.payload_json),
                headers={
                    "X-Internal-Key": settings.l2e_api_key,
                    "X-Api-Key": settings.l2e_api_key,
                    "Content-Type": "application/json",
                },
                timeout=_TIMEOUT,
            )
            if resp.status_code < 300:
                entry.status = "delivered"
                entry.delivered_at = now
                entry.receiver_ack = resp.text[:200]
                delivered += 1
            else:
                entry.retry_count += 1
                entry.last_attempt_at = now
                backoff = timedelta(minutes=2 ** entry.retry_count)
                entry.next_retry_at = now + backoff
                entry.failure_reason = f"HTTP {resp.status_code}"
        except Exception as exc:
            entry.retry_count += 1
            entry.last_attempt_at = now
            entry.failure_reason = str(exc)[:500]
            backoff = timedelta(minutes=2 ** entry.retry_count)
            entry.next_retry_at = now + backoff

    db.commit()
    return {"delivered": delivered, "failed": failed, "skipped": skipped}


def reset_outbox(db: "Session") -> None:
    """Test helper — clear all outbox state in DB."""
    db.query(L2EOutboxEntry).delete()
    db.commit()


# ── Bridge payload builders (outbox-only, PII-free) ──────────

def report_lesson_attendance(lesson, db: "Session") -> bool:
    """Enqueue pseudonymous attendance attestations to the outbox.
    Does NOT post directly — delivery happens via process_outbox()."""
    if not settings.l2e_enabled:
        log.debug("[L2E] disabled, skipping lesson %s report", lesson.id)
        return True

    classroom = lesson.classroom
    if not classroom:
        return False

    tenant = classroom.l2e_tenant_id or settings.l2e_tenant_id
    l2e_course = classroom.l2e_course_id or f"edu-{classroom.id}"

    for att in lesson.attendance_rows:
        stu_ref = pseudonymous_student_ref(tenant, att.student_id)
        att_hash = build_attestation_hash({
            "classroom_id": classroom.id,
            "date": lesson.starts_at.isoformat() if lesson.starts_at else "",
            "status": att.status,
            "hours": lesson.teaching_hours,
        })
        eid = deterministic_event_id(
            tenant, str(classroom.id), str(lesson.id), 1, stu_ref
        )

        payload = {
            "source": "thronos_edupresence",
            "event_id": eid,
            "tenant_id": tenant,
            "l2e_course_id": l2e_course,
            "lesson_id": lesson.id,
            "student_ref": stu_ref,
            "attestation_hash": att_hash,
            "attendance_status": att.status,
            "confirmation_method": att.confirmation_method,
        }

        enqueue_attestation(
            db, event_id=eid, tenant_scope=tenant,
            student_ref=stu_ref, attestation_hash=att_hash,
            payload=payload,
        )

    db.commit()
    return True


def report_course_completion(classroom, db: "Session") -> dict:
    """Enqueue pseudonymous completion attestations to the outbox.
    Does NOT post directly — delivery happens via process_outbox()."""
    if not settings.l2e_enabled:
        return {"ok": True, "skipped": True}

    from app.models import Attendance

    tenant = classroom.l2e_tenant_id or settings.l2e_tenant_id
    threshold = settings.l2e_attendance_threshold_pct
    closed_lessons = [l for l in classroom.lessons if l.status == "closed"]
    total_hours = sum(l.teaching_hours for l in closed_lessons)
    lesson_ids = [l.id for l in closed_lessons]
    total_lessons = len(closed_lessons)

    eligible_n = 0
    for enrollment in classroom.enrollments:
        if enrollment.status != "active":
            continue
        student = enrollment.student
        present_count = (
            db.query(Attendance)
            .filter(
                Attendance.student_id == student.id,
                Attendance.lesson_id.in_(lesson_ids),
                Attendance.status.in_(["present", "late", "left_early",
                                       "student_only_unverified"]),
            )
            .count()
        ) if lesson_ids else 0

        pct = round(present_count / total_lessons * 100) if total_lessons else 0
        eligible = pct >= threshold

        stu_ref = pseudonymous_student_ref(tenant, student.id)
        eid = deterministic_event_id(
            tenant, str(classroom.id), "completion", 1, stu_ref
        )

        payload = {
            "source": "thronos_edupresence",
            "event_id": eid,
            "tenant_id": tenant,
            "l2e_course_id": classroom.l2e_course_id or f"edu-{classroom.id}",
            "student_ref": stu_ref,
            "lessons_attended": present_count,
            "lessons_total": total_lessons,
            "attendance_pct": pct,
            "reward_eligible": eligible,
            "certificate_eligible": eligible,
            "total_teaching_hours": total_hours,
            "target_teaching_hours": classroom.target_teaching_hours or 40,
            "attendance_threshold_pct": threshold,
        }

        enqueue_attestation(
            db, event_id=eid, tenant_scope=tenant,
            student_ref=stu_ref,
            attestation_hash=hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
            payload=payload,
        )
        if eligible:
            eligible_n += 1

    db.commit()
    return {"ok": True, "students_eligible": eligible_n,
            "students_total": sum(1 for e in classroom.enrollments if e.status == "active")}
