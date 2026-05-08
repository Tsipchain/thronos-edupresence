from __future__ import annotations
from typing import Annotated
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRouter
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.config import settings
from app.db import get_db
from app.models import Classroom, Enrollment, Node, Student
from app.attestation import write_audit
from app.sms import send_sms

router = APIRouter(prefix="/admin", tags=["admin-ui"])
templates = Jinja2Templates(directory="app/templates")


def _key_ok(key: str) -> bool:
    return bool(key) and key == settings.token_secret


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def admin_home(request: Request, key: str = "", error: str = ""):
    if not key or not _key_ok(key):
        return templates.TemplateResponse("admin_login.html",
            {"request": request, "error": "Λάθος κλειδί." if (key and not _key_ok(key)) else ""})
    db = next(get_db())
    classrooms = db.query(Classroom).options(
        joinedload(Classroom.node),
        joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).order_by(Classroom.id).all()
    db.close()
    return templates.TemplateResponse("admin_home.html",
        {"request": request, "key": key, "classrooms": classrooms})


@router.post("", response_class=HTMLResponse)
def admin_login(request: Request, key: str = Form("")):
    if not _key_ok(key):
        return templates.TemplateResponse("admin_login.html",
            {"request": request, "error": "Λάθος κλειδί Admin."})
    return RedirectResponse(f"/admin?key={key}", status_code=303)


@router.get("/class/{class_id}", response_class=HTMLResponse)
def admin_class(
    request: Request, class_id: int,
    key: str = "", sms_sent: int = 0, sms_failed: int = 0, saved: int = 0,
):
    if not _key_ok(key):
        return RedirectResponse("/admin", status_code=303)
    db = next(get_db())
    classroom = db.query(Classroom).options(
        joinedload(Classroom.node),
        joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).filter(Classroom.id == class_id).first()
    db.close()
    if not classroom:
        return RedirectResponse(f"/admin?key={key}", status_code=303)
    enrollments = sorted(
        [e for e in classroom.enrollments if e.status == "active"],
        key=lambda e: e.student.full_name or "",
    )
    return templates.TemplateResponse("admin_phones.html", {
        "request": request, "key": key, "classroom": classroom,
        "enrollments": enrollments,
        "sms_sent": sms_sent, "sms_failed": sms_failed, "saved": saved,
    })


@router.post("/class/{class_id}/update-phones")
async def update_phones(
    request: Request, class_id: int,
    db: Annotated[Session, Depends(get_db)],
    key: str = Form(""),
):
    if not _key_ok(key):
        return RedirectResponse("/admin", status_code=303)
    form = await request.form()
    saved = 0
    for field, value in form.items():
        if field.startswith("phone_"):
            student_id = int(field.split("_", 1)[1])
            student = db.query(Student).filter(Student.id == student_id).first()
            if student:
                student.phone = str(value).strip()
                saved += 1
    db.commit()
    write_audit(db, "admin_phones_updated", "classroom", class_id,
                actor="admin", detail={"updated": saved})
    return RedirectResponse(f"/admin/class/{class_id}?key={key}&saved={saved}", status_code=303)


@router.post("/class/{class_id}/send-sms")
def admin_send_sms(
    class_id: int,
    db: Annotated[Session, Depends(get_db)],
    key: str = Form(""),
    message_template: str = Form("Γεια {name}! Παρακολουθήστε την παρουσία σας στο ThrEDU: {url}"),
):
    if not _key_ok(key):
        return RedirectResponse("/admin", status_code=303)
    classroom = db.query(Classroom).options(
        joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).filter(Classroom.id == class_id).first()
    if not classroom:
        return RedirectResponse(f"/admin?key={key}", status_code=303)
    enrollments = [e for e in classroom.enrollments if e.status == "active"]
    sent = failed = skipped = 0
    for enr in enrollments:
        s = enr.student
        if not s or not s.phone:
            skipped += 1
            continue
        first_name = s.full_name.split()[0] if s.full_name else s.full_name
        url = f"{settings.public_base_url}/classes/{class_id}"
        body = message_template.format(name=first_name, url=url)
        result = send_sms(s.phone, body)
        if result.ok:
            sent += 1
        else:
            failed += 1
    write_audit(db, "admin_bulk_sms", "classroom", class_id,
                actor="admin", detail={"sent": sent, "failed": failed, "skipped": skipped})
    db.commit()
    return RedirectResponse(
        f"/admin/class/{class_id}?key={key}&sms_sent={sent}&sms_failed={failed}",
        status_code=303,
    )
