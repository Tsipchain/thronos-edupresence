from __future__ import annotations
import csv
import hashlib
import io
import secrets
import time
from typing import Annotated
from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.routing import APIRouter
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.config import settings
from app.db import get_db
from app.models import AdminUser, Classroom, Enrollment, Node, Student, now_utc
from app.attestation import write_audit
from app.security import sign_payload, verify_token
from app.sms import send_sms
from app.roles import (
    SUPER_ADMIN, TENANT_DIRECTOR, TEACHER, STUDENT, has_at_least,
)

router = APIRouter(prefix="/admin", tags=["admin-ui"])
templates = Jinja2Templates(directory="app/templates")

_COOKIE = settings.session_cookie_name or "thronos_admin"
_CSRF_COOKIE = "thronos_csrf"
_TTL = settings.session_ttl_hours * 3600


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _key_ok(key: str) -> bool:
    if settings.environment == "production" and not settings.admin_api_key:
        return False
    effective_key = settings.admin_api_key or settings.token_secret
    return bool(key) and key == effective_key


def _admin_session(request: Request) -> dict | None:
    token = request.cookies.get(_COOKIE, "")
    if not token:
        return None
    try:
        return verify_token(token, expected_type="admin_session")
    except Exception:
        return None


def _require_role(request: Request, minimum_role: str) -> tuple[dict | None, Response | None]:
    """Check session and role. Returns (session_info, None) on success,
    or (None, error_response) on failure."""
    session_info = _admin_session(request)
    if not session_info:
        return None, RedirectResponse("/admin", status_code=303)
    role = session_info.get("role", "")
    if not has_at_least(role, minimum_role):
        return None, Response(content="Forbidden: insufficient role", status_code=403)
    return session_info, None


def _enforce_tenant(session_info: dict, node_id: int | None, db: Session) -> Response | None:
    """Verify the session's tenant_id matches the node's tenant scope.
    super_admin bypasses. Returns an error response or None on success."""
    if has_at_least(session_info.get("role", ""), SUPER_ADMIN):
        return None
    tenant_id = session_info.get("tenant_id")
    if not tenant_id:
        return Response(content="Forbidden: no tenant scope in session", status_code=403)
    if node_id:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return RedirectResponse("/admin", status_code=303)
        node_tenant = str(node.id)
        if tenant_id != node_tenant:
            return Response(content="Forbidden: cross-tenant access denied", status_code=403)
    return None


def _verify_csrf(request: Request, csrf_token: str) -> bool:
    """Double-submit cookie CSRF: form value must match cookie."""
    cookie_val = request.cookies.get(_CSRF_COOKIE, "")
    if not cookie_val or not csrf_token:
        return False
    return secrets.compare_digest(cookie_val, csrf_token)


