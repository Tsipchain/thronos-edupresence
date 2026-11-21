"""LMS route tests: enrollment, modules, quizzes, certificates, profile."""
import time

from app.config import settings
from app.models import (
    Assignment, Certificate, Course, CourseEnrollment, CourseModule,
    ModuleProgress, Node, QuizAttempt, QuizQuestion, Student, University,
)
from app.security import sign_payload


def _verified_student(client, tax_id):
    payload = {
        "typ": "session", "tax_id": tax_id, "provider": "edu_verified_student",
        "role": "student", "full_name": "Test Student",
        "exp": int(time.time()) + 3600,
    }
    client.cookies.set(settings.session_cookie_name, sign_payload(payload))


def _seed_course(db):
    uni = University(name="Test Uni", slug="test-uni")
    db.add(uni)
    db.flush()
    course = Course(
        university_id=uni.id, title="Intro to Blockchain", code="BC101",
        description="Learn blockchain basics", status="published",
        is_active=True, teacher_name="Dr. Test", credits=5,
    )
    db.add(course)
    db.flush()
    return course


def _seed_student(db, tax_id="300000001"):
    node = Node(name="Test Node", municipality="Tests")
    db.add(node)
    db.flush()
    student = Student(
        node_id=node.id, full_name="Test Student", tax_id=tax_id,
        thr_wallet="", status="selected", is_active=True,
    )
    db.add(student)
    db.flush()
    return student


def test_course_detail_public(client, db_session):
    course = _seed_course(db_session)
    db_session.commit()
    r = client.get(f"/learn/courses/{course.id}")
    assert r.status_code == 200
    assert "Intro to Blockchain" in r.text


def test_unpublished_course_404(client, db_session):
    uni = University(name="Uni", slug="uni")
    db_session.add(uni)
    db_session.flush()
    course = Course(university_id=uni.id, title="Hidden", status="active", is_active=True)
    db_session.add(course)
    db_session.commit()
    assert client.get(f"/learn/courses/{course.id}").status_code == 404


def test_enrollment_requires_verified_student(client, db_session):
    course = _seed_course(db_session)
    db_session.commit()
    r = client.post(f"/learn/courses/{course.id}/enroll", follow_redirects=False)
    assert r.status_code == 403


