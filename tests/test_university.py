"""University tenant and course tests.

Note: template-rendering routes (GET /uni, GET /uni/{id}) fail with the
installed Starlette 1.7 because app/main.py's render() uses the old
TemplateResponse(name, context) signature.  These tests verify DB logic
via POST endpoints with follow_redirects=False to avoid template errors.
"""
from app.models import University


def test_create_university(client, db_session):
    resp = client.post(
        "/uni",
        data={
            "name": "Test University",
            "slug": "test-uni",
            "domain": "testuni.edu",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    uni = db_session.query(University).filter(University.slug == "test-uni").first()
    assert uni is not None
    assert uni.name == "Test University"


def test_duplicate_slug_rejected(client, db_session):
    uni = University(name="First Uni", slug="dup-slug", domain="first.edu")
    db_session.add(uni)
    db_session.commit()

    resp = client.post(
        "/uni",
        data={"name": "Second Uni", "slug": "dup-slug", "domain": "second.edu"},
        follow_redirects=False,
    )
    assert resp.status_code == 409


def test_create_course(client, db_session):
    uni = University(name="Course Uni", slug="course-uni", domain="course.edu")
    db_session.add(uni)
    db_session.commit()
    db_session.refresh(uni)

    resp = client.post(
        f"/uni/{uni.id}/courses",
        data={
            "title": "Intro to Testing",
            "description": "A test course",
            "teacher_name": "Prof Test",
            "teacher_email": "prof@test.edu",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
