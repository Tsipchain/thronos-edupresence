"""HTML smoke tests — verify key routes return 200 with valid HTML."""
from datetime import datetime

from app.models import Classroom, Enrollment, Lesson, Node, Student


def _seed(db_session):
    """Create a node → classroom → student → enrollment → lesson chain."""
    node = Node(name="Smoke Node", municipality="TEST")
    db_session.add(node)
    db_session.flush()

    classroom = Classroom(
        node_id=node.id, name="Smoke Class", capacity=15,
        teacher_name="Teacher", location="Smoke Node",
    )
    db_session.add(classroom)
    db_session.flush()

    student = Student(
        node_id=node.id, full_name="Smoke Student",
        phone="+301234567", status="selected",
    )
    db_session.add(student)
    db_session.flush()

    db_session.add(Enrollment(
        classroom_id=classroom.id, student_id=student.id, status="active",
    ))
    db_session.flush()

    lesson = Lesson(
        classroom_id=classroom.id, title="Smoke Lesson",
        starts_at=datetime(2026, 1, 15, 10, 0),
        duration_minutes=120, teaching_hours=2,
        created_by="Teacher",
    )
    db_session.add(lesson)
    db_session.commit()
    db_session.refresh(node)
    db_session.refresh(classroom)
    db_session.refresh(lesson)
    return node, classroom, lesson


def _assert_html(resp):
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "<html" in resp.text.lower(), "Response does not contain <html"


def test_dashboard_html(client):
    resp = client.get("/")
    _assert_html(resp)


def test_login_html(client):
    resp = client.get("/login")
    _assert_html(resp)


def test_admin_login_page_html(client):
    resp = client.get("/admin")
    _assert_html(resp)


def test_university_list_html(client):
    resp = client.get("/uni")
    _assert_html(resp)


def test_node_detail_html(client, db_session):
    node, _, _ = _seed(db_session)
    resp = client.get(f"/nodes/{node.id}")
    _assert_html(resp)


def test_class_detail_html(client, db_session):
    _, classroom, _ = _seed(db_session)
    resp = client.get(f"/classes/{classroom.id}")
    _assert_html(resp)


def test_lesson_detail_html(client, db_session):
    _, _, lesson = _seed(db_session)
    resp = client.get(f"/lessons/{lesson.id}")
    _assert_html(resp)


def test_lesson_print_html(client, db_session):
    _, _, lesson = _seed(db_session)
    resp = client.get(f"/lessons/{lesson.id}/print")
    _assert_html(resp)


def test_attendance_dashboard_html(client, db_session):
    _, classroom, _ = _seed(db_session)
    resp = client.get(f"/classes/{classroom.id}/attendance-dashboard")
    _assert_html(resp)


def test_class_history_html(client, db_session):
    _, classroom, _ = _seed(db_session)
    resp = client.get(f"/classes/{classroom.id}/history")
    _assert_html(resp)
