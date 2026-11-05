from fastapi.testclient import TestClient

from photoflow.main import create_app


def test_health():
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
