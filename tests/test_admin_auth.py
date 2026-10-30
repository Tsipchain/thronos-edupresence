"""Admin key authentication tests."""
from app.config import settings


def test_admin_import_rejects_without_key(client):
    resp = client.post("/api/admin/import-class", json={
        "node_name": "Test Node",
        "classroom_name": "Test Class",
        "students": [],
    })
    assert resp.status_code == 403


def test_admin_import_rejects_wrong_key(client):
    resp = client.post(
        "/api/admin/import-class",
        json={
            "node_name": "Test Node",
            "classroom_name": "Test Class",
            "students": [],
        },
        headers={"X-Admin-Key": "wrong-key"},
    )
    assert resp.status_code == 403


def test_admin_import_accepts_correct_key(client):
    effective_key = settings.admin_api_key or settings.token_secret
    resp = client.post(
        "/api/admin/import-class",
        json={
            "node_name": "Test Admin Node",
            "classroom_name": "Test Admin Class",
            "teacher_name": "Teacher A",
            "students": [
                {"external_ref": "S001", "full_name": "Student One", "phone": "+30691234567"},
            ],
        },
        headers={"X-Admin-Key": effective_key},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["students_created"] == 1
