"""EDU-owned student portal: walletless access with verified signed identity only."""
import time

from app.config import settings
from app.models import Classroom, Enrollment, Node, Student
from app.security import sign_payload


def _session(client, tax_id, provider="edu_verified_student", role="student"):
    payload = {
        "typ": "session",
        "tax_id": tax_id,
        "provider": provider,
        "role": role,
        "full_name": "Verified Student",
        "exp": int(time.time()) + 3600,
    }
    client.cookies.set(settings.session_cookie_name, sign_payload(payload))


def _seed(db, name, tax_id, classroom_name):
    node = Node(name="EDU Node", municipality="Tests")
    db.add(node)
    db.flush()
    classroom = Classroom(
        node_id=node.id, name=classroom_name, program_name="Cybersecurity",
        teacher_name="Synthetic Teacher",
    )
    db.add(classroom)
    db.flush()
    student = Student(
        node_id=node.id, full_name=name, tax_id=tax_id,
        thr_wallet="", status="selected", is_active=True,
    )
    db.add(student)
    db.flush()
    db.add(Enrollment(classroom_id=classroom.id, student_id=student.id, status="active"))
    db.commit()
    return student


def test_student_dashboard_requires_a_signed_session(client):
    resp = client.get("/student-dashboard", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    client.cookies.set(settings.session_cookie_name, "totally.invalid")
    assert client.get("/student-dashboard", follow_redirects=False).status_code == 303


def test_mock_or_teacher_identity_cannot_access_private_academic_records(client, db_session):
    _seed(db_session, "Private Student", "200000001", "Private Class")
    _session(client, "200000001", provider="mock_taxisnet")
    assert client.get("/student-dashboard").status_code == 403
    _session(client, "200000001", provider="gov_pending_exchange")
    assert client.get("/student-dashboard").status_code == 403
    _session(client, "200000001", role="teacher")
    assert client.get("/student-dashboard").status_code == 403


def test_verified_walletless_student_sees_only_own_enrollments(client, db_session):
    _seed(db_session, "Student Alpha", "200000002", "Class Alpha")
    _seed(db_session, "Student Beta", "200000003", "Class Beta")
    _session(client, "200000002")
    page = client.get("/student-dashboard").text
    assert "Student Alpha" in page
    assert "Class Alpha" in page
    assert "Student Beta" not in page
    assert "Class Beta" not in page
    assert "Δεν χρειάζεσαι THR Wallet" in page
    assert "Δεν αποδίδεται αυτόματα ανταμοιβή" in page
    assert 'id="edu-walletless-policy"' in page


def test_query_wallet_and_learner_id_cannot_override_signed_identity(client, db_session):
    _seed(db_session, "Student One", "200000004", "Own Class")
    _seed(db_session, "Student Two", "200000005", "Other Class")
    _session(client, "200000004")
    resp = client.get("/student-dashboard?student_id=200000005&tax_id=200000005&wallet=THR_BAD")
    assert resp.status_code == 200
    assert "Own Class" in resp.text
    assert "Other Class" not in resp.text


def test_verified_user_without_local_enrollments_gets_clear_empty_state(client):
    _session(client, "200000006")
    r = client.get("/student-dashboard")
    assert r.status_code == 200
    assert 'data-state="no-student-record"' in r.text


def test_duplicate_identity_is_not_silently_selected(client, db_session):
    _seed(db_session, "Duplicate One", "200000007", "Class 1")
    _seed(db_session, "Duplicate Two", "200000007", "Class 2")
    _session(client, "200000007")
    r = client.get("/student-dashboard")
    assert r.status_code == 409
    assert "Duplicate One" not in r.text
    assert "Duplicate Two" not in r.text


def test_expired_session_rejected(client, db_session):
    _seed(db_session, "Expired Student", "200000008", "Expired Class")
    payload = {
        "typ": "session",
        "tax_id": "200000008",
        "provider": "edu_verified_student",
        "role": "student",
        "full_name": "Expired Student",
        "exp": int(time.time()) - 60,
    }
    client.cookies.set(settings.session_cookie_name, sign_payload(payload))
    r = client.get("/student-dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_teacher_role_rejected_even_with_verified_provider(client, db_session):
    _seed(db_session, "Teacher Impersonator", "200000009", "Secret Class")
    _session(client, "200000009", provider="edu_verified_student", role="teacher")
    r = client.get("/student-dashboard")
    assert r.status_code == 403
    assert "Secret Class" not in r.text


def test_l2e_bridge_disabled_notice_shown(client, db_session):
    _seed(db_session, "L2E Student", "200000010", "L2E Class")
    _session(client, "200000010")
    page = client.get("/student-dashboard").text
    assert "δεν έχει ενεργοποιηθεί" in page.lower() or "δεν έχει ενεργοποιηθεί" in page


def test_no_earn_learner_id_cookie_trust(client, db_session):
    """earn_learner_id cookie must NOT grant dashboard access."""
    _seed(db_session, "Cookie Victim", "200000011", "Victim Class")
    client.cookies.set("earn_learner_id", "200000011")
    r = client.get("/student-dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
