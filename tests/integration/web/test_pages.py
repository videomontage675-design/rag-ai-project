"""Server-rendered pages and HTMX fragments (DESIGN-001 §11.2)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from rag_app.web.context import AppContext

pytestmark = pytest.mark.integration

HX = {"HX-Request": "true"}
GUIDE = "# دليل المواعيد\n\n## إنشاء موعد\n\nمن شاشة التقويم.\n".encode()


def _ctx(client: TestClient) -> AppContext:
    context: AppContext = client.app.state.context  # type: ignore[attr-defined]
    return context


def _upload_ui(client: TestClient, data: bytes = GUIDE, name: str = "دليل المواعيد.md") -> str:
    response = client.post("/documents", files={"file": (name, data)}, headers=HX)
    assert response.status_code == 200, response.text
    return response.text


def _doc_id(client: TestClient) -> str:
    return _ctx(client).documents.list_documents()[0].id


def test_every_page_has_the_shell_and_marks_the_current_section(client: TestClient) -> None:
    for path, current in (("/", "الرئيسية"), ("/documents", "المستندات")):
        html = client.get(path).text
        assert 'lang="ar" dir="rtl"' in html
        assert 'href="#content"' in html  # skip link
        assert re.search(rf'aria-current="page">{current}<', html)
        assert "htmx-2.0.11.min.js" in html and "<script>" not in html  # no inline script


def test_empty_library_invites_the_first_upload(client: TestClient) -> None:
    html = client.get("/documents").text

    assert "المكتبة فارغة" in html
    assert "hx-trigger" not in html.split('id="library"', 1)[1].split(">", 1)[0]
    assert "أضف أول مستند" in client.get("/").text


def test_upload_returns_the_table_that_polls_and_an_oob_confirmation(client: TestClient) -> None:
    html = _upload_ui(client)

    assert html.startswith('\n<section id="library"') or 'id="library"' in html.split("\n", 3)[2]
    assert 'hx-trigger="every 2s"' in html  # waiting for processing
    assert "بانتظار المعالجة" in html and 'class="weave"' in html
    assert 'id="alerts" hx-swap-oob="innerHTML"' in html
    assert "رُفع «دليل المواعيد» وتجري معالجته الآن." in html

    _ctx(client).worker.run_until_idle()
    fragment = client.get("/documents/_library", headers=HX).text
    assert "every 2s" not in fragment  # polling stops once processing is done
    assert "جاهز" in fragment


def test_upload_error_is_an_alert_retargeted_into_the_alert_region(client: TestClient) -> None:
    response = client.post("/documents", files={"file": ("a.docx", b"PK\x03")}, headers=HX)

    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#alerts"
    assert 'role="alert"' in response.text and "نوع الملف غير مدعوم" in response.text


def test_detail_page_shows_history_and_actions(client: TestClient) -> None:
    _upload_ui(client)
    _ctx(client).worker.run_until_idle()
    doc_id = _doc_id(client)
    response = client.post(
        f"/documents/{doc_id}/versions",
        files={"file": ("v2.md", GUIDE + "\n## إلغاء\n\nنص.\n".encode())},
        headers=HX,
    )
    assert "رُفعت النسخة 2" in response.text and "every 2s" in response.text
    _ctx(client).worker.run_until_idle()

    html = client.get(f"/documents/{doc_id}").text

    assert html.count('class="version') >= 2
    assert "معتمدة في الإجابات" in html
    assert "اعتماد هذه النسخة" in html  # v1 can be restored
    assert 'hx-confirm="ستعتمد إجابات المساعد على النسخة 1' in html
    assert html.count('<bdi dir="ltr">fake-embedding</bdi>') == 2  # model of each version


def test_activate_retry_and_version_delete_return_the_updated_block(client: TestClient) -> None:
    _upload_ui(client)
    _ctx(client).worker.run_until_idle()
    doc_id = _doc_id(client)
    client.post(f"/documents/{doc_id}/versions", files={"file": ("bad.md", b"# x\n")}, headers=HX)
    _ctx(client).worker.run_until_idle()
    detail = _ctx(client).documents.get_document(doc_id)
    failed, ready = detail.versions

    retried = client.post(f"/documents/{doc_id}/versions/{failed.id}/retry", headers=HX)
    assert "أُعيدت النسخة 2 إلى المعالجة" in retried.text
    _ctx(client).worker.run_until_idle()

    deleted = client.delete(f"/documents/{doc_id}/versions/{failed.id}", headers=HX)
    assert deleted.status_code == 200 and "حُذفت النسخة." in deleted.text

    activated = client.post(f"/documents/{doc_id}/versions/{ready.id}/activate", headers=HX)
    assert "اعتُمدت النسخة 1" in activated.text


def test_deleting_the_document_redirects_to_the_library_with_a_notice(client: TestClient) -> None:
    _upload_ui(client)
    doc_id = _doc_id(client)

    response = client.delete(f"/documents/{doc_id}", headers=HX)

    assert response.headers["HX-Redirect"].startswith("http://127.0.0.1:8000/documents?deleted=")
    page = client.get(response.headers["HX-Redirect"]).text
    assert "حُذف «دليل المواعيد»." in page
    assert client.get(f"/documents/{doc_id}").status_code == 404


def test_deleting_the_last_version_also_redirects(client: TestClient) -> None:
    _upload_ui(client)
    doc_id = _doc_id(client)
    version_id = _ctx(client).documents.get_document(doc_id).versions[0].id

    response = client.delete(f"/documents/{doc_id}/versions/{version_id}", headers=HX)

    assert "HX-Redirect" in response.headers
    assert _ctx(client).documents.list_documents() == []


def test_user_text_is_escaped(client: TestClient) -> None:
    _upload_ui(client, name='<img src=x onerror="alert(1)">.md')

    html = client.get("/documents").text

    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=" in html


def test_ready_version_without_vectors_says_reindexing_creates_them(client: TestClient) -> None:
    _upload_ui(client)
    _ctx(client).worker.run_until_idle()
    with _ctx(client).db.transaction() as conn:  # a version processed before Phase 7 (D-034)
        conn.execute("DELETE FROM chunk_embeddings")
        conn.execute("UPDATE document_versions SET embedding_model = NULL")

    html = client.get(f"/documents/{_doc_id(client)}").text

    assert "لم تُنشأ بعد؛ تُنشأ بإعادة الفهرسة" in html
