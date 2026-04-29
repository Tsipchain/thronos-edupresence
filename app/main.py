from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.attestation import canonical_hash, record_attestation, write_audit
from app.config import settings
from app.db import Base, engine, get_db
from app.models import (
    Attendance,
    Classroom,
    Enrollment,
    Lesson,
    Makeup,
    Node,
    SmsMessage,
    Student,
    UnableRequest,
    now_utc,
)
from app.security import hash_identity, qr_png_bytes, sign_payload, verify_token
from app.seed import seed_demo
from app.sms import send_sms

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.auto_seed_demo:
        db = next(get_db())
        try:
            seed_demo(db)
        finally:
            db.close()

# ---------------------------------------------------------------------------
# Labels / helpers
# ---------------------------------------------------------------------------

def status_label(status: str) -> str:
    return {
        "pending": "Αναμονή",
        "student_confirmed": "Επιβεβαίωσε μαθητής",
        "present": "Παρών",
        "absent": "Απών",
        "late": "Καθυστέρηση",
        "left_early": "Έφυγε νωρίς",
        "student_only_unverified": "Μόνο μαθητής / μη τελικό",
        "open": "Ανοιχτό",
        "closed": "Κλειδωμένο",
        "completed": "Ολοκληρωμένη",
        "selected": "Κατανεμημένος ωφελούμενος",
        "standby": "Επιλαχών",
        "unable_pending": "Εκκρεμεί αδυναμία παρακολούθησης",
        "unable_approved": "Εγκρίθηκε αδυναμία",
        "unable_rejected": "Απορρίφθηκε αδυναμία",
        "active": "Ενεργή",
        "removed": "Αφαιρέθηκε",
        "approved": "Εγκρίθηκε",
        "rejected": "Απορρίφθηκε",
    }.get(status, status)

def method_label(method: str) -> str:
    return {
        "student_qr_teacher_scan": "QR μαθητή + scan καθηγητή",
        "teacher_manual": "Χειροκίνητη επιβεβαίωση καθηγητή",
        "student_self_confirmed": "Επιβεβαίωση μαθητή μόνο",
        "no_signal": "Καμία επιβεβαίωση",
    }.get(method or "", method or "-")

def active_enrollments(classroom: Classroom):
    return [e for e in classroom.enrollments if e.status == "active"]

def active_enrollment_for(student: Student) -> Enrollment | None:
    for enrollment in student.enrollments:
        if enrollment.status == "active":
            return enrollment
    return None

