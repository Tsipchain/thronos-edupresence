"""Tenant/role isolation and admin session security tests for ThronosEdu."""
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.roles import (
    SUPER_ADMIN, TENANT_DIRECTOR, TEACHER, STUDENT,
    ALL_ROLES, has_at_least,
)
from app.security import sign_payload
from app.config import settings
from app.admin_ui import _COOKIE
import app.admin_ui as admin_ui_module


@pytest.fixture
def _patch_admin_db(_fresh_db):
    """Patch admin_ui's direct get_db calls to use the test DB."""
    session_factory = _fresh_db
    def _fake_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            pass  # don't close — the fixture manages teardown
    original = admin_ui_module.get_db
    admin_ui_module.get_db = _fake_get_db
    yield session_factory()
    admin_ui_module.get_db = original


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

def _set_admin_cookie(client: TestClient) -> None:
    token = sign_payload({
        "typ": "admin_session",
        "role": SUPER_ADMIN,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    })
    client.cookies.set(_COOKIE, token)


def test_admin_home_requires_session(client: TestClient):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 200
    assert "admin_login" in resp.text or "κλειδί" in resp.text.lower()


def test_admin_login_sets_httponly_cookie(client: TestClient):
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


def test_admin_key_not_in_redirect_urls(client: TestClient):
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
