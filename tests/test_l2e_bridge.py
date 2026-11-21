"""Tests for L2E Bridge — pseudonymous attestation relay and outbox."""
import json
import os
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///test_edupresence.db")
os.environ.setdefault("L2E_ENABLED", "false")

from app.l2e_bridge import (
    pseudonymous_student_ref,
    deterministic_event_id,
    build_attestation_hash,
    enqueue_attestation,
    process_outbox,
    reset_outbox,
)
from app.models import L2EOutboxEntry


class TestPseudonymousIdentity:
    def test_hmac_deterministic(self):
        ref1 = pseudonymous_student_ref("tenant-a", 42, secret="test-key")
        ref2 = pseudonymous_student_ref("tenant-a", 42, secret="test-key")
        assert ref1 == ref2
        assert len(ref1) == 24

    def test_different_tenant_different_ref(self):
        ref_a = pseudonymous_student_ref("tenant-a", 42, secret="key")
        ref_b = pseudonymous_student_ref("tenant-b", 42, secret="key")
        assert ref_a != ref_b

    def test_different_student_different_ref(self):
        ref1 = pseudonymous_student_ref("t", 1, secret="key")
        ref2 = pseudonymous_student_ref("t", 2, secret="key")
        assert ref1 != ref2

    def test_empty_secret_returns_empty(self):
        with patch("app.l2e_bridge.settings") as mock_settings:
            mock_settings.l2e_api_key = ""
            ref = pseudonymous_student_ref("t", 1, secret="")
            assert ref == ""

    def test_different_secret_different_ref(self):
        ref1 = pseudonymous_student_ref("t", 1, secret="key-a")
        ref2 = pseudonymous_student_ref("t", 1, secret="key-b")
        assert ref1 != ref2


class TestDeterministicEventId:
    def test_stable_id(self):
        eid1 = deterministic_event_id("tenant", "class-1", "lesson-5", 1, "stu-ref")
        eid2 = deterministic_event_id("tenant", "class-1", "lesson-5", 1, "stu-ref")
        assert eid1 == eid2
        assert len(eid1) == 32

    def test_different_inputs_different_id(self):
        eid1 = deterministic_event_id("tenant", "class-1", "lesson-5", 1, "stu-a")
        eid2 = deterministic_event_id("tenant", "class-1", "lesson-5", 1, "stu-b")
        assert eid1 != eid2


class TestAttestationHash:
    def test_hash_deterministic(self):
        record = {"classroom_id": 1, "date": "2026-01-15", "status": "present", "hours": 2}
        h1 = build_attestation_hash(record)
        h2 = build_attestation_hash(record)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_status_different_hash(self):
        base = {"classroom_id": 1, "date": "2026-01-15", "hours": 2}
        h1 = build_attestation_hash({**base, "status": "present"})
        h2 = build_attestation_hash({**base, "status": "absent"})
        assert h1 != h2

    def test_extra_fields_ignored(self):
        base = {"classroom_id": 1, "date": "2026-01-15", "status": "present", "hours": 2}
        h1 = build_attestation_hash(base)
        h2 = build_attestation_hash({**base, "student_name": "John", "tax_id": "123"})
        assert h1 == h2


