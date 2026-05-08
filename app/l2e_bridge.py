"""L2E Bridge — EduPresence → Thronos Chain Learn2Earn integration.

When a lesson closes, attendance data is pushed to the main chain L2E service.
When a classroom reaches its target teaching hours, a course-completion event
is pushed to trigger certificate eligibility and reward_eligibility for
qualifying students (attendance_pct >= L2E_ATTENDANCE_THRESHOLD_PCT).

All calls are fire-and-forget with error logging. A failure here never
blocks the lesson close flow on EduPresence.
"""
from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

import requests

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models import Classroom, Lesson

log = logging.getLogger(__name__)
_TIMEOUT = 15


def _headers() -> dict:
    return {
        "X-Internal-Key": settings.l2e_api_key,
        "X-Api-Key": settings.l2e_api_key,
        "Content-Type": "application/json",
    }


def _base() -> str:
    return settings.l2e_base_url.rstrip("/")


def _name_hash(name: str) -> str:
    return hashlib.sha256(name.strip().upper().encode()).hexdigest()[:16]


def report_lesson_attendance(lesson: "Lesson", db: "Session") -> bool:
    """Push per-lesson attendance to main chain L2E. Called on lesson close."""
    if not settings.l2e_enabled:
        log.debug("[L2E] disabled, skipping lesson %s report", lesson.id)
        return True

    classroom = lesson.classroom
    if not classroom:
        return False

    attendances = [
        {
            "student_external_ref": att.student.external_ref or str(att.student.id),
            "student_name_hash": _name_hash(att.student.full_name),
            "thr_wallet": att.student.thr_wallet or "",
            "tax_id": att.student.tax_id or "",
            "attendance_status": att.status,
            "confirmation_method": att.confirmation_method,
            "attestation_hash": att.attestation_hash,
        }
        for att in lesson.attendance_rows
    ]

    payload = {
        "source": "thronos_edupresence",
        "tenant_id": classroom.l2e_tenant_id or settings.l2e_tenant_id,
        "l2e_course_id": classroom.l2e_course_id or f"edu-{classroom.id}",
        "classroom_id": classroom.id,
        "classroom_name": classroom.name,
        "program_name": classroom.program_name,
        "lesson_id": lesson.id,
        "lesson_title": lesson.title,
        "lesson_date": lesson.starts_at.isoformat(),
        "teaching_hours": lesson.teaching_hours,
        "closed_at": (lesson.closed_at or lesson.starts_at).isoformat(),
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
            log.info("[L2E] lesson %s reported ok (%d students)", lesson.id, len(attendances))
        else:
            log.warning("[L2E] lesson %s report failed %s: %s", lesson.id, resp.status_code, resp.text[:200])
        return ok
    except Exception as exc:
        log.error("[L2E] lesson %s report error: %s", lesson.id, exc)
        return False


def report_course_completion(classroom: "Classroom", db: "Session") -> dict:
    """Push course-completion summary. Triggers reward + certificate eligibility."""
    if not settings.l2e_enabled:
        return {"ok": True, "skipped": True}

    from app.models import Attendance, Lesson as LessonModel

    threshold = settings.l2e_attendance_threshold_pct
    closed_lessons = [l for l in classroom.lessons if l.status == "closed"]
    total_hours = sum(l.teaching_hours for l in closed_lessons)
    lesson_ids = [l.id for l in closed_lessons]
    total_lessons = len(closed_lessons)

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
                Attendance.status.in_(["present", "late", "left_early", "student_only_unverified"]),
            )
            .count()
        ) if lesson_ids else 0

        pct = round(present_count / total_lessons * 100) if total_lessons else 0
        eligible = pct >= threshold
        students_summary.append({
            "student_external_ref": student.external_ref or str(student.id),
            "student_name_hash": _name_hash(student.full_name),
            "thr_wallet": student.thr_wallet or "",
            "tax_id": student.tax_id or "",
            "lessons_attended": present_count,
            "lessons_total": total_lessons,
            "attendance_pct": pct,
            "reward_eligible": eligible,
            "certificate_eligible": eligible,
        })

    payload = {
        "source": "thronos_edupresence",
        "tenant_id": classroom.l2e_tenant_id or settings.l2e_tenant_id,
        "l2e_course_id": classroom.l2e_course_id or f"edu-{classroom.id}",
        "classroom_id": classroom.id,
        "classroom_name": classroom.name,
        "program_name": classroom.program_name,
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
        return {"ok": ok, "students_eligible": eligible_n, "students_total": len(students_summary)}
    except Exception as exc:
        log.error("[L2E] course %s completion error: %s", classroom.id, exc)
        return {"ok": False, "error": str(exc)}
