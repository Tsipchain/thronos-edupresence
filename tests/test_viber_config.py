"""Verify Viber config field exists to prevent runtime crash."""
from app.config import settings


def test_viber_min_api_version_exists():
    assert hasattr(settings, "viber_min_api_version")
    assert isinstance(settings.viber_min_api_version, int)
    assert settings.viber_min_api_version >= 1
