"""University tenant, course lifecycle, and auth enforcement tests.

Covers:
  - RBAC enforcement on all university POST routes
  - Wallet-less student can browse courses (Goal 1)
  - Teacher-only authoring requires server-side auth (Goal 2)
  - Role separation: super_admin, teacher, student (Goal 3)
  - Assignment submission lifecycle
  - Grading lifecycle (compute → lock)
  - Certificate lifecycle (issue from passed+locked only, no duplicates)
  - Attendance evidence / attestation hash integrity
"""
import time

from app.config import settings
from app.models import (
    Assignment, Certificate, Course, Enrollment, Grade, Node,
    Student, Submission, University,
)
from app.roles import SUPER_ADMIN, TEACHER, STUDENT
from app.security import sign_payload


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_COOKIE = settings.session_cookie_name or "thronos_admin"


def _make_token(role: str, tenant_id: str = "") -> str:
    payload = {
        "typ": "admin_session",
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    return sign_payload(payload)


def _set_role(client, role: str, tenant_id: str = ""):
    client.cookies.set(_COOKIE, _make_token(role, tenant_id))


def _clear_auth(client):
    client.cookies.clear()


# ---------------------------------------------------------------------------
# Scaffold helpers
# ---------------------------------------------------------------------------

def _create_university(db_session, name="Test Uni", slug="test-uni"):
    uni = University(name=name, slug=slug, domain="test.edu",
                     l2e_tenant_id=slug)
    db_session.add(uni)
    db_session.commit()
    db_session.refresh(uni)
    return uni


def _create_course_in_db(db_session, uni, code="CS101", title="Intro"):
    node = Node(university_id=uni.id, name=uni.name, municipality="")
    db_session.add(node)
    db_session.flush()
    from app.models import Classroom
    classroom = Classroom(node_id=node.id, name=f"{code} {title}",
                          capacity=100, teacher_name="Prof",
                          l2e_tenant_id=uni.l2e_tenant_id or uni.slug)
    db_session.add(classroom)
    db_session.flush()
    course = Course(university_id=uni.id, classroom_id=classroom.id,
                    code=code, title=title, pass_grade=5.0,
                    teacher_name="Prof", max_students=100)
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)
    return course, classroom, node


def _enroll_student(db_session, classroom, name="Alice", wallet=""):
    node = db_session.query(Node).filter(Node.id == classroom.node_id).first()
    student = Student(node_id=node.id, full_name=name, external_ref=f"S-{name}",
                      status="selected", thr_wallet=wallet)
    db_session.add(student)
    db_session.flush()
    enrollment = Enrollment(classroom_id=classroom.id, student_id=student.id,
                            status="active")
    db_session.add(enrollment)
    db_session.commit()
    db_session.refresh(student)
    return student


def _create_assignment_in_db(db_session, course, title="HW1",
                             max_score=100, weight=1.0):
    from app.models import now_utc
    assignment = Assignment(
        course_id=course.id, title=title, assignment_type="homework",
        max_score=max_score, weight=weight, status="published",
        published_at=now_utc(), created_by="test",
    )
    db_session.add(assignment)
    db_session.commit()
    db_session.refresh(assignment)
    return assignment


# ===========================================================================
# 1. AUTH ENFORCEMENT — unauthenticated requests blocked
# ===========================================================================

