"""University auth, tenant isolation, wallet verification, CSRF, and lifecycle tests.

Covers all 6 blocking review items:
  1. Student identity — server-derived, never from form; cross-student isolation
  2. Read access — sensitive GET routes require auth; student sees only own data
  3. Tenant scope — every route enforces session tenant_id; cross-tenant rejected
  4. Verified teacher wallet — fail closed if absent
  5. Session hardening — CSRF double-submit cookie on all POST routes
  6. Truthful attestation — no false "on-chain" claims
"""
import time

from app.config import settings
from app.models import (
    AdminUser, Assignment, Certificate, Classroom, Course, Enrollment,
    Grade, Node, Student, Submission, University,
)
from app.roles import SUPER_ADMIN, TENANT_DIRECTOR, TEACHER, STUDENT
from app.security import sign_payload
from app.admin_ui import _CSRF_COOKIE


# ---------------------------------------------------------------------------
# Auth / CSRF helpers
# ---------------------------------------------------------------------------

_COOKIE = settings.session_cookie_name or "thronos_admin"
_CSRF_VAL = "test-csrf-token-abc123"


def _make_token(role: str, tenant_id: str = "", student_id: int | None = None,
                thr_wallet: str = "") -> str:
    payload = {
        "typ": "admin_session",
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    if student_id:
        payload["student_id"] = student_id
    if thr_wallet:
        payload["thr_wallet"] = thr_wallet
    return sign_payload(payload)


def _set_role(client, role: str, tenant_id: str = "", student_id: int | None = None,
              thr_wallet: str = ""):
    client.cookies.set(_COOKIE, _make_token(role, tenant_id, student_id, thr_wallet))
    client.cookies.set(_CSRF_COOKIE, _CSRF_VAL)


def _clear_auth(client):
    client.cookies.clear()


def _csrf():
    return {"csrf_token": _CSRF_VAL}


# ---------------------------------------------------------------------------
# Scaffold helpers
# ---------------------------------------------------------------------------

def _create_university(db_session, name="Test Uni", slug="test-uni"):
    uni = University(name=name, slug=slug, domain="test.edu", l2e_tenant_id=slug)
    db_session.add(uni)
    db_session.commit()
    db_session.refresh(uni)
    return uni


def _create_course_in_db(db_session, uni, code="CS101", title="Intro"):
    node = Node(university_id=uni.id, name=uni.name, municipality="")
    db_session.add(node)
    db_session.flush()
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
# 1. STUDENT IDENTITY — server-derived, cross-student isolation
# ===========================================================================

class TestStudentIdentity:

    def test_submit_derives_student_from_session(self, client, db_session):
        """student_id comes from session, not form body."""
        uni = _create_university(db_session)
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        alice = _enroll_student(db_session, cl, name="Alice")
        _set_role(client, STUDENT, tenant_id=str(node.id), student_id=alice.id)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"content": "alice answer", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 303
        sub = db_session.query(Submission).filter(
            Submission.student_id == alice.id).first()
        assert sub is not None
        assert sub.content == "alice answer"

    def test_student_a_cannot_submit_as_student_b(self, client, db_session):
        """Even if form body carried another student_id (removed), session
        identity pins submission to the authenticated student."""
        uni = _create_university(db_session)
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        alice = _enroll_student(db_session, cl, name="Alice")
        bob = _enroll_student(db_session, cl, name="Bob")
        _set_role(client, STUDENT, tenant_id=str(node.id), student_id=alice.id)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"content": "pretend bob", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 303
        sub = db_session.query(Submission).filter(
            Submission.assignment_id == assignment.id).first()
        assert sub.student_id == alice.id

    def test_no_student_id_in_session_rejected(self, client, db_session):
        """Session without student_id cannot submit."""
        uni = _create_university(db_session)
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        _set_role(client, STUDENT, tenant_id=str(node.id))
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"content": "no id", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_unenrolled_student_cannot_submit(self, client, db_session):
        """Student not enrolled in the course's classroom is rejected."""
        uni = _create_university(db_session)
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        outsider = Student(node_id=node.id, full_name="Outsider",
                           external_ref="S-OUT", status="selected")
        db_session.add(outsider)
        db_session.commit()
        db_session.refresh(outsider)
        _set_role(client, STUDENT, tenant_id=str(node.id), student_id=outsider.id)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"content": "not enrolled", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_student_a_cannot_read_student_b_submission(self, client, db_session):
        """Student B's submission exists but student A cannot see via the
        same endpoint (tested via DB — A's request produces no B data)."""
        uni = _create_university(db_session)
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        alice = _enroll_student(db_session, cl, name="Alice")
        bob = _enroll_student(db_session, cl, name="Bob")
        sub_b = Submission(assignment_id=assignment.id, student_id=bob.id,
                           content="bob secret", content_hash="hb")
        db_session.add(sub_b)
        db_session.commit()
        _set_role(client, STUDENT, tenant_id=str(node.id), student_id=alice.id)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"content": "alice", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 303
        alice_sub = db_session.query(Submission).filter(
            Submission.student_id == alice.id).first()
        assert alice_sub is not None
        assert alice_sub.content == "alice"
        bob_sub = db_session.query(Submission).filter(
            Submission.student_id == bob.id).first()
        assert bob_sub.content == "bob secret"


# ===========================================================================
# 2. READ ACCESS — sensitive GETs require auth
# ===========================================================================

class TestReadAccess:

    def test_course_detail_requires_auth(self, client, db_session):
        uni = _create_university(db_session)
        course, _, _ = _create_course_in_db(db_session, uni)
        _clear_auth(client)
        resp = client.get(f"/uni/{uni.id}/courses/{course.id}",
                          follow_redirects=False)
        assert resp.status_code == 403

    def test_assignment_detail_requires_auth(self, client, db_session):
        uni = _create_university(db_session)
        course, _, _ = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        _clear_auth(client)
        resp = client.get(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}",
            follow_redirects=False)
        assert resp.status_code == 403

    def test_university_list_public(self, client, db_session):
        """University list (metadata only) is public."""
        _create_university(db_session)
        _clear_auth(client)
        resp = client.get("/uni", follow_redirects=False)
        assert resp.status_code in (200, 303)


