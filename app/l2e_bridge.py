"""L2E Bridge — pseudonymous attendance attestation relay.

DISABLED by default (l2e_enabled=false in config). When enabled, sends only
pseudonymous, hashed attestations to the main chain L2E service. No PII
(tax_id, full names, classroom/program names, raw personal data) ever
leaves this module.

Payload contains only:
- tenant-scoped pseudonymous student ref (HMAC)
- versioned attestation hash
- deterministic event_id (for idempotency)

Delivery uses a durable outbox with retry policy, receiver acknowledgement,
and idempotency. A delivery retry never creates a second eligibility/reward
event.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Callable

import requests

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models import Classroom, Lesson

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


def deterministic_event_id(tenant_scope: str, student_ref: str,
                           session_ts: int) -> str:
    raw = f"{tenant_scope}:{student_ref}:{session_ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def build_attestation_hash(attendance_record: dict) -> str:
    canonical = json.dumps({
        "classroom_id": attendance_record.get("classroom_id"),
        "date": attendance_record.get("date"),
        "status": attendance_record.get("status"),
        "hours": attendance_record.get("hours"),
    }, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Attestation event ─────────────────────────────────────────

@dataclass
class L2EAttestationEvent:
    event_id: str
    tenant_scope: str
    student_ref: str
    attestation_hash: str
    attestation_version: int = 1
    timestamp: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = int(time.time())


# ── Durable outbox ────────────────────────────────────────────

_outbox: list[dict] = []
_delivered_event_ids: set[str] = set()


def enqueue_attestation(event: L2EAttestationEvent) -> bool:
    if not settings.l2e_enabled:
        return False
    if event.event_id in _delivered_event_ids:
        return False
    for queued in _outbox:
        if queued["event_id"] == event.event_id:
            return False
    _outbox.append(asdict(event))
    return True


def process_outbox(receiver_ack_fn: Callable | None = None,
                   max_retries: int = 3) -> dict:
    if not settings.l2e_enabled:
        return {"delivered": 0, "failed": 0, "skipped": 0}

    delivered = 0
    failed = 0
    skipped = 0
    remaining = []

    for entry in _outbox:
        eid = entry["event_id"]
        if eid in _delivered_event_ids:
            skipped += 1
            continue

        retries = entry.get("_retries", 0)
        if retries >= max_retries:
            failed += 1
            continue

        if receiver_ack_fn:
            try:
                ack = receiver_ack_fn(entry)
                if ack:
                    _delivered_event_ids.add(eid)
                    delivered += 1
                    continue
            except Exception:
                pass

        entry["_retries"] = retries + 1
        remaining.append(entry)

    _outbox.clear()
    _outbox.extend(remaining)
    return {"delivered": delivered, "failed": failed, "skipped": skipped}


def reset_outbox():
    _outbox.clear()
    _delivered_event_ids.clear()


# ── Bridge payload builders (PII-free) ────────────────────────

def _headers() -> dict:
    return {
        "X-Internal-Key": settings.l2e_api_key,
        "X-Api-Key": settings.l2e_api_key,
        "Content-Type": "application/json",
    }


def _base() -> str:
    return settings.l2e_base_url.rstrip("/")


def report_lesson_attendance(lesson: "Lesson", db: "Session") -> bool:
    if not settings.l2e_enabled:
        log.debug("[L2E] disabled, skipping lesson %s report", lesson.id)
        return True

    classroom = lesson.classroom
    if not classroom:
        return False

    tenant = classroom.l2e_tenant_id or settings.l2e_tenant_id
    lesson_ts = int(lesson.starts_at.timestamp()) if lesson.starts_at else int(time.time())

    attendances = []
    for att in lesson.attendance_rows:
        stu_ref = pseudonymous_student_ref(tenant, att.student_id)
        att_hash = build_attestation_hash({
            "classroom_id": classroom.id,
            "date": lesson.starts_at.isoformat() if lesson.starts_at else "",
            "status": att.status,
            "hours": lesson.teaching_hours,
        })
        event_id = deterministic_event_id(tenant, stu_ref, lesson_ts)

        attendances.append({
            "student_ref": stu_ref,
            "attestation_hash": att_hash,
            "event_id": event_id,
            "attendance_status": att.status,
            "confirmation_method": att.confirmation_method,
        })

        evt = L2EAttestationEvent(
            event_id=event_id,
            tenant_scope=tenant,
            student_ref=stu_ref,
            attestation_hash=att_hash,
            timestamp=lesson_ts,
        )
        enqueue_attestation(evt)

    payload = {
        "source": "thronos_edupresence",
        "tenant_id": tenant,
        "l2e_course_id": classroom.l2e_course_id or f"edu-{classroom.id}",
        "lesson_id": lesson.id,
        "lesson_date": lesson.starts_at.isoformat() if lesson.starts_at else "",
        "teaching_hours": lesson.teaching_hours,
        "closed_at": (lesson.closed_at or lesson.starts_at).isoformat()
                     if (lesson.closed_at or lesson.starts_at) else "",
        "attendances": attendances,
    }

    try:
        resp = requests.post(
            f"{_base()}/api/l2e/edu/attendance",
            json=payload,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        ok = resp.status_code < 300
        if ok:
            log.info("[L2E] lesson %s reported ok (%d students)",
                     lesson.id, len(attendances))
        else:
            log.warning("[L2E] lesson %s report failed %s: %s",
                        lesson.id, resp.status_code, resp.text[:200])
        return ok
    except Exception as exc:
        log.error("[L2E] lesson %s report error: %s", lesson.id, exc)
        return False


def report_course_completion(classroom: "Classroom", db: "Session") -> dict:
    if not settings.l2e_enabled:
        return {"ok": True, "skipped": True}

    from app.models import Attendance

    tenant = classroom.l2e_tenant_id or settings.l2e_tenant_id
    threshold = settings.l2e_attendance_threshold_pct
    closed_lessons = [l for l in classroom.lessons if l.status == "closed"]
    total_hours = sum(l.teaching_hours for l in closed_lessons)
    lesson_ids = [l.id for l in closed_lessons]
    total_lessons = len(closed_lessons)
    completion_ts = int(time.time())

    students_summary = []
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
        event_id = deterministic_event_id(tenant, stu_ref, completion_ts)

        students_summary.append({
            "student_ref": stu_ref,
            "event_id": event_id,
            "lessons_attended": present_count,
            "lessons_total": total_lessons,
            "attendance_pct": pct,
            "reward_eligible": eligible,
            "certificate_eligible": eligible,
        })

    payload = {
        "source": "thronos_edupresence",
        "tenant_id": tenant,
        "l2e_course_id": classroom.l2e_course_id or f"edu-{classroom.id}",
        "total_teaching_hours": total_hours,
        "target_teaching_hours": classroom.target_teaching_hours or 40,
        "attendance_threshold_pct": threshold,
        "students": students_summary,
    }

    try:
        resp = requests.post(
            f"{_base()}/api/l2e/edu/complete",
            json=payload,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        ok = resp.status_code < 300
        eligible_n = sum(1 for s in students_summary if s["reward_eligible"])
        log.info("[L2E] course %s completion reported ok=%s eligible=%d/%d",
                 classroom.id, ok, eligible_n, len(students_summary))
        return {"ok": ok, "students_eligible": eligible_n,
                "students_total": len(students_summary)}
    except Exception as exc:
        log.error("[L2E] course %s completion error: %s", classroom.id, exc)
        return {"ok": False, "error": str(exc)}