class TestAuthEnforcement:
    """All university POST routes must reject unauthenticated requests."""

    def test_create_university_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni", data={"name": "X", "slug": "x"},
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_create_course_no_auth(self, client, db_session):
        uni = _create_university(db_session)
        _clear_auth(client)
        resp = client.post(f"/uni/{uni.id}/courses",
                           data={"title": "X"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_create_assignment_no_auth(self, client, db_session):
        uni = _create_university(db_session)
        course, _, _ = _create_course_in_db(db_session, uni)
        _clear_auth(client)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments",
            data={"title": "X"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_submit_assignment_no_auth(self, client, db_session):
        uni = _create_university(db_session)
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl)
        _clear_auth(client)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"student_id": student.id, "content": "answer"},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_grade_submission_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post(
            "/uni/1/courses/1/assignments/1/grade",
            data={"submission_id": 1, "score": 90},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_compute_grades_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/grades/compute",
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_lock_grades_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/grades/lock",
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_issue_certificates_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/certificates/issue",
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_create_live_session_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/live",
                           data={"title": "X"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_enroll_student_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/enroll",
                           data={"student_id": 1}, follow_redirects=False)
        assert resp.status_code == 403


# ===========================================================================
# 2. ROLE SEPARATION — student cannot author, teacher cannot create uni
# ===========================================================================

class TestRoleSeparation:
    """Verify role hierarchy is enforced on university routes."""

    def test_student_cannot_create_university(self, client, db_session):
        _set_role(client, STUDENT)
        resp = client.post("/uni", data={"name": "X", "slug": "x"},
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_cannot_create_university(self, client, db_session):
        _set_role(client, TEACHER)
        resp = client.post("/uni", data={"name": "X", "slug": "x"},
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_super_admin_can_create_university(self, client, db_session):
        _set_role(client, SUPER_ADMIN)
        resp = client.post("/uni", data={"name": "Auth Uni", "slug": "auth-uni"},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert db_session.query(University).filter(
            University.slug == "auth-uni").first() is not None

    def test_student_cannot_create_course(self, client, db_session):
        uni = _create_university(db_session)
        _set_role(client, STUDENT)
        resp = client.post(f"/uni/{uni.id}/courses",
                           data={"title": "X"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_can_create_course(self, client, db_session):
        uni = _create_university(db_session)
        _set_role(client, TEACHER)
        resp = client.post(f"/uni/{uni.id}/courses",
                           data={"title": "Teacher Course", "code": "TC1"},
                           follow_redirects=False)
        assert resp.status_code == 303

    def test_student_cannot_create_assignment(self, client, db_session):
        uni = _create_university(db_session)
        course, _, _ = _create_course_in_db(db_session, uni)
        _set_role(client, STUDENT)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments",
            data={"title": "X"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_student_cannot_grade(self, client, db_session):
        uni = _create_university(db_session)
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl)
        sub = Submission(assignment_id=assignment.id, student_id=student.id,
                         content="answer", content_hash="abc")
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        _set_role(client, STUDENT)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/grade",
            data={"submission_id": sub.id, "score": 90},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_student_can_submit_assignment(self, client, db_session):
        uni = _create_university(db_session)
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl)
        _set_role(client, STUDENT)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"student_id": student.id, "content": "my answer"},
            follow_redirects=False)
        assert resp.status_code == 303
        sub = db_session.query(Submission).filter(
            Submission.student_id == student.id).first()
        assert sub is not None
        assert sub.content == "my answer"

    def test_student_cannot_issue_certificates(self, client, db_session):
        _set_role(client, STUDENT)
        resp = client.post("/uni/1/courses/1/certificates/issue",
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_student_cannot_lock_grades(self, client, db_session):
        _set_role(client, STUDENT)
        resp = client.post("/uni/1/courses/1/grades/lock",
                           follow_redirects=False)
        assert resp.status_code == 403


# ===========================================================================
# 3. WALLET-LESS LEARNER — student without wallet can still participate
# ===========================================================================

class TestWalletlessLearner:
    """Students without thr_wallet can still submit assignments (Goal 1)."""

    def test_walletless_student_can_submit(self, client, db_session):
        uni = _create_university(db_session)
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl, name="NoWallet", wallet="")
        assert student.thr_wallet == ""
        _set_role(client, STUDENT)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"student_id": student.id, "content": "no wallet answer"},
            follow_redirects=False)
        assert resp.status_code == 303
        sub = db_session.query(Submission).filter(
            Submission.student_id == student.id).first()
        assert sub is not None

    def test_walletless_student_can_receive_grade(self, client, db_session):
        uni = _create_university(db_session)
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl, name="NoWallet2", wallet="")
        sub = Submission(assignment_id=assignment.id, student_id=student.id,
                         content="answer", content_hash="h1")
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        _set_role(client, TEACHER)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/grade",
            data={"submission_id": sub.id, "score": 85, "feedback": "good"},
            follow_redirects=False)
        assert resp.status_code == 303
        db_session.refresh(sub)
        assert sub.score == 85
        assert sub.status == "graded"


# ===========================================================================
# 4. ASSIGNMENT SUBMISSION LIFECYCLE
# ===========================================================================

class TestAssignmentLifecycle:
    """Full assignment create → submit → grade flow."""

    def test_create_assignment_teacher(self, client, db_session):
        uni = _create_university(db_session)
        course, _, _ = _create_course_in_db(db_session, uni)
        _set_role(client, TEACHER)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments",
            data={"title": "Midterm", "assignment_type": "exam",
                  "max_score": 50, "weight": 2.0},
            follow_redirects=False)
        assert resp.status_code == 303
        a = db_session.query(Assignment).filter(
            Assignment.course_id == course.id).first()
        assert a is not None
        assert a.title == "Midterm"
        assert a.assignment_type == "exam"
        assert a.max_score == 50
        assert a.weight == 2.0

    def test_submit_updates_existing(self, client, db_session):
        uni = _create_university(db_session)
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl)
        _set_role(client, STUDENT)
        client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"student_id": student.id, "content": "first"},
            follow_redirects=False)
        client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"student_id": student.id, "content": "revised"},
            follow_redirects=False)
        subs = db_session.query(Submission).filter(
            Submission.student_id == student.id,
            Submission.assignment_id == assignment.id).all()
        assert len(subs) == 1
        assert subs[0].content == "revised"

    def test_grade_clamps_to_max_score(self, client, db_session):
        uni = _create_university(db_session)
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course, max_score=50)
        student = _enroll_student(db_session, cl)
        sub = Submission(assignment_id=assignment.id, student_id=student.id,
                         content="x", content_hash="h")
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        _set_role(client, TEACHER)
        client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/grade",
            data={"submission_id": sub.id, "score": 999},
            follow_redirects=False)
        db_session.refresh(sub)
        assert sub.score == 50