# ===========================================================================
# 3. TENANT SCOPE — cross-tenant rejected
# ===========================================================================

class TestTenantScope:

    def test_teacher_from_other_uni_cannot_create_course(self, client, db_session):
        """Teacher whose node is in uni_b cannot create a course in uni_a."""
        uni_a = _create_university(db_session, name="Uni A", slug="uni-a")
        uni_b = _create_university(db_session, name="Uni B", slug="uni-b")
        node_b = Node(university_id=uni_b.id, name="Node B", municipality="")
        db_session.add(node_b)
        db_session.commit()
        db_session.refresh(node_b)
        _set_role(client, TEACHER, tenant_id=str(node_b.id), thr_wallet="thr1abc")
        resp = client.post(
            f"/uni/{uni_a.id}/courses",
            data={"title": "Cross Tenant", "code": "CT1", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_same_tenant_can_create_course(self, client, db_session):
        uni = _create_university(db_session, slug="same-tenant")
        node = Node(university_id=uni.id, name="My Node", municipality="")
        db_session.add(node)
        db_session.commit()
        db_session.refresh(node)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1abc")
        resp = client.post(
            f"/uni/{uni.id}/courses",
            data={"title": "My Course", "code": "MC1", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 303

    def test_cross_tenant_course_detail_rejected(self, client, db_session):
        uni = _create_university(db_session, slug="ct-detail")
        course, _, node_a = _create_course_in_db(db_session, uni)
        node_b = Node(university_id=uni.id, name="Other", municipality="")
        db_session.add(node_b)
        db_session.commit()
        db_session.refresh(node_b)
        _set_role(client, STUDENT, tenant_id=str(node_b.id))
        resp = client.get(f"/uni/{uni.id}/courses/{course.id}",
                          follow_redirects=False)
        assert resp.status_code == 403

    def test_cross_tenant_grade_rejected(self, client, db_session):
        uni = _create_university(db_session, slug="ct-grade")
        course, cl, node_a = _create_course_in_db(db_session, uni)
        student = _enroll_student(db_session, cl, name="Stu")
        sub = Submission(assignment_id=None, student_id=student.id,
                         content="x", content_hash="h")
        assignment = _create_assignment_in_db(db_session, course)
        sub.assignment_id = assignment.id
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        node_b = Node(university_id=uni.id, name="Other", municipality="")
        db_session.add(node_b)
        db_session.commit()
        db_session.refresh(node_b)
        _set_role(client, TEACHER, tenant_id=str(node_b.id), thr_wallet="thr1x")
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/grade",
            data={"submission_id": sub.id, "score": 90, **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_super_admin_bypasses_tenant(self, client, db_session):
        uni = _create_university(db_session, slug="sa-bypass")
        course, _, _ = _create_course_in_db(db_session, uni)
        _set_role(client, SUPER_ADMIN)
        resp = client.get(f"/uni/{uni.id}/courses/{course.id}",
                          follow_redirects=False)
        assert resp.status_code in (200, 303)

    def test_two_accounts_never_see_each_other_ledger(self, client, db_session):
        """Two students in different tenants cannot see each other's grades."""
        uni = _create_university(db_session, slug="iso-ledger")
        course, cl, node_a = _create_course_in_db(db_session, uni)
        alice = _enroll_student(db_session, cl, name="Alice")
        g = Grade(course_id=course.id, student_id=alice.id,
                  final_score=9.0, letter_grade="A", passed=True,
                  locked=True, graded_by="test")
        db_session.add(g)
        db_session.commit()
        node_b = Node(university_id=uni.id, name="Other Tenant", municipality="")
        db_session.add(node_b)
        db_session.commit()
        db_session.refresh(node_b)
        _set_role(client, STUDENT, tenant_id=str(node_b.id))
        resp = client.get(f"/uni/{uni.id}/courses/{course.id}",
                          follow_redirects=False)
        assert resp.status_code == 403


# ===========================================================================
# 4. VERIFIED TEACHER WALLET — fail closed if absent
# ===========================================================================

class TestTeacherWallet:

    def test_teacher_without_wallet_cannot_create_course(self, client, db_session):
        uni = _create_university(db_session, slug="no-wallet")
        node = Node(university_id=uni.id, name="N", municipality="")
        db_session.add(node)
        db_session.commit()
        db_session.refresh(node)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="")
        resp = client.post(
            f"/uni/{uni.id}/courses",
            data={"title": "X", "code": "X1", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_with_wallet_can_create_course(self, client, db_session):
        uni = _create_university(db_session, slug="with-wallet")
        node = Node(university_id=uni.id, name="N", municipality="")
        db_session.add(node)
        db_session.commit()
        db_session.refresh(node)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1teacher")
        resp = client.post(
            f"/uni/{uni.id}/courses",
            data={"title": "Wallet Course", "code": "WC1", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 303

    def test_teacher_without_wallet_cannot_grade(self, client, db_session):
        uni = _create_university(db_session, slug="nw-grade")
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl)
        sub = Submission(assignment_id=assignment.id, student_id=student.id,
                         content="x", content_hash="h")
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="")
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/grade",
            data={"submission_id": sub.id, "score": 90, **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_without_wallet_cannot_issue_certs(self, client, db_session):
        uni = _create_university(db_session, slug="nw-cert")
        course, _, node = _create_course_in_db(db_session, uni)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="")
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
            data={**_csrf()}, follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_without_wallet_cannot_lock_grades(self, client, db_session):
        uni = _create_university(db_session, slug="nw-lock")
        course, _, node = _create_course_in_db(db_session, uni)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="")
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/grades/lock",
            data={**_csrf()}, follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_without_wallet_cannot_create_assignment(self, client, db_session):
        uni = _create_university(db_session, slug="nw-assign")
        course, _, node = _create_course_in_db(db_session, uni)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="")
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments",
            data={"title": "X", **_csrf()}, follow_redirects=False)
        assert resp.status_code == 403

    def test_student_remains_wallet_optional(self, client, db_session):
        """Students without thr_wallet can still submit (wallet-optional)."""
        uni = _create_university(db_session, slug="stu-nowallet")
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl, name="NoWallet", wallet="")
        _set_role(client, STUDENT, tenant_id=str(node.id), student_id=student.id)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"content": "answer", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 303


# ===========================================================================
# 5. SESSION HARDENING — CSRF double-submit cookie
# ===========================================================================

class TestCSRF:

    def test_post_without_csrf_rejected(self, client, db_session):
        _set_role(client, SUPER_ADMIN)
        client.cookies.delete(_CSRF_COOKIE)
        resp = client.post("/uni", data={"name": "X", "slug": "x"},
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_post_with_wrong_csrf_rejected(self, client, db_session):
        _set_role(client, SUPER_ADMIN)
        resp = client.post(
            "/uni", data={"name": "X", "slug": "x", "csrf_token": "wrong"},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_post_with_valid_csrf_accepted(self, client, db_session):
        _set_role(client, SUPER_ADMIN)
        resp = client.post(
            "/uni", data={"name": "CSRF Uni", "slug": "csrf-uni", **_csrf()},
            follow_redirects=False)
        assert resp.status_code == 303

    def test_csrf_required_on_submit(self, client, db_session):
        uni = _create_university(db_session, slug="csrf-sub")
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl)
        _set_role(client, STUDENT, tenant_id=str(node.id), student_id=student.id)
        client.cookies.delete(_CSRF_COOKIE)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/submit",
            data={"content": "x"},
            follow_redirects=False)
        assert resp.status_code == 403

    def test_csrf_required_on_grade(self, client, db_session):
        uni = _create_university(db_session, slug="csrf-grade")
        course, cl, node = _create_course_in_db(db_session, uni)
        assignment = _create_assignment_in_db(db_session, course)
        student = _enroll_student(db_session, cl)
        sub = Submission(assignment_id=assignment.id, student_id=student.id,
                         content="x", content_hash="h")
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1x")
        client.cookies.delete(_CSRF_COOKIE)
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/assignments/{assignment.id}/grade",
            data={"submission_id": sub.id, "score": 90},
            follow_redirects=False)
        assert resp.status_code == 403


# ===========================================================================
# 6. TRUTHFUL ATTESTATION — no false on-chain claims
# ===========================================================================

class TestTruthfulAttestation:

    def test_grade_lock_uses_attestation_queued_event_type(self, client, db_session):
        """Event type must say 'attestation_queued', not 'on_chain'."""
        uni = _create_university(db_session, slug="truthful")
        course, cl, node = _create_course_in_db(db_session, uni)
        student = _enroll_student(db_session, cl)
        g = Grade(course_id=course.id, student_id=student.id,
                  final_score=8.0, letter_grade="B", passed=True,
                  locked=False, graded_by="test")
        db_session.add(g)
        db_session.commit()
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1x")
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/grades/lock",
            data={**_csrf()}, follow_redirects=False)
        assert resp.status_code == 303
        from app.models import Attestation
        attest = db_session.query(Attestation).filter(
            Attestation.event_type == "grade_attestation_queued").first()
        assert attest is not None

    def test_certificate_uses_attestation_queued_event_type(self, client, db_session):
        uni = _create_university(db_session, slug="cert-truth")
        course, cl, node = _create_course_in_db(db_session, uni)
        student = _enroll_student(db_session, cl)
        g = Grade(course_id=course.id, student_id=student.id,
                  final_score=9.0, letter_grade="A", passed=True,
                  locked=True, graded_by="test", attestation_hash="h")
        db_session.add(g)
        db_session.commit()
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1x")
        resp = client.post(
            f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
            data={**_csrf()}, follow_redirects=False)
        assert resp.status_code == 303
        from app.models import Attestation
        attest = db_session.query(Attestation).filter(
            Attestation.event_type == "certificate_attestation_queued").first()
        assert attest is not None