def _set_session_cookie(response: Response, role: str = SUPER_ADMIN,
                        tenant_id: str = "", student_id: int | None = None,
                        thr_wallet: str = "") -> Response:
    payload = {
        "typ": "admin_session",
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + _TTL,
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    if student_id:
        payload["student_id"] = student_id
    if thr_wallet:
        payload["thr_wallet"] = thr_wallet
    token = sign_payload(payload)
    response.set_cookie(
        key=_COOKIE,
        value=token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=_TTL,
        path="/",
    )
    csrf = secrets.token_hex(16)
    response.set_cookie(
        key=_CSRF_COOKIE,
        value=csrf,
        httponly=False,
        secure=settings.environment == "production",
        samesite="strict",
        max_age=_TTL,
        path="/",
    )
    return response


def _clear_session_cookie(response: Response) -> Response:
    response.delete_cookie(key=_COOKIE, path="/")
    response.delete_cookie(key=_CSRF_COOKIE, path="/")
    return response


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def admin_home(request: Request, msg: str = ""):
    session_info, err = _require_role(request, STUDENT)
    if err:
        return templates.TemplateResponse(request, "admin_login.html",
            {"request": request, "error": ""})
    db = next(get_db())
    nodes = db.query(Node).options(
        joinedload(Node.classrooms).joinedload(Classroom.enrollments),
    ).order_by(Node.id).all()
    db.close()
    return templates.TemplateResponse(request, "admin_home.html",
        {"request": request, "nodes": nodes, "msg": msg})


@router.post("", response_class=HTMLResponse)
def admin_login(request: Request, key: str = Form("")):
    if not _key_ok(key):
        return templates.TemplateResponse(request, "admin_login.html",
            {"request": request, "error": "Λάθος κλειδί Admin."})
    db = next(get_db())
    try:
        admin_user = db.query(AdminUser).filter(
            AdminUser.api_key_hash == _hash_key(key),
            AdminUser.is_active == True,
        ).first()
    finally:
        db.close()
    if admin_user:
        effective_role = admin_user.role if admin_user.role in (
            SUPER_ADMIN, TENANT_DIRECTOR, TEACHER, STUDENT
        ) else STUDENT
        tenant_id = str(admin_user.tenant_node_id) if admin_user.tenant_node_id else ""
        student_id = admin_user.student_id
        thr_wallet = admin_user.thr_wallet or ""
    else:
        effective_role = SUPER_ADMIN
        tenant_id = ""
        student_id = None
        thr_wallet = ""
    response = RedirectResponse("/admin", status_code=303)
    _set_session_cookie(response, role=effective_role, tenant_id=tenant_id,
                        student_id=student_id, thr_wallet=thr_wallet)
    return response


@router.get("/logout")
def admin_logout():
    response = RedirectResponse("/admin", status_code=303)
    _clear_session_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Node management (super_admin only)
# ---------------------------------------------------------------------------

@router.post("/nodes/create")
def create_node(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(...),
    municipality: str = Form("ΘΕΣΣΑΛΟΝΙΚΗΣ"),
    responsible_name: str = Form(""),
    capacity: int = Form(15),
):
    session_info, err = _require_role(request, SUPER_ADMIN)
    if err:
        return err
    existing = db.query(Node).filter(Node.name == name.strip()).first()
    if existing:
        return RedirectResponse("/admin?msg=Ο+κόμβος+υπάρχει+ήδη", status_code=303)
    node = Node(
        name=name.strip(),
        municipality=municipality.strip() or "ΘΕΣΣΑΛΟΝΙΚΗΣ",
        responsible_name=responsible_name.strip(),
        capacity=capacity,
    )
    db.add(node)
    db.commit()
    write_audit(db, "admin_node_created", "node", node.id,
                actor="admin", detail={"name": node.name})
    return RedirectResponse("/admin?msg=Κόμβος+δημιουργήθηκε", status_code=303)


# ---------------------------------------------------------------------------
# CSV / Excel import (tenant_director+ only)
# ---------------------------------------------------------------------------

@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    session_info, err = _require_role(request, TENANT_DIRECTOR)
    if err:
        return err
    db = next(get_db())
    nodes = db.query(Node).order_by(Node.name).all()
    db.close()
    return templates.TemplateResponse(request, "admin_import_csv.html",
        {"request": request, "nodes": nodes, "result": None})


@router.post("/import/upload")
async def import_upload(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    node_id: str = Form(""),
    new_node_name: str = Form(""),
    municipality: str = Form("ΘΕΣΣΑΛΟΝΙΚΗΣ"),
    classroom_name: str = Form(...),
    teacher_name: str = Form(""),
    teacher_phone: str = Form(""),
    target_hours: int = Form(40),
    file: UploadFile = File(...),
):
    session_info, err = _require_role(request, TENANT_DIRECTOR)
    if err:
        return err

    # Resolve or create node
    if node_id and node_id.isdigit():
        node = db.query(Node).filter(Node.id == int(node_id)).first()
    else:
        node = None

    if not node and new_node_name.strip():
        node = db.query(Node).filter(Node.name == new_node_name.strip()).first()
        if not node:
            node = Node(
                name=new_node_name.strip(),
                municipality=municipality.strip() or "ΘΕΣΣΑΛΟΝΙΚΗΣ",
                responsible_name=teacher_name.strip(),
                capacity=30,
            )
            db.add(node)
            db.flush()

    if not node:
        nodes = db.query(Node).order_by(Node.name).all()
        return templates.TemplateResponse(request, "admin_import_csv.html", {
            "request": request, "nodes": nodes,
            "result": {"error": "Επιλέξτε ή δημιουργήστε κόμβο."},
        })

    # Tenant isolation: non-super_admin must belong to this node's tenant
    tenant_err = _enforce_tenant(session_info, node.id, db)
    if tenant_err:
        return tenant_err

    # Parse file
    content = await file.read()
    filename = (file.filename or "").lower()
    rows = []

    try:
        if filename.endswith(".csv"):
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        elif filename.endswith((".xlsx", ".xls")):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            headers = [str(c.value or "").strip().lower() for c in next(ws.iter_rows(min_row=1, max_row=1))]
            for row in ws.iter_rows(min_row=2, values_only=True):
                rows.append(dict(zip(headers, [str(v or "").strip() for v in row])))
        else:
            nodes = db.query(Node).order_by(Node.name).all()
            return templates.TemplateResponse(request, "admin_import_csv.html", {
                "request": request, "nodes": nodes,
                "result": {"error": "Αποδεκτοί μόνο .csv και .xlsx"},
            })
    except Exception as exc:
        nodes = db.query(Node).order_by(Node.name).all()
        return templates.TemplateResponse(request, "admin_import_csv.html", {
            "request": request, "nodes": nodes,
            "result": {"error": f"Σφάλμα ανάγνωσης αρχείου: {exc}"},
        })

    # Column name aliases
    def _get(row: dict, *keys: str) -> str:
        for k in keys:
            if k in row and row[k]:
                return str(row[k]).strip()
        return ""

    # Create classroom
    classroom = Classroom(
        node_id=node.id,
        name=classroom_name.strip(),
        teacher_name=teacher_name.strip(),
        teacher_phone=teacher_phone.strip(),
        location=node.name,
        target_teaching_hours=target_hours,
        l2e_tenant_id=settings.l2e_tenant_id,
    )
    db.add(classroom)
    db.flush()

    created = []
    skipped = []
    for i, row in enumerate(rows, 1):
        full_name = _get(row, "full_name", "ονοματεπώνυμο", "name", "όνομα")
        if not full_name:
            skipped.append(f"Γραμμή {i}: κενό όνομα")
            continue
        phone = _get(row, "phone", "τηλέφωνο", "mobile", "tel")
        ext_ref = _get(row, "external_ref", "ref", "κωδικός", "id")
        gender = _get(row, "gender", "φύλο")
        student = Student(
            node_id=node.id,
            full_name=full_name,
            phone=phone,
            external_ref=ext_ref or f"IMP-{i:03d}",
            gender=gender,
            status="selected",
            priority_order=i,
        )
        db.add(student)
        db.flush()
        db.add(Enrollment(classroom_id=classroom.id, student_id=student.id, status="active"))
        created.append(full_name)

    db.commit()
    write_audit(db, "admin_csv_import", "classroom", classroom.id,
                actor="admin", detail={"created": len(created), "skipped": len(skipped)})

    return templates.TemplateResponse(request, "admin_import_csv.html", {
        "request": request,
        "nodes": db.query(Node).order_by(Node.name).all(),
        "result": {
            "ok": True,
            "classroom_id": classroom.id,
            "classroom_name": classroom.name,
            "node_name": node.name,
            "created": created,
            "skipped": skipped,
        },
    })


# ---------------------------------------------------------------------------
# Phone management per classroom (teacher+ only, with tenant isolation)
# ---------------------------------------------------------------------------

@router.get("/class/{class_id}", response_class=HTMLResponse)
def admin_class(
    request: Request, class_id: int,
    sms_sent: int = 0, sms_failed: int = 0, saved: int = 0,
):
    session_info, err = _require_role(request, TEACHER)
    if err:
        return err
    db = next(get_db())
    classroom = db.query(Classroom).options(
        joinedload(Classroom.node),
        joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).filter(Classroom.id == class_id).first()
    if not classroom:
        db.close()
        return RedirectResponse("/admin", status_code=303)
    tenant_err = _enforce_tenant(session_info, classroom.node_id, db)
    if tenant_err:
        db.close()
        return tenant_err
    enrollments = sorted(
        [e for e in classroom.enrollments if e.status == "active"],
        key=lambda e: e.student.full_name or "",
    )
    db.close()
    return templates.TemplateResponse(request, "admin_phones.html", {
        "request": request, "classroom": classroom,
        "enrollments": enrollments,
        "sms_sent": sms_sent, "sms_failed": sms_failed, "saved": saved,
    })


@router.post("/class/{class_id}/update-phones")
async def update_phones(
    request: Request, class_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    session_info, err = _require_role(request, TEACHER)
    if err:
        return err
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if classroom:
        tenant_err = _enforce_tenant(session_info, classroom.node_id, db)
        if tenant_err:
            return tenant_err
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
    return RedirectResponse(f"/admin/class/{class_id}?saved={saved}", status_code=303)


@router.post("/class/{class_id}/send-sms")
def admin_send_sms(
    request: Request,
    class_id: int,
    db: Annotated[Session, Depends(get_db)],
    message_template: str = Form("Γεια {name}! Παρακολουθήστε την παρουσία σας στο ThrEDU: {url}"),
):
    session_info, err = _require_role(request, TEACHER)
    if err:
        return err
    classroom = db.query(Classroom).options(
        joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).filter(Classroom.id == class_id).first()
    if not classroom:
        return RedirectResponse("/admin", status_code=303)
    tenant_err = _enforce_tenant(session_info, classroom.node_id, db)
    if tenant_err:
        return tenant_err
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
        f"/admin/class/{class_id}?sms_sent={sent}&sms_failed={failed}",
        status_code=303,
    )