def teaching_hours_done(classroom: Classroom) -> int:
    return sum((lesson.teaching_hours or max(1, lesson.duration_minutes // 45)) for lesson in classroom.lessons if lesson.status == "closed")

def completion_percent(classroom: Classroom) -> int:
    target = classroom.target_teaching_hours or 40
    return min(100, round((teaching_hours_done(classroom) / target) * 100)) if target else 0

# ---------------------------------------------------------------------------
# Mock / Gov login scaffold
# ---------------------------------------------------------------------------

def build_session(user: dict) -> str:
    exp = int(time.time() + settings.session_ttl_hours * 3600)
    payload = {"typ": "session", "exp": exp, **user}
    return sign_payload(payload)

def current_user(request: Request) -> dict | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    try:
        return verify_token(token, expected_type="session")
    except HTTPException:
        return None

def actor_name(request: Request) -> str:
    user = current_user(request)
    if user:
        return str(user.get("full_name") or user.get("tax_id") or "teacher")
    return settings.mock_user_full_name or "teacher"

def render(request: Request, name: str, context: dict) -> HTMLResponse:
    if settings.auth_required and not current_user(request) and request.url.path not in {"/login", "/auth/gov/start", "/auth/gov/callback", "/health"}:
        return RedirectResponse("/login", status_code=303)  # type: ignore[return-value]
    base = {
        "request": request,
        "settings": settings,
        "now": now_utc(),
        "current_user": current_user(request),
        "status_label": status_label,
        "method_label": method_label,
        "active_enrollments": active_enrollments,
        "active_enrollment_for": active_enrollment_for,
        "teaching_hours_done": teaching_hours_done,
        "completion_percent": completion_percent,
    }
    base.update(context)
    return templates.TemplateResponse(name, base)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", {})

@app.get("/auth/gov/start")
def auth_gov_start():
    # Mock mode: immediate demo login. Real gov mode: redirect to configured OAuth/OIDC endpoint.
    if settings.auth_provider != "gov" or not settings.gov_oauth_authorize_url or not settings.gov_oauth_client_id:
        user = {
            "tax_id": settings.mock_user_tax_id,
            "full_name": settings.mock_user_full_name,
            "role": settings.mock_user_role,
            "provider": "mock_taxisnet",
        }
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(settings.session_cookie_name, build_session(user), httponly=True, samesite="lax")
        return resp

    params = {
        "client_id": settings.gov_oauth_client_id,
        "redirect_uri": settings.gov_oauth_redirect_uri or f"{settings.public_base_url.rstrip('/')}/auth/gov/callback",
        "response_type": "code",
        "scope": "openid profile",
        "state": sign_payload({"typ": "gov_state", "exp": int(time.time() + 600)}),
    }
    return RedirectResponse(f"{settings.gov_oauth_authorize_url}?{urlencode(params)}", status_code=302)

@app.get("/auth/gov/callback")
def auth_gov_callback(code: str = "", state: str = ""):
    # Placeholder for real gov.gr/TaxisNet exchange. Until env vars and provider contract exist,
    # keep callback safe and mock a verified user.
    if state:
        try:
            verify_token(state, expected_type="gov_state")
        except HTTPException:
            pass
    user = {
        "tax_id": settings.mock_user_tax_id,
        "full_name": settings.mock_user_full_name,
        "role": settings.mock_user_role,
        "provider": "gov_callback_mock" if not code else "gov_pending_exchange",
    }
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(settings.session_cookie_name, build_session(user), httponly=True, samesite="lax")
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(settings.session_cookie_name)
    return resp

# ---------------------------------------------------------------------------
# Attendance link helpers
# ---------------------------------------------------------------------------

def student_link(att: Attendance) -> str:
    exp = int(time.time() + settings.student_link_ttl_hours * 3600)
    token = sign_payload({"typ": "student_checkin", "attendance_id": att.id, "lesson_id": att.lesson_id, "student_id": att.student_id, "exp": exp})
    return f"{settings.public_base_url.rstrip('/')}/s/{token}"

def sms_body_for_attendance(att: Attendance) -> str:
    link = student_link(att)
    lesson = att.lesson
    date_text = lesson.starts_at.strftime("%d/%m %H:%M") if lesson and lesson.starts_at else "σήμερα"
    return (
        f"Thronos EduPresence: Το μάθημα {date_text} ξεκίνησε. "
        f"Πατήστε για επιβεβαίωση παρουσίας: {link}"
    )

def assert_lesson_open(lesson: Lesson) -> None:
    if lesson.status != "open":
        raise HTTPException(status_code=409, detail="Lesson is closed/locked")

# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"ok": True, "service": settings.app_name, "environment": settings.environment}

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Annotated[Session, Depends(get_db)]):
    nodes = db.query(Node).options(joinedload(Node.classrooms), joinedload(Node.students)).order_by(Node.id.asc()).all()
    pending_makeups = db.query(Makeup).filter(Makeup.status == "pending").count()
    pending_unable = db.query(UnableRequest).filter(UnableRequest.status == "pending").count()
    node_selected_counts = {
        node.id: len([s for s in node.students if s.status in {"selected", "unable_pending", "unable_rejected"}])
        for node in nodes
    }
    return render(request, "dashboard.html", {"nodes": nodes, "node_selected_counts": node_selected_counts, "pending_makeups": pending_makeups, "pending_unable": pending_unable})

@app.post("/nodes")
def create_node(request: Request, db: Annotated[Session, Depends(get_db)], name: str = Form(...), municipality: str = Form(""), responsible_name: str = Form(""), capacity: int = Form(15)):
    node = Node(name=name.strip(), municipality=municipality.strip() or "ΘΕΣΣΑΛΟΝΙΚΗΣ", responsible_name=responsible_name.strip(), capacity=capacity)
    db.add(node); db.commit()
    write_audit(db, "node_created", "node", node.id, actor=actor_name(request), detail={"name": node.name})
    return RedirectResponse(f"/nodes/{node.id}", status_code=303)

@app.get("/nodes/{node_id}", response_class=HTMLResponse)
def node_detail(request: Request, node_id: int, db: Annotated[Session, Depends(get_db)]):
    node = db.query(Node).options(
        joinedload(Node.classrooms).joinedload(Classroom.lessons),
        joinedload(Node.classrooms).joinedload(Classroom.enrollments).joinedload(Enrollment.student),
        joinedload(Node.students).joinedload(Student.enrollments).joinedload(Enrollment.classroom),
    ).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    selected = sorted([s for s in node.students if s.status in {"selected", "unable_pending", "unable_rejected"}], key=lambda s: (s.full_name or ""))
    standby = sorted([s for s in node.students if s.status == "standby"], key=lambda s: (s.priority_order, s.full_name))
    unable_requests = db.query(UnableRequest).options(joinedload(UnableRequest.student)).filter(UnableRequest.node_id == node_id).order_by(UnableRequest.created_at.desc()).all()
    return render(request, "node_detail.html", {"node": node, "selected": selected, "standby": standby, "unable_requests": unable_requests})

@app.post("/nodes/{node_id}/classes")
def create_classroom(request: Request, node_id: int, db: Annotated[Session, Depends(get_db)], name: str = Form(...), capacity: int = Form(15), teacher_name: str = Form(""), teacher_afm: str = Form(""), teacher_email: str = Form(""), teacher_phone: str = Form("")):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    classroom = Classroom(node_id=node.id, name=name.strip(), capacity=capacity, teacher_name=teacher_name.strip() or settings.mock_user_full_name, teacher_afm=teacher_afm.strip(), teacher_email=teacher_email.strip(), teacher_phone=teacher_phone.strip(), location=node.name)
    db.add(classroom); db.commit()
    write_audit(db, "classroom_created", "classroom", classroom.id, actor=actor_name(request), detail={"node_id": node.id, "name": classroom.name})
    return RedirectResponse(f"/nodes/{node.id}", status_code=303)

@app.post("/nodes/{node_id}/students")
def create_student(request: Request, node_id: int, db: Annotated[Session, Depends(get_db)], full_name: str = Form(...), phone: str = Form(""), email: str = Form(""), external_ref: str = Form(""), gender: str = Form(""), status: str = Form("selected")):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    if status not in {"selected", "standby"}:
        status = "selected"
    max_priority = db.query(Student).filter(Student.node_id == node.id).count() + 1
    student = Student(node_id=node.id, full_name=full_name.strip(), phone=phone.strip(), email=email.strip(), external_ref=external_ref.strip(), gender=gender.strip(), status=status, priority_order=max_priority)
    db.add(student); db.commit()
    write_audit(db, "student_created", "student", student.id, actor=actor_name(request), detail={"status": status, "node_id": node.id})
    return RedirectResponse(f"/nodes/{node.id}", status_code=303)

@app.post("/nodes/{node_id}/students/{student_id}/enroll")
def enroll_student_to_class(request: Request, node_id: int, student_id: int, db: Annotated[Session, Depends(get_db)], classroom_id: int = Form(...)):
    node = db.get(Node, node_id)
    student = db.query(Student).options(joinedload(Student.enrollments)).filter(Student.id == student_id, Student.node_id == node_id).first()
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id, Classroom.node_id == node_id).first()
    if not node or not student or not classroom:
        raise HTTPException(404, "Node/student/classroom not found")
    if student.status not in {"selected", "unable_rejected"}:
        raise HTTPException(409, "Only selected beneficiaries can be placed in a class")
    active_count = db.query(Enrollment).filter(Enrollment.classroom_id == classroom.id, Enrollment.status == "active").count()
    if active_count >= classroom.capacity:
        raise HTTPException(409, "Classroom capacity reached")
    for enrollment in student.enrollments:
        if enrollment.status == "active":
            enrollment.status = "removed"
            enrollment.removed_at = now_utc()
    db.add(Enrollment(classroom_id=classroom.id, student_id=student.id, status="active"))
    student.status = "selected"
    db.commit()
    write_audit(db, "student_enrolled", "classroom", classroom.id, actor=actor_name(request), detail={"student_id": student_id, "node_id": node_id})
    return RedirectResponse(f"/nodes/{node_id}", status_code=303)

@app.post("/nodes/{node_id}/students/{student_id}/unable/request")
def request_unable(request: Request, node_id: int, student_id: int, db: Annotated[Session, Depends(get_db)], reason: str = Form("Αδυναμία παρακολούθησης")):
    student = db.query(Student).filter(Student.id == student_id, Student.node_id == node_id).first()
    if not student:
        raise HTTPException(404, "Student not found")
    if student.status == "unable_pending":
        return RedirectResponse(f"/nodes/{node_id}", status_code=303)
    student.status = "unable_pending"
    student.inability_reason = reason.strip()
    req = UnableRequest(node_id=node_id, student_id=student_id, reason=reason.strip(), requested_by=actor_name(request))
    db.add(req); db.commit()
    write_audit(db, "unable_requested", "student", student.id, actor=actor_name(request), detail={"reason": reason})
    return RedirectResponse(f"/nodes/{node_id}", status_code=303)

@app.post("/nodes/{node_id}/unable/{request_id}/approve")
def approve_unable(request: Request, node_id: int, request_id: int, db: Annotated[Session, Depends(get_db)]):
    req = db.query(UnableRequest).options(joinedload(UnableRequest.student).joinedload(Student.enrollments)).filter(UnableRequest.id == request_id, UnableRequest.node_id == node_id).first()
    if not req:
        raise HTTPException(404, "Unable request not found")
    req.status = "approved"
    req.decided_by = actor_name(request)
    req.decided_at = now_utc()
    req.student.status = "unable_approved"
    req.student.is_active = False
    for enrollment in req.student.enrollments:
        if enrollment.status == "active":
            enrollment.status = "removed"
            enrollment.removed_at = now_utc()
    db.commit()
    write_audit(db, "unable_approved", "student", req.student_id, actor=actor_name(request), detail={"request_id": request_id})
    return RedirectResponse(f"/nodes/{node_id}", status_code=303)

@app.post("/nodes/{node_id}/unable/{request_id}/reject")
def reject_unable(request: Request, node_id: int, request_id: int, db: Annotated[Session, Depends(get_db)]):
    req = db.query(UnableRequest).options(joinedload(UnableRequest.student)).filter(UnableRequest.id == request_id, UnableRequest.node_id == node_id).first()
    if not req:
        raise HTTPException(404, "Unable request not found")
    req.status = "rejected"
    req.decided_by = actor_name(request)
    req.decided_at = now_utc()
    req.student.status = "unable_rejected"
    req.student.is_active = True
    db.commit()
    write_audit(db, "unable_rejected", "student", req.student_id, actor=actor_name(request), detail={"request_id": request_id})
    return RedirectResponse(f"/nodes/{node_id}", status_code=303)

@app.post("/nodes/{node_id}/allocate-next")
def allocate_next_standby(request: Request, node_id: int, db: Annotated[Session, Depends(get_db)]):
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    student = db.query(Student).filter(Student.node_id == node_id, Student.status == "standby").order_by(Student.priority_order.asc(), Student.id.asc()).first()
    if not student:
        return RedirectResponse(f"/nodes/{node_id}?allocated=none", status_code=303)
    student.status = "selected"
    student.is_active = True
    db.commit()
    write_audit(db, "standby_allocated", "student", student.id, actor=actor_name(request), detail={"node_id": node_id})
    return RedirectResponse(f"/nodes/{node_id}?allocated={student.id}", status_code=303)

# ---------------------------------------------------------------------------
# Legacy compatibility + classroom / lesson flow
# ---------------------------------------------------------------------------

@app.post("/students")
def create_student_legacy(db: Annotated[Session, Depends(get_db)], full_name: str = Form(...), phone: str = Form(""), email: str = Form("")):
    node = db.query(Node).order_by(Node.id.asc()).first()
    if not node:
        node = Node(name="Demo Κόμβος", municipality="ΘΕΣΣΑΛΟΝΙΚΗΣ")
        db.add(node); db.flush()
    student = Student(node_id=node.id, full_name=full_name.strip(), phone=phone.strip(), email=email.strip(), status="selected")
    db.add(student); db.commit()
    write_audit(db, "student_created", "student", student.id, actor="teacher", detail={"full_name": student.full_name})
    return RedirectResponse(f"/nodes/{node.id}", status_code=303)

@app.post("/classes")
def create_classroom_legacy(db: Annotated[Session, Depends(get_db)], name: str = Form(...), program_name: str = Form("Ψηφιακή Ενδυνάμωση"), teacher_name: str = Form(""), location: str = Form("")):
    node = db.query(Node).filter(Node.name == (location.strip() or "Demo Κόμβος")).first()
    if not node:
        node = Node(name=location.strip() or "Demo Κόμβος", municipality="ΘΕΣΣΑΛΟΝΙΚΗΣ")
        db.add(node); db.flush()
    c = Classroom(node_id=node.id, name=name.strip(), program_name=program_name.strip(), teacher_name=teacher_name.strip(), location=node.name)
    db.add(c); db.commit()
    write_audit(db, "classroom_created", "classroom", c.id, actor="teacher", detail={"name": c.name})
    return RedirectResponse(f"/nodes/{node.id}", status_code=303)

@app.get("/classes/{class_id}", response_class=HTMLResponse)
def class_detail(request: Request, class_id: int, db: Annotated[Session, Depends(get_db)]):
    classroom = db.query(Classroom).options(
        joinedload(Classroom.node).joinedload(Node.students).joinedload(Student.enrollments),
        joinedload(Classroom.enrollments).joinedload(Enrollment.student),
        joinedload(Classroom.lessons),
    ).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(404, "Classroom not found")
    lessons = sorted(classroom.lessons, key=lambda l: l.starts_at, reverse=True)
    enrollments = [e for e in classroom.enrollments if e.status == "active"]
    enrolled_ids = {e.student_id for e in enrollments}
    candidates = []
    if classroom.node:
        for student in classroom.node.students:
            if student.status in {"selected", "unable_rejected"} and student.id not in enrolled_ids:
                candidates.append(student)
    return render(request, "class_detail.html", {"classroom": classroom, "lessons": lessons, "enrollments": sorted(enrollments, key=lambda e: e.student.full_name), "students": sorted(candidates, key=lambda s: s.full_name), "enrolled_ids": enrolled_ids})

@app.post("/classes/{class_id}/enroll")
def enroll_student(class_id: int, db: Annotated[Session, Depends(get_db)], student_id: int = Form(...)):
    classroom = db.get(Classroom, class_id)
    if not classroom:
        raise HTTPException(404, "Classroom not found")
    exists = db.query(Enrollment).filter(Enrollment.classroom_id == class_id, Enrollment.student_id == student_id, Enrollment.status == "active").first()
    if not exists:
        db.add(Enrollment(classroom_id=class_id, student_id=student_id, status="active")); db.commit()
        write_audit(db, "student_enrolled", "classroom", class_id, actor="teacher", detail={"student_id": student_id})
    return RedirectResponse(f"/classes/{class_id}", status_code=303)

@app.post("/classes/{class_id}/lessons")
def create_lesson(class_id: int, request: Request, db: Annotated[Session, Depends(get_db)], title: str = Form("Μάθημα"), starts_at: str = Form(""), duration_minutes: int = Form(120), teaching_hours: int = Form(2)):
    classroom = db.query(Classroom).options(joinedload(Classroom.enrollments)).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(404, "Classroom not found")
    start_dt = datetime.fromisoformat(starts_at) if starts_at else now_utc()
    max_teaching_hours = max(1, duration_minutes // 45)
    if teaching_hours > max_teaching_hours:
        teaching_hours = max_teaching_hours
    lesson = Lesson(classroom_id=class_id, title=title.strip() or "Μάθημα", starts_at=start_dt, duration_minutes=duration_minutes, teaching_hours=teaching_hours, created_by=classroom.teacher_name or actor_name(request))
    db.add(lesson); db.flush()
    for enrollment in classroom.enrollments:
        if enrollment.status == "active":
            db.add(Attendance(lesson_id=lesson.id, student_id=enrollment.student_id))
    db.commit()
    write_audit(db, "lesson_opened", "lesson", lesson.id, actor=lesson.created_by, detail={"classroom_id": class_id})
    return RedirectResponse(f"/lessons/{lesson.id}", status_code=303)

@app.get("/lessons/{lesson_id}", response_class=HTMLResponse)
def lesson_detail(request: Request, lesson_id: int, db: Annotated[Session, Depends(get_db)]):
    lesson = db.query(Lesson).options(joinedload(Lesson.classroom).joinedload(Classroom.node), joinedload(Lesson.attendance_rows).joinedload(Attendance.student), joinedload(Lesson.attendance_rows).joinedload(Attendance.makeup)).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    rows = sorted(lesson.attendance_rows, key=lambda a: a.student.full_name)
    links = {row.id: student_link(row) for row in rows}
    sms_messages = db.query(SmsMessage).filter(SmsMessage.lesson_id == lesson.id).order_by(SmsMessage.created_at.desc()).limit(50).all()
    return render(request, "lesson_detail.html", {"lesson": lesson, "rows": rows, "links": links, "sms_messages": sms_messages})

@app.post("/lessons/{lesson_id}/attendance/{attendance_id}/manual")
def manual_attendance(lesson_id: int, attendance_id: int, request: Request, db: Annotated[Session, Depends(get_db)], status: str = Form(...), reason: str = Form(""), notes: str = Form("")):
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    assert_lesson_open(lesson)
    att = db.get(Attendance, attendance_id)
    if not att or att.lesson_id != lesson_id:
        raise HTTPException(404, "Attendance row not found")
    if status not in {"present", "absent", "late", "left_early"}:
        raise HTTPException(400, "Invalid status")
    att.status = status
    att.confirmation_method = "teacher_manual"
    att.manual_reason = reason.strip()
    att.notes = notes.strip()
    att.teacher_confirmed_at = now_utc()
    att.finalized_at = now_utc()
    db.commit()
    write_audit(db, "attendance_manual_set", "attendance", att.id, actor=actor_name(request), detail={"status": status, "reason": reason})
    return RedirectResponse(f"/lessons/{lesson_id}", status_code=303)

@app.post("/lessons/{lesson_id}/send-sms")
def send_lesson_sms(lesson_id: int, request: Request, db: Annotated[Session, Depends(get_db)]):
    lesson = db.query(Lesson).options(
        joinedload(Lesson.attendance_rows).joinedload(Attendance.student),
        joinedload(Lesson.classroom),
    ).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    assert_lesson_open(lesson)

    sent = 0
    failed = 0
    skipped = 0
    for att in lesson.attendance_rows:
        student = att.student
        if not student.phone:
            skipped += 1
            msg = SmsMessage(lesson_id=lesson.id, attendance_id=att.id, student_id=student.id, to_phone="", body="", provider=settings.sms_provider, status="no_phone", provider_response="No phone number")
            db.add(msg)
            continue
        body = sms_body_for_attendance(att)
        result = send_sms(student.phone, body)
        msg = SmsMessage(
            lesson_id=lesson.id, attendance_id=att.id, student_id=student.id,
            to_phone=student.phone, body=body, provider=result.provider, status=result.status,
            provider_response=result.response, sent_at=now_utc() if result.ok else None,
        )
        db.add(msg)
        if result.ok:
            sent += 1
        else:
            failed += 1
    db.commit()
    write_audit(db, "sms_links_sent", "lesson", lesson.id, actor=actor_name(request), detail={"sent": sent, "failed": failed, "skipped": skipped, "provider": settings.sms_provider})
    return RedirectResponse(f"/lessons/{lesson_id}?sms_sent={sent}&sms_failed={failed}&sms_skipped={skipped}", status_code=303)

@app.post("/api/lessons/{lesson_id}/scan")
async def scan_student_qr(lesson_id: int, request: Request, db: Annotated[Session, Depends(get_db)]):
    data = await request.json()
    raw_token = str(data.get("token", "")).strip()
    if raw_token.startswith("THRONOS_EDUPRESENCE_SCAN:"):
        raw_token = raw_token.split(":", 1)[1]
    payload = verify_token(raw_token, expected_type="teacher_scan")
    if int(payload.get("lesson_id", 0)) != lesson_id:
        raise HTTPException(400, "Token belongs to another lesson")
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    assert_lesson_open(lesson)
    att = db.get(Attendance, int(payload["attendance_id"]))
    if not att or att.lesson_id != lesson_id:
        raise HTTPException(404, "Attendance row not found")
    att.status = "present"
    att.confirmation_method = "student_qr_teacher_scan"
    att.teacher_confirmed_at = now_utc()
    att.finalized_at = now_utc()
    db.commit()
    write_audit(db, "attendance_qr_scanned", "attendance", att.id, actor=lesson.created_by, detail={"student_id_hash": hash_identity("student", att.student_id)})
    return {"ok": True, "attendance_id": att.id, "status": att.status, "student_name": att.student.full_name}

@app.get("/api/lessons/{lesson_id}/student-links")
def lesson_student_links(lesson_id: int, db: Annotated[Session, Depends(get_db)]):
    lesson = db.query(Lesson).options(joinedload(Lesson.attendance_rows).joinedload(Attendance.student)).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    return {
        "ok": True,
        "lesson_id": lesson.id,
        "links": [
            {"attendance_id": att.id, "student": att.student.full_name, "phone": att.student.phone, "link": student_link(att)}
            for att in sorted(lesson.attendance_rows, key=lambda a: a.student.full_name)
        ],
    }

@app.post("/lessons/{lesson_id}/close")
def close_lesson(lesson_id: int, request: Request, db: Annotated[Session, Depends(get_db)]):
    lesson = db.query(Lesson).options(joinedload(Lesson.attendance_rows).joinedload(Attendance.student), joinedload(Lesson.classroom)).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    assert_lesson_open(lesson)
    for att in lesson.attendance_rows:
        if att.status == "pending":
            att.status = "absent"; att.confirmation_method = "no_signal"; att.finalized_at = now_utc()
        elif att.status == "student_confirmed":
            att.status = "student_only_unverified"; att.confirmation_method = "student_self_confirmed"; att.finalized_at = now_utc()
        payload = {
            "service": "edu_presence",
            "event_type": "attendance_finalized",
            "lesson_hash": hash_identity("lesson", lesson.id),
            "student_hash": hash_identity("student", att.student_id),
            "teacher_hash": hash_identity("teacher", lesson.created_by or lesson.classroom.teacher_name or "teacher"),
            "attendance_status": att.status,
            "confirmation_method": att.confirmation_method,
            "manual_reason_hash": hash_identity("manual_reason", att.manual_reason) if att.manual_reason else "",
            "lesson_started_at": lesson.starts_at.isoformat(),
            "finalized_at": (att.finalized_at or now_utc()).isoformat(),
        }
        attest = record_attestation(db, "attendance_finalized", payload)
        att.attestation_hash = attest.payload_hash
    lesson.status = "closed"; lesson.closed_at = now_utc()
    db.commit()
    write_audit(db, "lesson_closed", "lesson", lesson.id, actor=actor_name(request), detail={"rows": len(lesson.attendance_rows)})
    return RedirectResponse(f"/lessons/{lesson_id}/print", status_code=303)

@app.get("/lessons/{lesson_id}/print", response_class=HTMLResponse)
def lesson_print(request: Request, lesson_id: int, db: Annotated[Session, Depends(get_db)]):
    lesson = db.query(Lesson).options(joinedload(Lesson.classroom).joinedload(Classroom.node), joinedload(Lesson.attendance_rows).joinedload(Attendance.student)).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    rows = sorted(lesson.attendance_rows, key=lambda a: a.student.full_name)
    return render(request, "lesson_print.html", {"lesson": lesson, "rows": rows})

@app.get("/s/{token}", response_class=HTMLResponse)
def student_checkin(request: Request, token: str, db: Annotated[Session, Depends(get_db)]):
    payload = verify_token(token, expected_type="student_checkin")
    att = db.query(Attendance).options(joinedload(Attendance.student), joinedload(Attendance.lesson).joinedload(Lesson.classroom)).filter(Attendance.id == int(payload["attendance_id"])).first()
    if not att:
        raise HTTPException(404, "Attendance not found")
    if att.lesson.status != "open":
        return render(request, "student_checkin.html", {"token": token, "attendance": att, "closed": True})
    if att.status == "pending":
        att.status = "student_confirmed"; att.confirmation_method = "student_self_confirmed"; att.student_confirmed_at = now_utc()
        db.commit()
        write_audit(db, "student_self_confirmed", "attendance", att.id, actor="student", detail={"student_id_hash": hash_identity("student", att.student_id)})
    return render(request, "student_checkin.html", {"token": token, "attendance": att, "closed": False})

@app.get("/s/{token}/qr.png")
def student_qr(token: str, db: Annotated[Session, Depends(get_db)]):
    payload = verify_token(token, expected_type="student_checkin")
    att = db.query(Attendance).options(joinedload(Attendance.lesson)).filter(Attendance.id == int(payload["attendance_id"])).first()
    if not att:
        raise HTTPException(404, "Attendance not found")
    if att.lesson.status != "open":
        raise HTTPException(409, "Lesson is closed")
    exp = int(time.time() + settings.qr_ttl_seconds)
    scan_token = sign_payload({"typ": "teacher_scan", "attendance_id": att.id, "lesson_id": att.lesson_id, "student_id": att.student_id, "exp": exp})
    qr_data = f"THRONOS_EDUPRESENCE_SCAN:{scan_token}"
    return Response(content=qr_png_bytes(qr_data), media_type="image/png", headers={"Cache-Control": "no-store"})

@app.post("/attendance/{attendance_id}/makeup")
def create_makeup(attendance_id: int, request: Request, db: Annotated[Session, Depends(get_db)]):
    att = db.query(Attendance).options(joinedload(Attendance.lesson), joinedload(Attendance.student)).filter(Attendance.id == attendance_id).first()
    if not att:
        raise HTTPException(404, "Attendance not found")
    if att.status not in {"absent", "student_only_unverified"}:
        raise HTTPException(409, "Makeup is only for absence/unverified")
    existing = db.query(Makeup).filter(Makeup.original_attendance_id == attendance_id).first()
    if existing:
        return RedirectResponse(f"/makeups/{existing.id}", status_code=303)
    m = Makeup(original_attendance_id=att.id, original_lesson_id=att.lesson_id, student_id=att.student_id, teacher_name=att.lesson.created_by)
    db.add(m); db.commit()
    write_audit(db, "makeup_created", "makeup", m.id, actor=actor_name(request), detail={"original_attendance_id": att.id})
    return RedirectResponse(f"/makeups/{m.id}", status_code=303)

@app.get("/makeups/{makeup_id}", response_class=HTMLResponse)
def makeup_detail(request: Request, makeup_id: int, db: Annotated[Session, Depends(get_db)]):
    makeup = db.query(Makeup).options(joinedload(Makeup.student), joinedload(Makeup.original_lesson).joinedload(Lesson.classroom), joinedload(Makeup.original_attendance)).filter(Makeup.id == makeup_id).first()
    if not makeup:
        raise HTTPException(404, "Makeup not found")
    return render(request, "makeup_detail.html", {"makeup": makeup})

@app.post("/makeups/{makeup_id}/complete")
def complete_makeup(makeup_id: int, request: Request, db: Annotated[Session, Depends(get_db)], makeup_date: str = Form(...), duration_minutes: int = Form(120), topic: str = Form(""), student_signature_note: str = Form("Υπογράφηκε φυσικά")):
    makeup = db.query(Makeup).options(joinedload(Makeup.student), joinedload(Makeup.original_lesson)).filter(Makeup.id == makeup_id).first()
    if not makeup:
        raise HTTPException(404, "Makeup not found")
    if makeup.status == "completed":
        return RedirectResponse(f"/makeups/{makeup.id}/print", status_code=303)
    dt = datetime.fromisoformat(makeup_date)
    makeup.makeup_date = dt; makeup.duration_minutes = duration_minutes; makeup.topic = topic.strip(); makeup.student_signature_note = student_signature_note.strip()
    makeup.status = "completed"; makeup.completed_at = now_utc()
    evidence = {"makeup_id": makeup.id, "original_lesson_id": makeup.original_lesson_id, "student_id_hash": hash_identity("student", makeup.student_id), "makeup_date": dt.isoformat(), "duration_minutes": duration_minutes, "topic": makeup.topic}
    _, makeup.evidence_hash = canonical_hash(evidence)
    payload = {
        "service": "edu_presence",
        "event_type": "makeup_attendance_completed",
        "original_lesson_hash": hash_identity("lesson", makeup.original_lesson_id),
        "student_hash": hash_identity("student", makeup.student_id),
        "teacher_hash": hash_identity("teacher", makeup.teacher_name or makeup.original_lesson.created_by),
        "makeup_document_hash": makeup.evidence_hash,
        "original_absence_date": makeup.original_lesson.starts_at.date().isoformat(),
        "makeup_date": dt.date().isoformat(),
        "duration_minutes": duration_minutes,
        "completed_at": makeup.completed_at.isoformat(),
    }
    attest = record_attestation(db, "makeup_attendance_completed", payload)
    makeup.attestation_hash = attest.payload_hash
    db.commit()
    write_audit(db, "makeup_completed", "makeup", makeup.id, actor=actor_name(request), detail={"attestation_hash": makeup.attestation_hash})
    return RedirectResponse(f"/makeups/{makeup.id}/print", status_code=303)

@app.get("/makeups/{makeup_id}/print", response_class=HTMLResponse)
def makeup_print(request: Request, makeup_id: int, db: Annotated[Session, Depends(get_db)]):
    makeup = db.query(Makeup).options(joinedload(Makeup.student), joinedload(Makeup.original_lesson).joinedload(Lesson.classroom), joinedload(Makeup.original_attendance)).filter(Makeup.id == makeup_id).first()
    if not makeup:
        raise HTTPException(404, "Makeup not found")
    return render(request, "makeup_print.html", {"makeup": makeup})
