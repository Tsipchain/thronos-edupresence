"""Tenant/role isolation, admin session security, and L2E bridge tests.

All L2E outbox tests use the DB-backed outbox — no in-memory state.
All login tests confirm role/tenant derived from DB, never form params.
"""
import hashlib
import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.roles import (
    SUPER_ADMIN, TENANT_DIRECTOR, TEACHER, STUDENT,
    ALL_ROLES, has_at_least,
)
from app.security import sign_payload
from app.config import settings
from app.admin_ui import _COOKIE, _hash_key
import app.admin_ui as admin_ui_module
from app.models import AdminUser, L2EOutboxEntry


@pytest.fixture
def _patch_admin_db(_fresh_db):
    """Patch admin_ui's direct get_db calls to use the test DB."""
    session_factory = _fresh_db
    def _fake_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            pass
    original = admin_ui_module.get_db
    admin_ui_module.get_db = _fake_get_db
    yield session_factory()
    admin_ui_module.get_db = original


# ── Helpers ──────────────────────────────────────────────────────────────

def _set_admin_cookie(client: TestClient) -> None:
    token = sign_payload({
        "typ": "admin_session",
        "role": SUPER_ADMIN,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    })
    client.cookies.set(_COOKIE, token)


def _set_role_cookie(client: TestClient, role: str,
                     tenant_id: str = "") -> None:
    payload = {
        "typ": "admin_session",
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    token = sign_payload(payload)
    client.cookies.set(_COOKIE, token)


# ── Role hierarchy ───────────────────────────────────────────────────────


def test_role_hierarchy_ordering():
    assert has_at_least(SUPER_ADMIN, STUDENT)
    assert has_at_least(SUPER_ADMIN, TEACHER)
    assert has_at_least(SUPER_ADMIN, TENANT_DIRECTOR)
    assert has_at_least(SUPER_ADMIN, SUPER_ADMIN)

    assert has_at_least(TENANT_DIRECTOR, STUDENT)
    assert has_at_least(TENANT_DIRECTOR, TEACHER)
    assert has_at_least(TENANT_DIRECTOR, TENANT_DIRECTOR)
    assert not has_at_least(TENANT_DIRECTOR, SUPER_ADMIN)

    assert has_at_least(TEACHER, STUDENT)
    assert has_at_least(TEACHER, TEACHER)
    assert not has_at_least(TEACHER, TENANT_DIRECTOR)

    assert has_at_least(STUDENT, STUDENT)
    assert not has_at_least(STUDENT, TEACHER)


def test_unknown_role_denied():
    assert not has_at_least("unknown_role", STUDENT)
    assert not has_at_least(STUDENT, "unknown_role")
    assert not has_at_least("", "")


def test_all_roles_constant():
    assert len(ALL_ROLES) == 4
    assert set(ALL_ROLES) == {SUPER_ADMIN, TENANT_DIRECTOR, TEACHER, STUDENT}


# ── Admin session cookie security ────────────────────────────────────────

def test_admin_home_requires_session(client: TestClient):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 200
    assert "admin_login" in resp.text or "κλειδί" in resp.text.lower()


def test_admin_login_sets_httponly_cookie(client: TestClient, _patch_admin_db):
    effective_key = settings.admin_api_key or settings.token_secret
    resp = client.post("/admin", data={"key": effective_key}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"
    cookie_header = resp.headers.get("set-cookie", "")
    assert _COOKIE in cookie_header
    assert "httponly" in cookie_header.lower()


def test_admin_login_wrong_key_rejected(client: TestClient):
    resp = client.post("/admin", data={"key": "wrong-key"})
    assert resp.status_code == 200
    assert "Λάθος" in resp.text


def test_admin_key_not_in_redirect_urls(client: TestClient, _patch_admin_db):
    effective_key = settings.admin_api_key or settings.token_secret
    resp = client.post("/admin", data={"key": effective_key}, follow_redirects=False)
    location = resp.headers.get("location", "")
    assert "key=" not in location


def test_admin_home_with_valid_session_shows_panel(client: TestClient, _patch_admin_db):
    _set_admin_cookie(client)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "key=" not in resp.text
    client.cookies.clear()


def test_admin_logout_clears_cookie(client: TestClient):
    _set_admin_cookie(client)
    resp = client.get("/admin/logout", follow_redirects=False)
    assert resp.status_code == 303
    cookie_header = resp.headers.get("set-cookie", "")
    assert _COOKIE in cookie_header
    assert 'max-age=0' in cookie_header.lower() or '="";' in cookie_header
    client.cookies.clear()


def test_forged_session_cookie_rejected(client: TestClient):
    client.cookies.set(_COOKIE, "totally.invalid")
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "κλειδί" in resp.text.lower() or "admin_login" in resp.text
    client.cookies.clear()


def test_expired_session_cookie_rejected(client: TestClient):
    token = sign_payload({
        "typ": "admin_session",
        "role": SUPER_ADMIN,
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 10,
    })
    client.cookies.set(_COOKIE, token)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "κλειδί" in resp.text.lower() or "admin_login" in resp.text
    client.cookies.clear()


# ── Protected routes require session ─────────────────────────────────────

def test_import_page_requires_session(client: TestClient):
    resp = client.get("/admin/import", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


def test_class_page_requires_session(client: TestClient):
    resp = client.get("/admin/class/1", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


def test_node_create_requires_session(client: TestClient):
    resp = client.post("/admin/nodes/create",
        data={"name": "Test Node"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


# ── RBAC enforcement ─────────────────────────────────────────────────────

def test_import_requires_director_role(client: TestClient):
    _set_role_cookie(client, STUDENT)
    resp = client.get("/admin/import", follow_redirects=False)
    assert resp.status_code == 403
    client.cookies.clear()


def test_node_create_requires_super_admin(client: TestClient):
    _set_role_cookie(client, TEACHER)
    resp = client.post("/admin/nodes/create",
        data={"name": "Forbidden Node"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    client.cookies.clear()


def test_student_role_can_view_admin_home(client: TestClient, _patch_admin_db):
    _set_role_cookie(client, STUDENT)
    resp = client.get("/admin")
    assert resp.status_code == 200
    client.cookies.clear()


def test_teacher_role_denied_import(client: TestClient):
    _set_role_cookie(client, TEACHER)
    resp = client.get("/admin/import", follow_redirects=False)
    assert resp.status_code == 403
    client.cookies.clear()


def test_director_role_allowed_import(client: TestClient, _patch_admin_db):
    _set_role_cookie(client, TENANT_DIRECTOR)
    resp = client.get("/admin/import")
    assert resp.status_code == 200
    client.cookies.clear()


def test_form_role_param_ignored(client: TestClient, _patch_admin_db):
    """Form-supplied role and tenant_id must NOT control the session.
    Master key (no AdminUser record) → super_admin, no tenant."""
    effective_key = settings.admin_api_key or settings.token_secret
    resp = client.post("/admin",
        data={"key": effective_key, "role": TEACHER, "tenant_id": "42"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    cookie_header = resp.headers.get("set-cookie", "")
    assert _COOKIE in cookie_header
    from app.security import verify_token
    import re
    m = re.search(rf'{_COOKIE}=([^;]+)', cookie_header)
    assert m
    session_info = verify_token(m.group(1), expected_type="admin_session")
    assert session_info["role"] == SUPER_ADMIN
    assert session_info.get("tenant_id", "") == ""
    client.cookies.clear()


def test_login_with_admin_user_record(client: TestClient, _patch_admin_db):
    """When an AdminUser record exists for the key, derive role/tenant from it."""
    db_session = _patch_admin_db
    from app.models import Node
    node = Node(name="TestNode", municipality="TEST")
    db_session.add(node)
    db_session.flush()

    key = "teacher-specific-key-12345"
    admin_user = AdminUser(
        username="teacher1",
        api_key_hash=_hash_key(key),
        role=TEACHER,
        tenant_node_id=node.id,
        is_active=True,
    )
    db_session.add(admin_user)
    db_session.commit()

    with patch.object(settings, "admin_api_key", ""), \
         patch.object(settings, "token_secret", key):
        resp = client.post("/admin", data={"key": key}, follow_redirects=False)
        assert resp.status_code == 303
        cookie_header = resp.headers.get("set-cookie", "")
        import re
        m = re.search(rf'{_COOKIE}=([^;]+)', cookie_header)
        assert m
        from app.security import verify_token
        session_info = verify_token(m.group(1), expected_type="admin_session")
    assert session_info["role"] == TEACHER
    assert session_info["tenant_id"] == str(node.id)
    client.cookies.clear()


# ── Tenant isolation (data partitioning) ─────────────────────────────────

def test_classroom_scoped_to_node(client: TestClient, _patch_admin_db):
    from app.models import Node, Classroom, Student, Enrollment
    db_session = _patch_admin_db
    node_a = Node(name="Node-A", municipality="A")
    node_b = Node(name="Node-B", municipality="B")
    db_session.add_all([node_a, node_b])
    db_session.flush()

    cls_a = Classroom(node_id=node_a.id, name="Class-A", location="A")
    cls_b = Classroom(node_id=node_b.id, name="Class-B", location="B")
    db_session.add_all([cls_a, cls_b])
    db_session.flush()

    stu_a = Student(node_id=node_a.id, full_name="Student A", external_ref="A1")
    stu_b = Student(node_id=node_b.id, full_name="Student B", external_ref="B1")
    db_session.add_all([stu_a, stu_b])
    db_session.flush()

    db_session.add(Enrollment(classroom_id=cls_a.id, student_id=stu_a.id, status="active"))
    db_session.add(Enrollment(classroom_id=cls_b.id, student_id=stu_b.id, status="active"))
    db_session.commit()

    _set_admin_cookie(client)
    resp_a = client.get(f"/admin/class/{cls_a.id}")
    resp_b = client.get(f"/admin/class/{cls_b.id}")
    client.cookies.clear()

    assert resp_a.status_code == 200
    assert "Student A" in resp_a.text
    assert "Student B" not in resp_a.text

    assert resp_b.status_code == 200
    assert "Student B" in resp_b.text
    assert "Student A" not in resp_b.text


def test_nonexistent_class_redirects(client: TestClient, _patch_admin_db):
    _set_admin_cookie(client)
    resp = client.get("/admin/class/99999", follow_redirects=False)
    client.cookies.clear()
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "key=" not in location


def test_cross_tenant_access_denied(client: TestClient, _patch_admin_db):
    from app.models import Node, Classroom, Student, Enrollment
    db_session = _patch_admin_db
    node_a = Node(name="TenantA-Node", municipality="A")
    node_b = Node(name="TenantB-Node", municipality="B")
    db_session.add_all([node_a, node_b])
    db_session.flush()

    cls_b = Classroom(node_id=node_b.id, name="ClassB", location="B")
    db_session.add(cls_b)
    db_session.flush()
    stu_b = Student(node_id=node_b.id, full_name="Student B", external_ref="B1")
    db_session.add(stu_b)
    db_session.flush()
    db_session.add(Enrollment(classroom_id=cls_b.id, student_id=stu_b.id, status="active"))
    db_session.commit()

    _set_role_cookie(client, TEACHER, tenant_id=str(node_a.id))
    resp = client.get(f"/admin/class/{cls_b.id}", follow_redirects=False)
    client.cookies.clear()
    assert resp.status_code == 403


def test_super_admin_cross_tenant_allowed(client: TestClient, _patch_admin_db):
    from app.models import Node, Classroom, Student, Enrollment
    db_session = _patch_admin_db
    node_b = Node(name="OtherTenant-Node", municipality="X")
    db_session.add(node_b)
    db_session.flush()

    cls_b = Classroom(node_id=node_b.id, name="Other-Class", location="X")
    db_session.add(cls_b)
    db_session.flush()
    stu = Student(node_id=node_b.id, full_name="Other Student", external_ref="X1")
    db_session.add(stu)
    db_session.flush()
    db_session.add(Enrollment(classroom_id=cls_b.id, student_id=stu.id, status="active"))
    db_session.commit()

    _set_admin_cookie(client)
    resp = client.get(f"/admin/class/{cls_b.id}")
    client.cookies.clear()
    assert resp.status_code == 200
    assert "Other Student" in resp.text


# ── L2E bridge: DB-backed outbox tests ────────────────────────────────────

def test_pii_absent_from_bridge_payload():
    from app.l2e_bridge import (
        pseudonymous_student_ref, deterministic_event_id,
        build_attestation_hash,
    )
    tenant = "test_tenant"
    stu_ref = pseudonymous_student_ref(tenant, 42, secret="test-secret")
    att_hash = build_attestation_hash({
        "classroom_id": 1,
        "date": "2026-01-15",
        "status": "present",
        "hours": 2,
    })
    event_id = deterministic_event_id(tenant, "1", "lesson_5", 1, stu_ref)

    payload = {
        "event_id": event_id,
        "tenant_scope": tenant,
        "student_ref": stu_ref,
        "attestation_hash": att_hash,
    }
    d = json.dumps(payload)
    for pii_field in ["tax_id", "full_name", "classroom_name", "program_name"]:
        assert pii_field not in d


def test_pseudonymous_student_ref_is_opaque():
    from app.l2e_bridge import pseudonymous_student_ref
    ref = pseudonymous_student_ref("tenant_x", 123, secret="secret-key")
    assert ref
    assert len(ref) == 24
    assert "123" not in ref
    assert "tenant_x" not in ref


def test_deterministic_event_id_stable():
    from app.l2e_bridge import deterministic_event_id
    id1 = deterministic_event_id("t1", "cls_1", "lesson_5", 1, "ref_abc")
    id2 = deterministic_event_id("t1", "cls_1", "lesson_5", 1, "ref_abc")
    assert id1 == id2
    assert len(id1) == 32
    id3 = deterministic_event_id("t1", "cls_1", "lesson_6", 1, "ref_abc")
    assert id3 != id1


def test_event_id_no_time_component():
    """Event ID must be stable across calls at different times — no timestamp."""
    from app.l2e_bridge import deterministic_event_id
    id1 = deterministic_event_id("t1", "cls_1", "lesson_5", 1, "ref_abc")
    import time as _t
    _t.sleep(0.01)
    id2 = deterministic_event_id("t1", "cls_1", "lesson_5", 1, "ref_abc")
    assert id1 == id2


def test_duplicate_delivery_rejected(db_session: Session, monkeypatch):
    from app.l2e_bridge import enqueue_attestation
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)

    ok1 = enqueue_attestation(
        db_session, event_id="evt_dup_001", tenant_scope="t1",
        student_ref="ref_aaa", attestation_hash="hash_000",
        payload={"test": True},
    )
    db_session.commit()
    assert ok1 is True

    ok2 = enqueue_attestation(
        db_session, event_id="evt_dup_001", tenant_scope="t1",
        student_ref="ref_aaa", attestation_hash="hash_000",
        payload={"test": True},
    )
    assert ok2 is False


def test_l2e_disabled_by_default(db_session: Session):
    from app.l2e_bridge import enqueue_attestation
    ok = enqueue_attestation(
        db_session, event_id="evt_disabled_001", tenant_scope="t1",
        student_ref="ref_ddd", attestation_hash="hash_333",
        payload={"test": True},
    )
    assert ok is False


def test_retry_after_failure(db_session: Session, monkeypatch):
    from app.l2e_bridge import enqueue_attestation, process_outbox
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_base_url", "http://fake-l2e")

    enqueue_attestation(
        db_session, event_id="evt_retry_001", tenant_scope="t1",
        student_ref="ref_bbb", attestation_hash="hash_111",
        payload={"test": True}, max_retries=3,
    )
    db_session.commit()

    with patch("app.l2e_bridge.requests.post", side_effect=ConnectionError("down")):
        result = process_outbox(db_session)
    assert result["delivered"] == 0

    entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt_retry_001").one()
    assert entry.retry_count == 1
    assert entry.status == "pending"

    entry.next_retry_at = None
    db_session.commit()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"ok":true}'
    with patch("app.l2e_bridge.requests.post", return_value=mock_resp):
        result = process_outbox(db_session)
    assert result["delivered"] == 1

    entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt_retry_001").one()
    assert entry.status == "delivered"
    assert entry.receiver_ack == '{"ok":true}'


def test_event_dedup_after_delivery(db_session: Session, monkeypatch):
    from app.l2e_bridge import enqueue_attestation, process_outbox
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_base_url", "http://fake-l2e")

    enqueue_attestation(
        db_session, event_id="evt_dedup_001", tenant_scope="t1",
        student_ref="ref_ccc", attestation_hash="hash_222",
        payload={"test": True},
    )
    db_session.commit()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    with patch("app.l2e_bridge.requests.post", return_value=mock_resp):
        process_outbox(db_session)

    ok = enqueue_attestation(
        db_session, event_id="evt_dedup_001", tenant_scope="t1",
        student_ref="ref_ccc", attestation_hash="hash_222",
        payload={"test": True},
    )
    assert ok is False


def test_outbox_max_retries_exhausted(db_session: Session, monkeypatch):
    from app.l2e_bridge import enqueue_attestation, process_outbox
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_base_url", "http://fake-l2e")

    enqueue_attestation(
        db_session, event_id="evt_exhaust_001", tenant_scope="t1",
        student_ref="ref_eee", attestation_hash="hash_444",
        payload={"test": True}, max_retries=3,
    )
    db_session.commit()

    for _ in range(3):
        with patch("app.l2e_bridge.requests.post", side_effect=ConnectionError("down")):
            process_outbox(db_session)
        entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt_exhaust_001").one()
        entry.next_retry_at = None
        db_session.commit()

    with patch("app.l2e_bridge.requests.post", side_effect=ConnectionError("down")):
        result = process_outbox(db_session)
    assert result["failed"] == 1

    entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt_exhaust_001").one()
    assert entry.status == "failed"
    assert entry.failure_reason == "max retries exceeded"


def test_process_restart_preserves_outbox(db_session: Session, monkeypatch):
    """After enqueue + simulated restart (new session), outbox entries survive."""
    from app.l2e_bridge import enqueue_attestation, process_outbox
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_base_url", "http://fake-l2e")

    enqueue_attestation(
        db_session, event_id="evt_restart_001", tenant_scope="t1",
        student_ref="ref_restart", attestation_hash="hash_restart",
        payload={"restart_test": True},
    )
    db_session.commit()

    db_session.expire_all()

    entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt_restart_001").one()
    assert entry.status == "pending"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ack"
    with patch("app.l2e_bridge.requests.post", return_value=mock_resp):
        result = process_outbox(db_session)
    assert result["delivered"] == 1


def test_duplicate_close(db_session: Session, monkeypatch):
    """Double-delivering the same event_id must be idempotent."""
    from app.l2e_bridge import enqueue_attestation
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)

    ok1 = enqueue_attestation(
        db_session, event_id="evt_dclose_001", tenant_scope="t1",
        student_ref="ref_dc", attestation_hash="hash_dc",
        payload={"dc": True},
    )
    db_session.commit()
    assert ok1 is True

    ok2 = enqueue_attestation(
        db_session, event_id="evt_dclose_001", tenant_scope="t1",
        student_ref="ref_dc", attestation_hash="hash_dc",
        payload={"dc": True},
    )
    assert ok2 is False

    count = db_session.query(L2EOutboxEntry).filter_by(event_id="evt_dclose_001").count()
    assert count == 1


def test_receiver_timeout(db_session: Session, monkeypatch):
    """A request timeout counts as a retriable failure, not terminal."""
    import requests as _req
    from app.l2e_bridge import enqueue_attestation, process_outbox
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_base_url", "http://fake-l2e")

    enqueue_attestation(
        db_session, event_id="evt_timeout_001", tenant_scope="t1",
        student_ref="ref_to", attestation_hash="hash_to",
        payload={"to": True}, max_retries=3,
    )
    db_session.commit()

    with patch("app.l2e_bridge.requests.post",
               side_effect=_req.exceptions.Timeout("timed out")):
        result = process_outbox(db_session)

    entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt_timeout_001").one()
    assert entry.status == "pending"
    assert entry.retry_count == 1
    assert "timed out" in entry.failure_reason


def test_duplicate_acknowledgement(db_session: Session, monkeypatch):
    """Processing an already-delivered entry must not re-deliver."""
    from app.l2e_bridge import enqueue_attestation, process_outbox
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_enabled", True)
    monkeypatch.setattr("app.l2e_bridge.settings.l2e_base_url", "http://fake-l2e")

    enqueue_attestation(
        db_session, event_id="evt_dupack_001", tenant_scope="t1",
        student_ref="ref_da", attestation_hash="hash_da",
        payload={"da": True},
    )
    db_session.commit()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    with patch("app.l2e_bridge.requests.post", return_value=mock_resp) as mock_post:
        process_outbox(db_session)
        assert mock_post.call_count == 1

    with patch("app.l2e_bridge.requests.post", return_value=mock_resp) as mock_post2:
        result = process_outbox(db_session)
        assert mock_post2.call_count == 0
    assert result["delivered"] == 0


def test_no_direct_post_on_report(monkeypatch):
    """report_lesson_attendance must not call requests.post directly."""
    import inspect
    from app import l2e_bridge
    src = inspect.getsource(l2e_bridge.report_lesson_attendance)
    assert "requests.post" not in src
    src2 = inspect.getsource(l2e_bridge.report_course_completion)
    assert "requests.post" not in src2
