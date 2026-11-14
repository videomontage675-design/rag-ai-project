"""The documents JSON API contract (DESIGN-001 §11.1), through the real app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_app.web.context import AppContext

pytestmark = pytest.mark.integration

API = "/api/v1/documents"
GUIDE = "# دليل\n\n## قسم\n\nنص الدليل.\n".encode()
GUIDE_V2 = GUIDE + "\n## قسم ثان\n\nنص إضافي.\n".encode()


def _ctx(client: TestClient) -> AppContext:
    context: AppContext = client.app.state.context  # type: ignore[attr-defined]
    return context


def _upload(client: TestClient, data: bytes = GUIDE, name: str = "دليل.md") -> dict:
    response = client.post(API, files={"file": (name, data, "text/markdown")})
    assert response.status_code == 202, response.text
    return response.json()


def _process(client: TestClient) -> None:
    _ctx(client).worker.run_until_idle()


def test_upload_list_detail_and_processing(client: TestClient) -> None:
    created = _upload(client)

    assert created["display_name"] == "دليل"
    assert created["is_processing"] is True
    assert created["versions"][0]["status"] == "uploaded"
    _process(client)

    listed = client.get(API).json()
    assert [(d["display_name"], d["status"], d["active_version"]) for d in listed] == [
        ("دليل", "ready", 1)
    ]
    detail = client.get(f"{API}/{created['id']}").json()
    assert detail["is_processing"] is False
    assert detail["versions"][0]["is_active"] is True
    assert detail["versions"][0]["chunk_count"] == 1
    assert detail["versions"][0]["error"] is None


def test_version_activate_delete_and_retry_flow(client: TestClient) -> None:
    doc = _upload(client)
    _process(client)
    v2 = client.post(f"{API}/{doc['id']}/versions", files={"file": ("v2.md", GUIDE_V2)})
    assert v2.status_code == 202 and v2.json()["version_number"] == 2
    _process(client)
    v1_id = client.get(f"{API}/{doc['id']}").json()["versions"][1]["id"]

    activated = client.post(f"{API}/{doc['id']}/versions/{v1_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["active_version_id"] == v1_id

    deleted = client.delete(f"{API}/{doc['id']}/versions/{v2.json()['id']}")
    assert deleted.status_code == 204

    refused = client.delete(f"{API}/{doc['id']}/versions/{v1_id}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "VERSION_IS_ACTIVE"

    retry = client.post(f"{API}/{doc['id']}/versions/{v1_id}/retry")
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "VERSION_NOT_FAILED"

    assert client.delete(f"{API}/{doc['id']}").status_code == 204
    assert client.get(API).json() == []


def test_failed_version_reports_its_arabic_error_and_can_be_retried(client: TestClient) -> None:
    doc = _upload(client, "# عنوان فقط\n".encode())
    _process(client)

    version = client.get(f"{API}/{doc['id']}").json()["versions"][0]
    assert version["status"] == "failed"
    assert version["error"] == {"code": "EMPTY_FILE", "message": "الملف فارغ."}
    retried = client.post(f"{API}/{doc['id']}/versions/{version['id']}/retry")
    assert retried.status_code == 202 and retried.json()["status"] == "uploaded"


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("a.exe", b"MZ\x90\x00", 400, "UNSUPPORTED_TYPE"),
        ("a.md", b"", 400, "EMPTY_FILE"),
        ("a.md", b"\xff\xfe\x00", 400, "INVALID_UTF8"),
    ],
)
def test_invalid_upload_errors_follow_the_contract(
    client: TestClient, name: str, data: bytes, status: int, code: str
) -> None:
    response = client.post(API, files={"file": (name, data)})

    assert response.status_code == status
    body = response.json()["error"]
    assert body["code"] == code and body["message"]


def test_duplicate_upload_is_409_with_document_pointer(client: TestClient) -> None:
    doc = _upload(client)

    response = client.post(API, files={"file": ("copy.md", GUIDE)})

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"document_id": doc["id"]}


def test_oversized_upload_is_refused_by_content_length(client: TestClient) -> None:
    limit = _ctx(client).settings.limits.max_upload_mb * 1024 * 1024

    response = client.post(API, files={"file": ("big.md", b"a" * (limit + 100 * 1024))})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert "10" in response.json()["error"]["message"]


def test_missing_file_field_is_a_validation_error(client: TestClient) -> None:
    response = client.post(API, data={"x": "1"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_ids_are_404(client: TestClient) -> None:
    assert client.get(f"{API}/nope").status_code == 404
    assert client.delete(f"{API}/nope").status_code == 404
    assert client.post(f"{API}/nope/versions", files={"file": ("a.md", GUIDE)}).status_code == 404
    doc = _upload(client)
    assert client.post(f"{API}/{doc['id']}/versions/nope/activate").status_code == 404


def test_htmx_errors_render_an_arabic_alert_into_the_alert_region(client: TestClient) -> None:
    response = client.get(f"{API}/nope", headers={"HX-Request": "true"})

    assert response.status_code == 404
    assert response.headers["HX-Retarget"] == "#alerts"
    assert 'role="alert"' in response.text and "العنصر المطلوب غير موجود" in response.text