# ===========================================================================
# 5. GRADING LIFECYCLE — compute → lock
# ===========================================================================

class TestGradingLifecycle:
    """Full grading compute and lock flow."""

    def _setup_graded_course(self, db_session):
        uni = _create_university(db_session, slug="grade-uni")
        course, cl, _ = _create_course_in_db(db_session, uni)
        s1 = _enroll_student(db_session, cl, name="Student A")
        s2 = _enroll_student(db_session, cl, name="Student B")
        a1 = _create_assignment_in_db(db_session, course, "HW1", 100, 1.0)
        a2 = _create_assignment_in_db(db_session, course, "HW2", 100, 1.0)
        for s, score1, score2 in [(s1, 90, 80), (s2, 40, 30)]:
            for a, sc in [(a1, score1), (a2, score2)]:
                sub = Submission(assignment_id=a.id, student_id=s.id,
                                 content="ans", content_hash="h",
                                 score=sc, status="graded")
                db_session.add(sub)
        db_session.commit()
        return uni, course, s1, s2

    def test_compute_grades(self, client, db_session):
        uni, course, s1, s2 = self._setup_graded_course(db_session)
        _set_role(client, TEACHER)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/grades/compute",
            follow_redirects=False)
        assert resp.status_code == 303
        g1 = db_session.query(Grade).filter(
            Grade.course_id == course.id, Grade.student_id == s1.id).first()
        g2 = db_session.query(Grade).filter(
            Grade.course_id == course.id, Grade.student_id == s2.id).first()
        assert g1 is not None
        assert g1.passed is True
        assert g2 is not None
        assert g2.passed is False

    def test_lock_grades_on_chain(self, client, db_session):
        uni, course, s1, s2 = self._setup_graded_course(db_session)
        _set_role(client, TEACHER)
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/compute",
                    follow_redirects=False)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/grades/lock",
            follow_redirects=False)
        assert resp.status_code == 303
        g1 = db_session.query(Grade).filter(
            Grade.course_id == course.id, Grade.student_id == s1.id).first()
        assert g1.locked is True
        assert g1.attestation_hash is not None
        assert len(g1.attestation_hash) > 0

    def test_locked_grade_not_overwritten(self, client, db_session):
        uni, course, s1, _ = self._setup_graded_course(db_session)
        _set_role(client, TEACHER)
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/compute",
                    follow_redirects=False)
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/lock",
                    follow_redirects=False)
        g1 = db_session.query(Grade).filter(
            Grade.course_id == course.id, Grade.student_id == s1.id).first()
        original_score = g1.final_score
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/compute",
                    follow_redirects=False)
        db_session.refresh(g1)
        assert g1.final_score == original_score
        assert g1.locked is True


# ===========================================================================
# 6. CERTIFICATE LIFECYCLE
# ===========================================================================

class TestCertificateLifecycle:
    """Certificate issuance from passed+locked grades only, no duplicates."""

    def _setup_passed_locked(self, db_session):
        uni = _create_university(db_session, slug="cert-uni")
        course, cl, _ = _create_course_in_db(db_session, uni)
        s_pass = _enroll_student(db_session, cl, name="Passer")
        s_fail = _enroll_student(db_session, cl, name="Failer")
        g_pass = Grade(course_id=course.id, student_id=s_pass.id,
                       final_score=8.0, letter_grade="B", passed=True,
                       locked=True, graded_by="test",
                       attestation_hash="hash_pass")
        g_fail = Grade(course_id=course.id, student_id=s_fail.id,
                       final_score=3.0, letter_grade="F", passed=False,
                       locked=True, graded_by="test",
                       attestation_hash="hash_fail")
        db_session.add_all([g_pass, g_fail])
        db_session.commit()
        return uni, course, s_pass, s_fail

    def test_issue_certificates_only_for_passed(self, client, db_session):
        uni, course, s_pass, s_fail = self._setup_passed_locked(db_session)
        _set_role(client, TEACHER)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
            follow_redirects=False)
        assert resp.status_code == 303
        certs = db_session.query(Certificate).filter(
            Certificate.course_id == course.id).all()
        assert len(certs) == 1
        assert certs[0].student_id == s_pass.id
        assert certs[0].attestation_hash is not None

    def test_no_duplicate_certificates(self, client, db_session):
        uni, course, s_pass, _ = self._setup_passed_locked(db_session)
        _set_role(client, TEACHER)
        client.post(f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
                    follow_redirects=False)
        client.post(f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
                    follow_redirects=False)
        certs = db_session.query(Certificate).filter(
            Certificate.course_id == course.id,
            Certificate.student_id == s_pass.id).all()
        assert len(certs) == 1

    def test_certificate_not_issued_for_unlocked_grade(self, client, db_session):
        uni = _create_university(db_session, slug="cert-unlock")
        course, cl, _ = _create_course_in_db(db_session, uni)
        student = _enroll_student(db_session, cl, name="Unlocked")
        g = Grade(course_id=course.id, student_id=student.id,
                  final_score=9.0, letter_grade="A", passed=True,
                  locked=False, graded_by="test")
        db_session.add(g)
        db_session.commit()
        _set_role(client, TEACHER)
        client.post(f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
                    follow_redirects=False)
        certs = db_session.query(Certificate).filter(
            Certificate.course_id == course.id).all()
        assert len(certs) == 0


