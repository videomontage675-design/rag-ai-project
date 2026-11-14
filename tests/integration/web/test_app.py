import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from rag_app.config.settings import Settings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.web.app import create_app

pytestmark = pytest.mark.integration


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "client-req-0001"})

    assert response.headers["X-Request-ID"] == "client-req-0001"
    assert client.get("/health").headers["X-Request-ID"]


def test_malformed_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})

    assert response.headers["X-Request-ID"] != "bad id with spaces"


def test_system_status_on_empty_database(client: TestClient) -> None:
    body = client.get("/api/v1/system/status").json()

    assert body["schema_version"] == 1
    assert body["documents"] == 0
    assert body["reindex_required"] is False
    assert {p["role"] for p in body["providers"]} == {"embedding", "chat"}


def test_system_status_never_exposes_key_variables(client: TestClient) -> None:
    text = client.get("/api/v1/system/status").text

    assert "API_KEY" not in text


def test_unknown_api_route_returns_json_error_contract(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_app_error_is_mapped_to_status_and_arabic_message(settings: Settings) -> None:
    app = create_app(settings)
    probe = APIRouter()

    @probe.get("/probe")
    def _raise() -> None:
        raise AppError(ErrorCode.FILE_TOO_LARGE, limit_mb=10)

    app.include_router(probe)
    with TestClient(app) as test_client:
        response = test_client.get("/probe")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert "10" in response.json()["error"]["message"]


def test_unexpected_exception_returns_generic_internal_error(settings: Settings) -> None:
    app = create_app(settings)
    probe = APIRouter()

    @probe.get("/boom")
    def _boom() -> None:
        raise RuntimeError("secret internals")

    app.include_router(probe)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internals" not in response.text


def test_home_page_is_arabic_rtl_with_domain_profile(client: TestClient) -> None:
    html = client.get("/").text

    assert 'dir="rtl"' in html and 'lang="ar"' in html
    assert "مساعد ضفيرة" in html
    assert "ما المدة الافتراضية للموعد؟" in html


def test_openapi_document_lists_versioned_api(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/system/status" in paths
    assert "/health" in paths
