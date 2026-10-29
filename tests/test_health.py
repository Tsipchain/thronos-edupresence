"""Basic health and smoke tests."""


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "service" in data


def test_health_has_l2e_field(client):
    resp = client.get("/health")
    data = resp.json()
    assert "l2e_enabled" in data
