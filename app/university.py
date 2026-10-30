"""University Tenant Router — courses, assignments, grading, certificates, live sessions.

Provides the full university workflow:
  University → Course → Assignment → Submission → Grade → Certificate
  Course → LiveSession (scheduled live classrooms linked to attendance)

All write routes require RBAC + CSRF + tenant scope enforcement.
Teacher authoring/grading requires a verified Thronos wallet binding.
Student submissions derive identity from server-side session, never from form input.
Attestation hashes are queued attestations — not confirmed on-chain unless
a real transaction receipt exists.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.attestation import canonical_hash, record_attestation, write_audit
from app.config import settings
from app.db import get_db
from app.models import (
    Assignment, Certificate, Classroom, Course, Enrollment, Grade,
    LiveSession, Node, Student, Submission, University, now_utc,
)
from app.admin_ui import (
    _admin_session, _require_role, _enforce_tenant, _verify_csrf, _CSRF_COOKIE,
)
from app.roles import SUPER_ADMIN, TENANT_DIRECTOR, TEACHER, STUDENT, has_at_least

router = APIRouter(prefix="/uni", tags=["university"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _actor(request: Request) -> str:
    from app.main import actor_name
    return actor_name(request)


def _render(request: Request, template: str, ctx: dict):
    from app.main import render
    return render(request, template, ctx)


def _letter(score: float, pass_grade: float) -> str:
    if score >= 9.0:
        return "A"
    if score >= 8.0:
        return "B"
    if score >= 6.5:
        return "C"
    if score >= pass_grade:
        return "D"
    return "F"


def _require_csrf(request: Request, csrf_token: str) -> None:
    """Reject POST without valid CSRF double-submit cookie."""
    if not _verify_csrf(request, csrf_token):
        raise HTTPException(403, "Forbidden: invalid or missing CSRF token")


def _require_teacher_wallet(session_info: dict) -> None:
    """Teacher actions require a verified Thronos wallet binding.
    Fail closed if wallet absent, revoked or empty."""
    wallet = session_info.get("thr_wallet", "")
    if not wallet:
        raise HTTPException(403, "Forbidden: verified Thronos wallet required for teacher actions")


def _enforce_course_tenant(session_info: dict, course: Course, db: Session) -> None:
    """Enforce tenant scope on a course via its classroom's node.
    Super_admin bypasses."""
    if has_at_least(session_info.get("role", ""), SUPER_ADMIN):
        return
    tenant_id = session_info.get("tenant_id")
    if not tenant_id:
        raise HTTPException(403, "Forbidden: no tenant scope in session")
    if course.classroom and course.classroom.node_id:
        node_tenant = str(course.classroom.node_id)
        if tenant_id != node_tenant:
            raise HTTPException(403, "Forbidden: cross-tenant access denied")


def _enforce_uni_tenant(session_info: dict, uni_id: int, db: Session) -> None:
    """Enforce tenant scope at university level via its nodes.
    Super_admin bypasses."""
    if has_at_least(session_info.get("role", ""), SUPER_ADMIN):
        return
    tenant_id = session_info.get("tenant_id")
    if not tenant_id:
        raise HTTPException(403, "Forbidden: no tenant scope in session")
    node = db.query(Node).filter(
        Node.university_id == uni_id, Node.id == int(tenant_id)
    ).first()
    if not node:
        raise HTTPException(403, "Forbidden: cross-tenant access denied")


# ---------------------------------------------------------------------------
# Universities (tenants) — public metadata only on GET
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def university_list(request: Request, db: Annotated[Session, Depends(get_db)]):
    unis = db.query(University).order_by(University.name).all()
    return _render(request, "uni_list.html", {"universities": unis})


@router.post("")
def create_university(request: Request, db: Annotated[Session, Depends(get_db)],
                      name: str = Form(...), slug: str = Form(""),
                      domain: str = Form(""), contact_email: str = Form(""),
                      csrf_token: str = Form("")):
    session_info, err = _require_role(request, SUPER_ADMIN)
    if err:
        raise HTTPException(403, "Forbidden: super_admin role required")
    _require_csrf(request, csrf_token)
    if not slug.strip():
        slug = name.strip().lower().replace(" ", "-")[:120]
    existing = db.query(University).filter(University.slug == slug).first()
    if existing:
        raise HTTPException(409, "University slug already exists")
    uni = University(name=name.strip(), slug=slug, domain=domain.strip(),
                     contact_email=contact_email.strip(),
                     l2e_tenant_id=slug)
    db.add(uni)
    db.commit()
    write_audit(db, "university_created", "university", uni.id,
                actor=_actor(request), detail={"name": uni.name, "slug": uni.slug})
    return RedirectResponse(f"/uni/{uni.id}", status_code=303)


@router.get("/{uni_id}", response_class=HTMLResponse)
def university_detail(request: Request, uni_id: int, db: Annotated[Session, Depends(get_db)]):
    uni = db.query(University).options(
        joinedload(University.courses),
    ).filter(University.id == uni_id).first()
    if not uni:
        raise HTTPException(404, "University not found")
    return _render(request, "uni_detail.html", {"university": uni})


# ---------------------------------------------------------------------------
# Courses — detail requires auth (shows grades, submissions, student names)
# ---------------------------------------------------------------------------

@router.post("/{uni_id}/courses")
def create_course(request: Request, uni_id: int, db: Annotated[Session, Depends(get_db)],
                  title: str = Form(...), code: str = Form(""), description: str = Form(""),
                  semester: str = Form(""), credits: int = Form(0),
                  teacher_name: str = Form(""), teacher_email: str = Form(""),
                  max_students: int = Form(100), pass_grade: float = Form(5.0),
                  csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    _require_teacher_wallet(session_info)
    uni = db.get(University, uni_id)
    if not uni:
        raise HTTPException(404, "University not found")
    _enforce_uni_tenant(session_info, uni_id, db)

    node = db.query(Node).filter(Node.university_id == uni_id).first()
    if not node:
        node = Node(university_id=uni_id, name=uni.name, municipality="", address=uni.address)
        db.add(node)
        db.flush()

    classroom = Classroom(
        node_id=node.id, name=f"{code} {title}".strip(), capacity=max_students,
        teacher_name=teacher_name.strip(), teacher_email=teacher_email.strip(),
        l2e_tenant_id=uni.l2e_tenant_id or uni.slug,
    )
    db.add(classroom)
    db.flush()

    course = Course(
        university_id=uni_id, classroom_id=classroom.id,
        code=code.strip().upper(), title=title.strip(), description=description.strip(),
        semester=semester.strip(), credits=credits, max_students=max_students,
        teacher_name=teacher_name.strip(), teacher_email=teacher_email.strip(),
        pass_grade=pass_grade, l2e_course_id=f"uni-{uni.slug}-{code.strip().upper() or classroom.id}",
    )
    db.add(course)
    db.commit()
    write_audit(db, "course_created", "course", course.id,
                actor=_actor(request), detail={"uni_id": uni_id, "code": course.code, "title": course.title})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course.id}", status_code=303)


@router.get("/{uni_id}/courses/{course_id}", response_class=HTMLResponse)
def course_detail(request: Request, uni_id: int, course_id: int,
                  db: Annotated[Session, Depends(get_db)]):
    session_info, err = _require_role(request, STUDENT)
    if err:
        raise HTTPException(403, "Forbidden: authentication required")
    course = db.query(Course).options(
        joinedload(Course.university),
        joinedload(Course.assignments),
        joinedload(Course.grades).joinedload(Grade.student),
        joinedload(Course.live_sessions),
        joinedload(Course.certificates),
        joinedload(Course.classroom).joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).filter(Course.id == course_id, Course.university_id == uni_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    _enforce_course_tenant(session_info, course, db)
    enrollments = []
    if course.classroom:
        enrollments = [e for e in course.classroom.enrollments if e.status == "active"]
    return _render(request, "uni_course.html", {
        "course": course, "university": course.university,
        "enrollments": sorted(enrollments, key=lambda e: e.student.full_name),
    })


@router.post("/{uni_id}/courses/{course_id}/enroll")
def enroll_student_course(request: Request, uni_id: int, course_id: int,
                          db: Annotated[Session, Depends(get_db)],
                          student_id: int = Form(...),
                          csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    course = db.query(Course).options(
        joinedload(Course.classroom),
    ).filter(Course.id == course_id, Course.university_id == uni_id).first()
    if not course or not course.classroom_id:
        raise HTTPException(404, "Course not found")
    _enforce_course_tenant(session_info, course, db)
    existing = db.query(Enrollment).filter(
        Enrollment.classroom_id == course.classroom_id,
        Enrollment.student_id == student_id,
        Enrollment.status == "active",
    ).first()
    if not existing:
        db.add(Enrollment(classroom_id=course.classroom_id, student_id=student_id, status="active"))
        db.commit()
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}", status_code=303)


# ---------------------------------------------------------------------------
# Assignments — detail requires auth (shows submissions, student names)
# ---------------------------------------------------------------------------

@router.post("/{uni_id}/courses/{course_id}/assignments")
def create_assignment(request: Request, uni_id: int, course_id: int,
                      db: Annotated[Session, Depends(get_db)],
                      title: str = Form(...), description: str = Form(""),
                      assignment_type: str = Form("homework"), max_score: float = Form(100),
                      weight: float = Form(1.0), due_at: str = Form(""),
                      lock_on_chain: bool = Form(False),
                      csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    _require_teacher_wallet(session_info)
    course = db.query(Course).options(
        joinedload(Course.classroom),
    ).filter(Course.id == course_id, Course.university_id == uni_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    _enforce_course_tenant(session_info, course, db)
    if assignment_type not in {"homework", "exam", "project", "quiz"}:
        assignment_type = "homework"
    due_dt = datetime.fromisoformat(due_at) if due_at else None
    assignment = Assignment(
        course_id=course_id, title=title.strip(), description=description.strip(),
        assignment_type=assignment_type, max_score=max_score, weight=weight,
        due_at=due_dt, lock_on_chain=lock_on_chain,
        created_by=_actor(request), status="published", published_at=now_utc(),
    )
    db.add(assignment)
    db.commit()
    write_audit(db, "assignment_created", "assignment", assignment.id,
                actor=_actor(request), detail={"course_id": course_id, "type": assignment_type})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}/assignments/{assignment.id}", status_code=303)


@router.get("/{uni_id}/courses/{course_id}/assignments/{assign_id}", response_class=HTMLResponse)
def assignment_detail(request: Request, uni_id: int, course_id: int, assign_id: int,
                      db: Annotated[Session, Depends(get_db)]):
    session_info, err = _require_role(request, STUDENT)
    if err:
        raise HTTPException(403, "Forbidden: authentication required")
    assignment = db.query(Assignment).options(
        joinedload(Assignment.course).joinedload(Course.university),
        joinedload(Assignment.course).joinedload(Course.classroom),
        joinedload(Assignment.submissions).joinedload(Submission.student),
    ).filter(Assignment.id == assign_id, Assignment.course_id == course_id).first()
    if not assignment or assignment.course.university_id != uni_id:
        raise HTTPException(404, "Assignment not found")
    _enforce_course_tenant(session_info, assignment.course, db)
    enrolled = []
    if assignment.course.classroom_id:
        enrolled = db.query(Student).join(Enrollment).filter(
            Enrollment.classroom_id == assignment.course.classroom_id,
            Enrollment.status == "active",
        ).order_by(Student.full_name).all()
    submitted_ids = {s.student_id for s in assignment.submissions}
    return _render(request, "uni_assignment.html", {
        "assignment": assignment, "course": assignment.course,
        "university": assignment.course.university,
        "enrolled": enrolled, "submitted_ids": submitted_ids,
    })


@router.post("/{uni_id}/courses/{course_id}/assignments/{assign_id}/submit")
def submit_assignment(request: Request, uni_id: int, course_id: int, assign_id: int,
                      db: Annotated[Session, Depends(get_db)],
                      content: str = Form(""), file_url: str = Form(""),
                      csrf_token: str = Form("")):
    session_info, err = _require_role(request, STUDENT)
    if err:
        raise HTTPException(403, "Forbidden: authentication required")
    _require_csrf(request, csrf_token)

    student_id = session_info.get("student_id")
    if not student_id:
        raise HTTPException(403, "Forbidden: no student identity in session")

    assignment = db.query(Assignment).options(
        joinedload(Assignment.course).joinedload(Course.classroom),
    ).filter(Assignment.id == assign_id, Assignment.course_id == course_id).first()
    if not assignment or assignment.course.university_id != uni_id:
        raise HTTPException(404, "Assignment not found")
    if assignment.status not in {"published", "closed"}:
        raise HTTPException(409, "Assignment is not accepting submissions")

    if not assignment.course.classroom_id:
        raise HTTPException(404, "Course has no classroom")
    enrolled = db.query(Enrollment).filter(
        Enrollment.classroom_id == assignment.course.classroom_id,
        Enrollment.student_id == student_id,
        Enrollment.status == "active",
    ).first()
    if not enrolled:
        raise HTTPException(403, "Forbidden: not enrolled in this course")

    _enforce_course_tenant(session_info, assignment.course, db)

    existing = db.query(Submission).filter(
        Submission.assignment_id == assign_id, Submission.student_id == student_id,
    ).first()
    if existing:
        existing.content = content.strip()
        existing.file_url = file_url.strip()
        existing.content_hash = hashlib.sha256((content + file_url).encode()).hexdigest()[:32]
        existing.submitted_at = now_utc()
        existing.status = "submitted"
        db.commit()
        return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}/assignments/{assign_id}", status_code=303)

    sub = Submission(
        assignment_id=assign_id, student_id=student_id,
        content=content.strip(), file_url=file_url.strip(),
        content_hash=hashlib.sha256((content + file_url).encode()).hexdigest()[:32],
    )
    db.add(sub)
    db.commit()
    write_audit(db, "submission_created", "submission", sub.id,
                actor=_actor(request), detail={"assignment_id": assign_id, "student_id": student_id})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}/assignments/{assign_id}", status_code=303)


@router.post("/{uni_id}/courses/{course_id}/assignments/{assign_id}/grade")
def grade_submission(request: Request, uni_id: int, course_id: int, assign_id: int,
                     db: Annotated[Session, Depends(get_db)],
                     submission_id: int = Form(...), score: float = Form(...),
                     feedback: str = Form(""),
                     csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    _require_teacher_wallet(session_info)
    sub = db.query(Submission).options(
        joinedload(Submission.assignment).joinedload(Assignment.course).joinedload(Course.classroom),
    ).filter(Submission.id == submission_id, Submission.assignment_id == assign_id).first()
    if not sub or sub.assignment.course_id != course_id or sub.assignment.course.university_id != uni_id:
        raise HTTPException(404, "Submission not found")
    _enforce_course_tenant(session_info, sub.assignment.course, db)

    sub.score = min(score, sub.assignment.max_score)
    sub.feedback = feedback.strip()
    sub.graded_by = _actor(request)
    sub.graded_at = now_utc()
    sub.status = "graded"

    if sub.assignment.lock_on_chain:
        payload = {
            "service": "edu_presence", "event_type": "submission_graded",
            "assignment_id": sub.assignment_id, "submission_id": sub.id,
            "student_id": sub.student_id, "score": sub.score,
            "max_score": sub.assignment.max_score, "content_hash": sub.content_hash,
            "graded_at": sub.graded_at.isoformat(),
        }
        attest = record_attestation(db, "submission_graded", payload)
        sub.attestation_hash = attest.payload_hash

    db.commit()
    write_audit(db, "submission_graded", "submission", sub.id,
                actor=_actor(request), detail={"score": sub.score, "max": sub.assignment.max_score})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}/assignments/{assign_id}", status_code=303)


# ---------------------------------------------------------------------------
# Final Grades — attestation hash (queued, not confirmed on-chain)
# ---------------------------------------------------------------------------

@router.post("/{uni_id}/courses/{course_id}/grades/compute")
def compute_final_grades(request: Request, uni_id: int, course_id: int,
                         db: Annotated[Session, Depends(get_db)],
                         csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    _require_teacher_wallet(session_info)
    course = db.query(Course).options(
        joinedload(Course.assignments).joinedload(Assignment.submissions),
        joinedload(Course.classroom).joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).filter(Course.id == course_id, Course.university_id == uni_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    _enforce_course_tenant(session_info, course, db)

    enrollments = [e for e in (course.classroom.enrollments if course.classroom else []) if e.status == "active"]
    assignments = [a for a in course.assignments if a.status in {"published", "closed", "graded"}]
    total_weight = sum(a.weight for a in assignments) or 1.0

    for enr in enrollments:
        weighted_sum = 0.0
        for a in assignments:
            sub = next((s for s in a.submissions if s.student_id == enr.student_id and s.score is not None), None)
            if sub:
                normalized = (sub.score / a.max_score) * 10.0
                weighted_sum += normalized * a.weight
        final = round(weighted_sum / total_weight, 2)
        passed = final >= course.pass_grade

        existing = db.query(Grade).filter(
            Grade.course_id == course_id, Grade.student_id == enr.student_id,
        ).first()
        if existing and existing.locked:
            continue
        if existing:
            existing.final_score = final
            existing.letter_grade = _letter(final, course.pass_grade)
            existing.passed = passed
            existing.graded_by = _actor(request)
        else:
            db.add(Grade(
                course_id=course_id, student_id=enr.student_id,
                final_score=final, letter_grade=_letter(final, course.pass_grade),
                passed=passed, graded_by=_actor(request),
            ))
    db.commit()
    write_audit(db, "grades_computed", "course", course_id,
                actor=_actor(request), detail={"student_count": len(enrollments)})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}", status_code=303)


@router.post("/{uni_id}/courses/{course_id}/grades/lock")
def lock_grades(request: Request, uni_id: int, course_id: int,
                db: Annotated[Session, Depends(get_db)],
                csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    _require_teacher_wallet(session_info)
    course = db.query(Course).options(
        joinedload(Course.grades).joinedload(Grade.student),
        joinedload(Course.university),
        joinedload(Course.classroom),
    ).filter(Course.id == course_id, Course.university_id == uni_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    _enforce_course_tenant(session_info, course, db)

    locked_count = 0
    for grade in course.grades:
        if grade.locked or grade.final_score is None:
            continue
        payload = {
            "service": "edu_presence", "event_type": "grade_attestation_queued",
            "university": course.university.name, "course_code": course.code,
            "course_title": course.title, "semester": course.semester,
            "student_id": grade.student_id,
            "student_name_hash": hashlib.sha256(grade.student.full_name.strip().upper().encode()).hexdigest()[:16],
            "final_score": grade.final_score, "letter_grade": grade.letter_grade,
            "passed": grade.passed, "locked_at": now_utc().isoformat(),
        }
        attest = record_attestation(db, "grade_attestation_queued", payload)
        grade.attestation_hash = attest.payload_hash
        grade.locked = True
        grade.locked_at = now_utc()
        locked_count += 1

    db.commit()
    write_audit(db, "grades_locked", "course", course_id,
                actor=_actor(request), detail={"locked": locked_count})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}", status_code=303)


# ---------------------------------------------------------------------------
# Certificates — attestation hash (queued, not confirmed on-chain)
# ---------------------------------------------------------------------------

@router.post("/{uni_id}/courses/{course_id}/certificates/issue")
def issue_certificates(request: Request, uni_id: int, course_id: int,
                       db: Annotated[Session, Depends(get_db)],
                       csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    _require_teacher_wallet(session_info)
    course = db.query(Course).options(
        joinedload(Course.grades).joinedload(Grade.student),
        joinedload(Course.university),
        joinedload(Course.certificates),
        joinedload(Course.classroom),
    ).filter(Course.id == course_id, Course.university_id == uni_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    _enforce_course_tenant(session_info, course, db)

    existing_cert_students = {c.student_id for c in course.certificates if c.status == "issued"}
    issued = 0
    for grade in course.grades:
        if not grade.passed or not grade.locked:
            continue
        if grade.student_id in existing_cert_students:
            continue

        cert_title = f"Certificate of Completion — {course.code} {course.title}"
        metadata = {
            "university": course.university.name,
            "course_code": course.code, "course_title": course.title,
            "semester": course.semester, "credits": course.credits,
            "student_name": grade.student.full_name,
            "final_score": grade.final_score, "letter_grade": grade.letter_grade,
            "issued_at": now_utc().isoformat(),
        }

        payload = {
            "service": "edu_presence", "event_type": "certificate_attestation_queued",
            "university_slug": course.university.slug,
            "course_code": course.code, "student_id": grade.student_id,
            "student_name_hash": hashlib.sha256(grade.student.full_name.strip().upper().encode()).hexdigest()[:16],
            "thr_wallet": grade.student.thr_wallet or "",
            "final_score": grade.final_score, "letter_grade": grade.letter_grade,
            "issued_at": now_utc().isoformat(),
        }
        attest = record_attestation(db, "certificate_attestation_queued", payload)

        cert = Certificate(
            course_id=course_id, student_id=grade.student_id,
            certificate_type="completion", title=cert_title,
            description=f"Completed {course.code} with grade {grade.letter_grade} ({grade.final_score}/10)",
            issued_by=course.teacher_name or _actor(request),
            attestation_hash=attest.payload_hash,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )
        db.add(cert)
        issued += 1

    db.commit()
    write_audit(db, "certificates_issued", "course", course_id,
                actor=_actor(request), detail={"issued": issued})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}", status_code=303)


# ---------------------------------------------------------------------------
# Live Sessions
# ---------------------------------------------------------------------------

@router.post("/{uni_id}/courses/{course_id}/live")
def create_live_session(request: Request, uni_id: int, course_id: int,
                        db: Annotated[Session, Depends(get_db)],
                        title: str = Form("Live Classroom"),
                        scheduled_at: str = Form(""),
                        duration_minutes: int = Form(90),
                        csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    _require_teacher_wallet(session_info)
    course = db.query(Course).options(
        joinedload(Course.classroom),
    ).filter(Course.id == course_id, Course.university_id == uni_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    _enforce_course_tenant(session_info, course, db)

    sched_dt = datetime.fromisoformat(scheduled_at) if scheduled_at else now_utc()
    room_id = f"live-{course.code or course_id}-{secrets.token_hex(4)}"
    join_url = f"{settings.public_base_url.rstrip('/')}/uni/{uni_id}/courses/{course_id}/live/{room_id}/join"

    ls = LiveSession(
        course_id=course_id, title=title.strip(),
        room_id=room_id, join_url=join_url,
        scheduled_at=sched_dt, duration_minutes=duration_minutes,
    )
    db.add(ls)
    db.commit()
    write_audit(db, "live_session_created", "live_session", ls.id,
                actor=_actor(request), detail={"course_id": course_id, "room_id": room_id})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}", status_code=303)


@router.get("/{uni_id}/courses/{course_id}/live/{room_id}/join", response_class=HTMLResponse)
def join_live_session(request: Request, uni_id: int, course_id: int, room_id: str,
                      db: Annotated[Session, Depends(get_db)]):
    session_info, err = _require_role(request, STUDENT)
    if err:
        raise HTTPException(403, "Forbidden: authentication required")
    ls = db.query(LiveSession).options(
        joinedload(LiveSession.course).joinedload(Course.university),
    ).filter(LiveSession.room_id == room_id, LiveSession.course_id == course_id).first()
    if not ls or ls.course.university_id != uni_id:
        raise HTTPException(404, "Live session not found")
    return _render(request, "uni_live.html", {
        "live_session": ls, "course": ls.course, "university": ls.course.university,
    })


@router.post("/{uni_id}/courses/{course_id}/live/{session_id}/start")
def start_live_session(request: Request, uni_id: int, course_id: int, session_id: int,
                       db: Annotated[Session, Depends(get_db)],
                       csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    ls = db.query(LiveSession).options(
        joinedload(LiveSession.course).joinedload(Course.classroom),
    ).filter(LiveSession.id == session_id, LiveSession.course_id == course_id).first()
    if not ls or ls.course.university_id != uni_id:
        raise HTTPException(404, "Live session not found")
    _enforce_course_tenant(session_info, ls.course, db)
    ls.status = "live"
    ls.started_at = now_utc()
    db.commit()
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}", status_code=303)


@router.post("/{uni_id}/courses/{course_id}/live/{session_id}/end")
def end_live_session(request: Request, uni_id: int, course_id: int, session_id: int,
                     db: Annotated[Session, Depends(get_db)],
                     csrf_token: str = Form("")):
    session_info, err = _require_role(request, TEACHER)
    if err:
        raise HTTPException(403, "Forbidden: teacher role required")
    _require_csrf(request, csrf_token)
    ls = db.query(LiveSession).options(
        joinedload(LiveSession.course).joinedload(Course.classroom),
    ).filter(LiveSession.id == session_id, LiveSession.course_id == course_id).first()
    if not ls or ls.course.university_id != uni_id:
        raise HTTPException(404, "Live session not found")
    _enforce_course_tenant(session_info, ls.course, db)
    ls.status = "ended"
    ls.ended_at = now_utc()
    db.commit()
    write_audit(db, "live_session_ended", "live_session", ls.id,
                actor=_actor(request), detail={"attendees": ls.attendee_count})
    return RedirectResponse(f"/uni/{uni_id}/courses/{course_id}", status_code=303)