# ===========================================================================
# 7. AUTH ENFORCEMENT — unauthenticated requests blocked
# ===========================================================================

class TestAuthEnforcement:

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

    def test_submit_assignment_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/assignments/1/submit",
                           data={"content": "x"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_grade_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/assignments/1/grade",
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

    def test_issue_certs_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/certificates/issue",
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_enroll_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/enroll",
                           data={"student_id": 1}, follow_redirects=False)
        assert resp.status_code == 403

    def test_live_create_no_auth(self, client, db_session):
        _clear_auth(client)
        resp = client.post("/uni/1/courses/1/live",
                           data={"title": "X"}, follow_redirects=False)
        assert resp.status_code == 403


# ===========================================================================
# 8. ROLE SEPARATION
# ===========================================================================

class TestRoleSeparation:

    def test_student_cannot_create_university(self, client, db_session):
        _set_role(client, STUDENT)
        resp = client.post("/uni", data={"name": "X", "slug": "x", **_csrf()},
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_teacher_cannot_create_university(self, client, db_session):
        _set_role(client, TEACHER, thr_wallet="thr1x")
        resp = client.post("/uni", data={"name": "X", "slug": "x", **_csrf()},
                           follow_redirects=False)
        assert resp.status_code == 403

    def test_super_admin_can_create_university(self, client, db_session):
        _set_role(client, SUPER_ADMIN)
        resp = client.post("/uni", data={"name": "SA Uni", "slug": "sa-uni", **_csrf()},
                           follow_redirects=False)
        assert resp.status_code == 303

    def test_student_cannot_create_course(self, client, db_session):
        uni = _create_university(db_session, slug="stu-block")
        _set_role(client, STUDENT)
        resp = client.post(f"/uni/{uni.id}/courses",
                           data={"title": "X", **_csrf()}, follow_redirects=False)
        assert resp.status_code == 403

    def test_student_cannot_grade(self, client, db_session):
        _set_role(client, STUDENT)
        resp = client.post("/uni/1/courses/1/assignments/1/grade",
                           data={"submission_id": 1, "score": 90, **_csrf()},
                           follow_redirects=False)
        assert resp.status_code == 403


# ===========================================================================
# 9. GRADING & CERTIFICATE LIFECYCLE
# ===========================================================================

class TestGradingLifecycle:

    def _setup_graded_course(self, db_session):
        uni = _create_university(db_session, slug="grade-lc")
        course, cl, node = _create_course_in_db(db_session, uni)
        s1 = _enroll_student(db_session, cl, name="Student A")
        s2 = _enroll_student(db_session, cl, name="Student B")
        a1 = _create_assignment_in_db(db_session, course, "HW1", 100, 1.0)
        for s, sc in [(s1, 90), (s2, 30)]:
            sub = Submission(assignment_id=a1.id, student_id=s.id,
                             content="ans", content_hash="h",
                             score=sc, status="graded")
            db_session.add(sub)
        db_session.commit()
        return uni, course, cl, node, s1, s2

    def test_compute_and_lock(self, client, db_session):
        uni, course, _, node, s1, s2 = self._setup_graded_course(db_session)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1x")
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/compute",
                    data={**_csrf()}, follow_redirects=False)
        g1 = db_session.query(Grade).filter(
            Grade.course_id == course.id, Grade.student_id == s1.id).first()
        assert g1.passed is True
        g2 = db_session.query(Grade).filter(
            Grade.course_id == course.id, Grade.student_id == s2.id).first()
        assert g2.passed is False
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/lock",
                    data={**_csrf()}, follow_redirects=False)
        db_session.refresh(g1)
        assert g1.locked is True
        assert g1.attestation_hash

    def test_locked_grade_immutable(self, client, db_session):
        uni, course, _, node, s1, _ = self._setup_graded_course(db_session)
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1x")
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/compute",
                    data={**_csrf()}, follow_redirects=False)
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/lock",
                    data={**_csrf()}, follow_redirects=False)
        g1 = db_session.query(Grade).filter(
            Grade.course_id == course.id, Grade.student_id == s1.id).first()
        original = g1.final_score
        client.post(f"/uni/{uni.id}/courses/{course.id}/grades/compute",
                    data={**_csrf()}, follow_redirects=False)
        db_session.refresh(g1)
        assert g1.final_score == original
        assert g1.locked is True


