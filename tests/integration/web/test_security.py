"""Local-only guard (CLAUDE.md §12): DNS rebinding, cross-site requests, security headers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_app.config.settings import Settings
from rag_app.web.app import create_app

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "localhost"])
def test_loopback_hosts_are_served(client: TestClient, host: str) -> None:
    assert client.get("/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host", ["evil.example:8000", "192.168.1.5:8000", "127.0.0.1.evil.example"]
)
def test_foreign_host_is_refused(client: TestClient, host: str) -> None:
    response = client.get("/api/v1/documents", headers={"Host": host})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ORIGIN"


def test_cross_site_post_is_refused_and_changes_nothing(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents",
        files={"file": ("a.md", "# أ\n\nنص.\n".encode())},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert client.get("/api/v1/documents").json() == []


@pytest.mark.parametrize(
    "headers",
    [{"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}, {"Origin": "http://localhost:9999"}],
)
def test_other_cross_site_signals_are_refused_for_changes(
    client: TestClient, headers: dict[str, str]
) -> None:
    assert client.delete("/api/v1/documents/x", headers=headers).status_code == 403


def test_same_origin_and_header_less_clients_may_change_data(client: TestClient) -> None:
    same = {"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"}

    assert client.delete("/api/v1/documents/x", headers=same).status_code == 404
    assert client.delete("/api/v1/documents/x").status_code == 404  # curl-like: no Origin


def test_cross_site_reads_are_not_blocked_by_origin(client: TestClient) -> None:
    # Reading is harmless: browsers do not let a foreign page see the response (CORS).
    assert client.get("/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_every_response_carries_security_headers(client: TestClient) -> None:
    for response in (client.get("/"), client.get("/nope"), client.get("/health")):
        csp = response.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


def test_owner_can_explicitly_allow_non_local_hosts(settings: Settings) -> None:
    server = settings.server.model_copy(update={"allow_non_local": True})
    app = create_app(settings.model_copy(update={"server": server}))

    with TestClient(app, base_url="http://192.168.1.5:8000") as client:
        assert client.get("/health").status_code == 200
