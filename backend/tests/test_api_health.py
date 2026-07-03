import httpx
from app.api import health as health_module


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_health_reports_ok_when_db_and_hiring_agent_are_up(client, monkeypatch):
    monkeypatch.setattr(health_module.httpx, "get", lambda url, timeout: FakeResponse(200))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"database": "ok", "hiring_agent_service": "ok"}


def test_health_reports_503_when_hiring_agent_is_down(client, monkeypatch):
    def raise_connect_error(url, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(health_module.httpx, "get", raise_connect_error)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["hiring_agent_service"] == "error"