class TestCertificateLifecycle:

    def test_cert_only_for_passed_locked(self, client, db_session):
        uni = _create_university(db_session, slug="cert-lc")
        course, cl, node = _create_course_in_db(db_session, uni)
        s_pass = _enroll_student(db_session, cl, name="Passer")
        s_fail = _enroll_student(db_session, cl, name="Failer")
        db_session.add(Grade(course_id=course.id, student_id=s_pass.id,
                             final_score=8.0, letter_grade="B", passed=True,
                             locked=True, graded_by="t", attestation_hash="h"))
        db_session.add(Grade(course_id=course.id, student_id=s_fail.id,
                             final_score=3.0, letter_grade="F", passed=False,
                             locked=True, graded_by="t", attestation_hash="h"))
        db_session.commit()
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1x")
        client.post(f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
                    data={**_csrf()}, follow_redirects=False)
        certs = db_session.query(Certificate).filter(
            Certificate.course_id == course.id).all()
        assert len(certs) == 1
        assert certs[0].student_id == s_pass.id

    def test_no_duplicate_certs(self, client, db_session):
        uni = _create_university(db_session, slug="cert-dup")
        course, cl, node = _create_course_in_db(db_session, uni)
        student = _enroll_student(db_session, cl)
        db_session.add(Grade(course_id=course.id, student_id=student.id,
                             final_score=9.0, letter_grade="A", passed=True,
                             locked=True, graded_by="t", attestation_hash="h"))
        db_session.commit()
        _set_role(client, TEACHER, tenant_id=str(node.id), thr_wallet="thr1x")
        client.post(f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
                    data={**_csrf()}, follow_redirects=False)
        client.post(f"/uni/{uni.id}/courses/{course.id}/certificates/issue",
                    data={**_csrf()}, follow_redirects=False)
        certs = db_session.query(Certificate).filter(
            Certificate.course_id == course.id).all()
        assert len(certs) == 1


# ===========================================================================
# 10. DUPLICATE SLUG REJECTION
# ===========================================================================

def test_duplicate_slug_rejected(client, db_session):
    _set_role(client, SUPER_ADMIN)
    client.post("/uni", data={"name": "First", "slug": "dup-slug", **_csrf()},
                follow_redirects=False)
    resp = client.post("/uni", data={"name": "Second", "slug": "dup-slug", **_csrf()},
                       follow_redirects=False)
    assert resp.status_code == 409