class TestEnqueueAttestation:
    def test_disabled_returns_false(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = False
            result = enqueue_attestation(
                db_session, "evt-1", "tenant", "stu-ref", "hash123", {"data": 1}
            )
            assert result is False
            assert db_session.query(L2EOutboxEntry).count() == 0

    def test_enabled_enqueues(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = True
            result = enqueue_attestation(
                db_session, "evt-1", "tenant", "stu-ref", "hash123",
                {"test": "data"}, attestation_version=1, max_retries=3,
            )
            assert result is True
            entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt-1").first()
            assert entry is not None
            assert entry.status == "pending"
            assert entry.tenant_scope == "tenant"
            assert entry.student_ref == "stu-ref"
            assert entry.attestation_hash == "hash123"
            assert json.loads(entry.payload_json) == {"test": "data"}

    def test_duplicate_returns_false(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = True
            enqueue_attestation(db_session, "evt-dup", "t", "s", "h", {})
            db_session.commit()
            result = enqueue_attestation(db_session, "evt-dup", "t", "s", "h", {})
            assert result is False
            assert db_session.query(L2EOutboxEntry).filter_by(event_id="evt-dup").count() == 1


class TestProcessOutbox:
    def test_disabled_returns_zeros(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = False
            result = process_outbox(db_session)
            assert result == {"delivered": 0, "failed": 0, "skipped": 0}

    def test_successful_delivery(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = True
            mock_s.l2e_base_url = "http://localhost:5000"
            mock_s.l2e_api_key = "test-key"
            enqueue_attestation(db_session, "evt-ok", "t", "s", "h", {"ok": True})
            db_session.commit()

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"ok":true}'

            with patch("app.l2e_bridge.requests.post", return_value=mock_resp) as mock_post:
                result = process_outbox(db_session)
                assert result["delivered"] == 1
                assert result["failed"] == 0
                mock_post.assert_called_once()

            entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt-ok").first()
            assert entry.status == "delivered"
            assert entry.delivered_at is not None

    def test_failed_delivery_retries(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = True
            mock_s.l2e_base_url = "http://localhost:5000"
            mock_s.l2e_api_key = "test-key"
            enqueue_attestation(db_session, "evt-fail", "t", "s", "h", {}, max_retries=3)
            db_session.commit()

            mock_resp = MagicMock()
            mock_resp.status_code = 500

            with patch("app.l2e_bridge.requests.post", return_value=mock_resp):
                result = process_outbox(db_session)
                assert result["delivered"] == 0

            entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt-fail").first()
            assert entry.status == "pending"
            assert entry.retry_count == 1
            assert entry.next_retry_at is not None

    def test_max_retries_marks_failed(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = True
            mock_s.l2e_base_url = "http://localhost:5000"
            mock_s.l2e_api_key = "test-key"
            enqueue_attestation(db_session, "evt-maxed", "t", "s", "h", {}, max_retries=2)
            db_session.commit()

            entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt-maxed").first()
            entry.retry_count = 2
            db_session.commit()

            result = process_outbox(db_session)
            assert result["failed"] == 1

            entry = db_session.query(L2EOutboxEntry).filter_by(event_id="evt-maxed").first()
            assert entry.status == "failed"
            assert entry.failure_reason == "max retries exceeded"


class TestResetOutbox:
    def test_clears_all(self, db_session):
        with patch("app.l2e_bridge.settings") as mock_s:
            mock_s.l2e_enabled = True
            enqueue_attestation(db_session, "evt-1", "t", "s", "h", {})
            enqueue_attestation(db_session, "evt-2", "t", "s", "h", {})
            db_session.commit()
            assert db_session.query(L2EOutboxEntry).count() == 2

            reset_outbox(db_session)
            assert db_session.query(L2EOutboxEntry).count() == 0


class TestOutboxStatusEndpoint:
    def test_outbox_status_no_key(self, client):
        resp = client.get("/api/v1/l2e/outbox/status")
        assert resp.status_code == 422 or resp.status_code == 401

    def test_outbox_status_bad_key(self, client):
        resp = client.get("/api/v1/l2e/outbox/status", headers={"X-Api-Key": "wrong"})
        assert resp.status_code == 401

    def test_outbox_status_ok(self, client, db_session):
        with patch("app.api.settings") as mock_s:
            mock_s.l2e_api_key = "test-key"
            mock_s.l2e_enabled = False
            resp = client.get("/api/v1/l2e/outbox/status", headers={"X-Api-Key": "test-key"})
            assert resp.status_code == 200
            data = resp.json()
            assert "total" in data
            assert "pending" in data
            assert "delivered" in data
            assert "failed" in data
            assert data["l2e_enabled"] is False

    def test_outbox_failed_empty(self, client):
        with patch("app.api.settings") as mock_s:
            mock_s.l2e_api_key = "test-key"
            resp = client.get("/api/v1/l2e/outbox/failed", headers={"X-Api-Key": "test-key"})
            assert resp.status_code == 200
            assert resp.json()["count"] == 0


class TestNoPiiLeakage:
    def test_payload_has_no_pii_fields(self):
        ref = pseudonymous_student_ref("tenant", 42, secret="key")
        eid = deterministic_event_id("tenant", "class-1", "lesson-1", 1, ref)
        payload = {
            "source": "thronos_edupresence",
            "event_id": eid,
            "tenant_id": "tenant",
            "l2e_course_id": "edu-1",
            "lesson_id": 1,
            "student_ref": ref,
            "attestation_hash": "abc123",
            "attendance_status": "present",
            "confirmation_method": "nfc",
        }
        payload_str = json.dumps(payload)
        pii_fields = ["tax_id", "email", "phone", "name", "surname", "address",
                       "birth", "national_id", "passport"]
        for field in pii_fields:
            assert field not in payload_str.lower()

    def test_student_ref_not_reversible(self):
        ref = pseudonymous_student_ref("tenant", 42, secret="key")
        assert "42" not in ref
        assert "tenant" not in ref