def test_verified_student_can_enroll(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    db_session.commit()
    _verified_student(client, student.tax_id)
    r = client.post(f"/learn/courses/{course.id}/enroll", follow_redirects=False)
    assert r.status_code == 303
    enrollment = db_session.query(CourseEnrollment).filter_by(
        course_id=course.id, student_id=student.id
    ).first()
    assert enrollment is not None


def test_enrollment_idempotent(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    db_session.commit()
    _verified_student(client, student.tax_id)
    client.post(f"/learn/courses/{course.id}/enroll", follow_redirects=False)
    client.post(f"/learn/courses/{course.id}/enroll", follow_redirects=False)
    count = db_session.query(CourseEnrollment).filter_by(
        course_id=course.id, student_id=student.id
    ).count()
    assert count == 1


def test_module_requires_enrollment(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    module = CourseModule(
        course_id=course.id, title="Module 1", content="Content", is_published=True,
    )
    db_session.add(module)
    db_session.commit()
    _verified_student(client, student.tax_id)
    r = client.get(f"/learn/courses/{course.id}/modules/{module.id}")
    assert r.status_code == 403


def test_enrolled_student_views_module(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    module = CourseModule(
        course_id=course.id, title="Module 1", content="<p>Learn this</p>",
        is_published=True,
    )
    db_session.add(module)
    db_session.flush()
    db_session.add(CourseEnrollment(course_id=course.id, student_id=student.id))
    db_session.commit()
    _verified_student(client, student.tax_id)
    r = client.get(f"/learn/courses/{course.id}/modules/{module.id}")
    assert r.status_code == 200
    assert "Module 1" in r.text


def test_module_completion_idempotent(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    module = CourseModule(
        course_id=course.id, title="M1", content="x", is_published=True,
    )
    db_session.add(module)
    db_session.flush()
    db_session.add(CourseEnrollment(course_id=course.id, student_id=student.id))
    db_session.commit()
    _verified_student(client, student.tax_id)
    client.post(
        f"/learn/courses/{course.id}/modules/{module.id}/complete",
        follow_redirects=False,
    )
    client.post(
        f"/learn/courses/{course.id}/modules/{module.id}/complete",
        follow_redirects=False,
    )
    count = db_session.query(ModuleProgress).filter_by(
        module_id=module.id, student_id=student.id
    ).count()
    assert count == 1


def test_quiz_server_side_grading(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    quiz = Assignment(
        course_id=course.id, title="Quiz 1",
        assignment_type="quiz", status="published", max_score=2,
    )
    db_session.add(quiz)
    db_session.flush()
    db_session.add(QuizQuestion(
        assignment_id=quiz.id, question_text="What is 1+1?",
        options_json='["1","2","3"]', correct_index=1,
        points=1.0, order_index=0,
    ))
    db_session.add(QuizQuestion(
        assignment_id=quiz.id, question_text="Is BTC digital?",
        options_json='["Yes","No"]', correct_index=0,
        points=1.0, order_index=1,
    ))
    db_session.add(CourseEnrollment(course_id=course.id, student_id=student.id))
    db_session.commit()
    _verified_student(client, student.tax_id)
    r = client.post(
        f"/learn/courses/{course.id}/quiz/{quiz.id}/submit",
        data={"q_0": "1", "q_1": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    attempt = db_session.query(QuizAttempt).filter_by(
        assignment_id=quiz.id, student_id=student.id
    ).first()
    assert attempt is not None
    assert attempt.score == 2.0
    assert attempt.passed is True


def test_quiz_max_attempts(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    quiz = Assignment(
        course_id=course.id, title="Quiz",
        assignment_type="quiz", status="published", max_score=1,
    )
    db_session.add(quiz)
    db_session.flush()
    db_session.add(QuizQuestion(
        assignment_id=quiz.id, question_text="Q?",
        options_json='["A","B"]', correct_index=0, points=1.0,
    ))
    db_session.add(CourseEnrollment(course_id=course.id, student_id=student.id))
    db_session.commit()
    _verified_student(client, student.tax_id)
    for _ in range(3):
        client.post(
            f"/learn/courses/{course.id}/quiz/{quiz.id}/submit",
            data={"q_0": "1"},
            follow_redirects=False,
        )
    r = client.post(
        f"/learn/courses/{course.id}/quiz/{quiz.id}/submit",
        data={"q_0": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_certificates_requires_auth(client):
    r = client.get("/learn/certificates", follow_redirects=False)
    assert r.status_code == 303


def test_profile_requires_auth(client):
    r = client.get("/learn/profile", follow_redirects=False)
    assert r.status_code == 303


def test_my_courses_requires_auth(client):
    r = client.get("/learn/my-courses", follow_redirects=False)
    assert r.status_code == 303


def test_cross_student_enrollment_isolation(client, db_session):
    course = _seed_course(db_session)
    s1 = _seed_student(db_session, "400000001")
    _seed_student(db_session, "400000002")
    db_session.add(CourseEnrollment(course_id=course.id, student_id=s1.id))
    db_session.commit()
    _verified_student(client, "400000002")
    r = client.get(f"/learn/courses/{course.id}")
    assert "enroll" in r.text.lower() or "Εγγραφή" in r.text


def test_no_wallet_required(client, db_session):
    course = _seed_course(db_session)
    student = _seed_student(db_session)
    student.thr_wallet = ""
    db_session.commit()
    _verified_student(client, student.tax_id)
    r = client.post(
        f"/learn/courses/{course.id}/enroll", follow_redirects=False,
    )
    assert r.status_code == 303


def test_teacher_dashboard_requires_teacher(client):
    r = client.get("/teach")
    assert r.status_code == 403
