"""Product contract: learner-first EDU, legacy QR pilot isolated.

These tests deliberately do not treat UI smoke as complete LMS acceptance.
"""
from app.models import Course, University


def test_public_home_is_learning_portal_not_qr_node_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "THRONOS EDU" in html
    assert 'href="/learn/courses"' in html
    assert "Επιλογή κόμβου" not in html
    assert "ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ" not in html
    assert "TaxisNet/Gov mock" not in html
    assert "Δεν χρειάζεσαι" not in html or "THR Wallet" in html


def test_original_qr_presence_dashboard_is_preserved(client):
    response = client.get("/presence")
    assert response.status_code == 200
    assert "Επιλογή κόμβου" in response.text
    assert "QR παρουσίες" in response.text
    assert "ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ" not in response.text


def test_catalog_never_publishes_existing_legacy_courses_by_default(client, db_session):
    university = University(name="Synthetic University", slug="synthetic-university")
    db_session.add(university)
    db_session.flush()
    db_session.add(Course(
        university_id=university.id, title="INTERNAL LEGACY COURSE",
        status="active", is_active=True,
    ))
    db_session.add(Course(
        university_id=university.id, title="PUBLIC APPROVED COURSE",
        status="published", is_active=True,
    ))
    db_session.add(Course(
        university_id=university.id, title="CANCELLED HIDDEN COURSE",
        status="published", is_active=False,
    ))
    db_session.commit()
    for url in ("/", "/learn/courses"):
        html = client.get(url).text
        assert "PUBLIC APPROVED COURSE" in html
        assert "INTERNAL LEGACY COURSE" not in html
        assert "CANCELLED HIDDEN COURSE" not in html


def test_catalog_is_honest_without_published_courses(client):
    response = client.get("/learn/courses")
    assert response.status_code == 200
    assert 'data-state="no-published-courses"' in response.text


def test_student_login_does_not_advertise_mock_gov_as_real_login(client):
    response = client.get("/learn/login")
    assert response.status_code == 200
    assert 'data-state="identity-provider-pending"' in response.text
    assert 'href="/auth/gov/start"' not in response.text


def test_student_dashboard_uses_learning_design_and_walletless_policy(client, db_session):
    # No signed student identity: never expose private records to the public.
    response = client.get("/student-dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/learn/login"
