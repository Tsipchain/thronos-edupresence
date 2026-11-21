from app.config import Settings
from app.db import _ensure_sqlite_parent


def test_sqlite_initialization_creates_only_configured_parent(tmp_path):
    database = tmp_path / "nested" / "edupresence.db"

    _ensure_sqlite_parent(f"sqlite:///{database}")

    assert database.parent.is_dir()


def test_relative_and_memory_databases_do_not_require_root_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    _ensure_sqlite_parent("sqlite:///local-test.db")
    _ensure_sqlite_parent("sqlite:///:memory:")

    assert not (tmp_path / "data").exists()


def test_production_persistence_and_l2e_defaults_remain_unchanged():
    assert Settings.model_fields["database_url"].default == (
        "sqlite:////data/edupresence_v4.db"
    )
    assert Settings.model_fields["l2e_enabled"].default is False