# ===========================================================================
# 7. ATTESTATION HASH INTEGRITY
# ===========================================================================

class TestAttestationIntegrity:
    """Attestation hashes are recorded on grade lock and certificate issue."""

    def test_grade_lock_records_attestation(self, client, db_session):
        uni = _create_university(db_session, slug="attest-uni")
        course, cl, _ = _create_course_in_db(db_session, uni)
        student = _enroll_student(db_session, cl, name="Attester")
        g = Grade(course_id=course.id, student_id=student.id,
                  final_score=7.5, letter_grade="C", passed=True,
                  locked=False, graded_by="test")
        db_session.add(g)
        db_session.commit()
        _set_role(client, TEACHER)
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/lock",
                    follow_redirects=False)
        db_session.refresh(g)
        assert g.locked is True
        assert g.attestation_hash is not None
        assert len(g.attestation_hash) >= 16

    def test_certificate_records_attestation(self, client, db_session):
        uni = _create_university(db_session, slug="cert-attest")
        course, cl, _ = _create_course_in_db(db_session, uni)
        student = _enroll_student(db_session, cl, name="CertAttest")
        g = Grade(course_id=course.id, student_id=student.id,
                  final_score=9.0, letter_grade="A", passed=True,
                  locked=True, graded_by="test", attestation_hash="g_hash")
        db_session.add(g)
        db_session.commit()
        _set_role(client, TEACHER)
        client.post(f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
                    follow_redirects=False)
        cert = db_session.query(Certificate).filter(
            Certificate.course_id == course.id).first()
        assert cert is not None
        assert cert.attestation_hash is not None
        assert len(cert.attestation_hash) >= 16

    def test_submission_grade_records_attestation_when_lock_on_chain(
            self, client, db_session):
        uni = _create_university(db_session, slug="sub-attest")
        course, cl, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        assignment.lock_on_chain = True
        db_session.commit()
        student = _enroll_student(db_session, cl, name="SubAttest")
        sub = Submission(assignment_id=assignment.id, student_id=student.id,
                         content="answer", content_hash="ch1")
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        _set_role(client, TEACHER)
        client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/grade",
            data={"submission_id": sub.id, "score": 95},
            follow_redirects=False)
        db_session.refresh(sub)
        assert sub.attestation_hash is not None


# ===========================================================================
# 8. DUPLICATE SLUG REJECTION
# ===========================================================================

def test_duplicate_slug_rejected(client, db_session):
    _set_role(client, SUPER_ADMIN)
    client.post("/uni", data={"name": "First Uni", "slug": "dup-slug"},
                follow_redirects=False)
    resp = client.post("/uni", data={"name": "Second Uni", "slug": "dup-slug"},
                       follow_redirects=False)
    assert resp.status_code == 409


# ===========================================================================
# 9. LIVE SESSION MANAGEMENT
# ===========================================================================

class TestLiveSessions:

    def test_teacher_can_create_live_session(self, client, db_session):
        uni = _create_university(db_session, slug="live-uni")
        course, _, _ = _create_course_in_db(db_session, uni)
        _set_role(client, TEACHER)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/live",
            data={"title": "Lecture 1", "duration_minutes": 60},
            follow_redirects=False)
        assert resp.status_code == 303
        from app.models import LiveSession
        ls = db_session.query(LiveSession).filter(
            LiveSession.course_id == course.id).first()
        assert ls is not None
        assert ls.title == "Lecture 1"

    def test_student_cannot_create_live_session(self, client, db_session):
        uni = _create_university(db_session, slug="live-block")
        course, _, _ = _create_course_in_db(db_session, uni)
        _set_role(client, STUDENT)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/live",
            data={"title": "X"}, follow_redirects=False)
        assert resp.status_code == 403
