from fastapi.testclient import TestClient

from photoflow.main import create_app


def test_health(settings, engine):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_missing_nas_is_unhealthy(settings, engine):
    with TestClient(create_app(settings)) as client:
        settings.nas_root.rmdir()
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}


def test_startup_requires_explicit_migration(settings):
    import pytest

    with pytest.raises(RuntimeError, match="migration required"), TestClient(create_app(settings)):
        pass
