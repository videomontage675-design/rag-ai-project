"""HTML pages and HTMX fragments (DESIGN-001 §11.2). Thin: call services, render templates."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from rag_app.domain.models import DocumentSummary, VersionStatus
from rag_app.web.context import AppContext, get_context

router = APIRouter(include_in_schema=False)
Ctx = Annotated[AppContext, Depends(get_context)]
Upload = Annotated[UploadFile, File()]
_WAITING = (VersionStatus.UPLOADED, VersionStatus.PROCESSING)


def _render(
    request: Request,
    ctx: AppContext,
    template: str,
    alert: dict[str, str] | None = None,
    **values: Any,  # noqa: ANN401  (template context)
) -> HTMLResponse:
    """Render ``template`` with the values every page needs; optionally add an OOB alert."""
    limit_mb = ctx.settings.limits.max_upload_mb
    context = {
        "request": request,
        "profile": ctx.profile,
        "max_upload_mb": limit_mb,
        "max_upload_bytes": limit_mb * 1024 * 1024,
        **values,
    }
    body = ctx.templates.get_template(template).render(context)
    if alert is not None:
        # Out-of-band swap: the confirmation lands in #alerts whatever the request targeted.
        fragment = ctx.templates.get_template("partials/alert.html").render(alert)
        body += f'<div id="alerts" hx-swap-oob="innerHTML">{fragment}</div>'
    return HTMLResponse(body)


def _library(ctx: AppContext) -> dict[str, Any]:
    documents: list[DocumentSummary] = ctx.documents.list_documents()
    return {"documents": documents, "any_processing": any(d.status in _WAITING for d in documents)}


def _redirect(url: str) -> Response:
    """Full-page navigation after an HTMX action (e.g. the document no longer exists)."""
    return Response(status_code=200, headers={"HX-Redirect": url})


# ------------------------------------------------------------------ home
@router.get("/", response_class=HTMLResponse, name="home")
def home(request: Request, ctx: Ctx) -> HTMLResponse:
    """Welcome page with the domain profile's text and example questions (FR-UI-08)."""
    documents = ctx.documents.list_documents()
    return _render(
        request,
        ctx,
        "index.html",
        section="home",
        total_documents=len(documents),
        ready_documents=sum(1 for d in documents if d.active_version is not None),
        processing_documents=sum(1 for d in documents if d.status in _WAITING),
    )


# ------------------------------------------------------------------ library
@router.get("/documents", response_class=HTMLResponse, name="documents_page")
def documents_page(request: Request, ctx: Ctx, deleted: str | None = None) -> HTMLResponse:
    """The document library: upload area and table (FR-UI-02/03)."""
    alert = {"kind": "success", "message": f"حُذف «{deleted}»."} if deleted else None
    return _render(
        request,
        ctx,
        "documents/list.html",
        section="documents",
        deleted_alert=alert,
        **_library(ctx),
    )


@router.get("/documents/_library", response_class=HTMLResponse, name="library_fragment")
def library_fragment(request: Request, ctx: Ctx) -> HTMLResponse:
    """The library table alone, for status polling."""
    return _render(request, ctx, "documents/_library.html", **_library(ctx))


@router.post("/documents", response_class=HTMLResponse, name="upload_document_ui")
def upload_document_ui(request: Request, ctx: Ctx, file: Upload) -> HTMLResponse:
    """Upload from the library page; returns the refreshed table and a confirmation."""
    detail = ctx.documents.upload_document(file.filename or "", file.file)
    alert = {"kind": "success", "message": f"رُفع «{detail.display_name}» وتجري معالجته الآن."}
    return _render(request, ctx, "documents/_library.html", alert=alert, **_library(ctx))


# ------------------------------------------------------------------ one document
@router.get("/documents/{document_id}", response_class=HTMLResponse, name="document_page")
def document_page(request: Request, ctx: Ctx, document_id: str) -> HTMLResponse:
    """Document details and version history (FR-UI-02, FR-VER)."""
    doc = ctx.documents.get_document(document_id)
    return _render(request, ctx, "documents/detail.html", section="documents", doc=doc)


@router.get(
    "/documents/{document_id}/_history", response_class=HTMLResponse, name="history_fragment"
)
def history_fragment(request: Request, ctx: Ctx, document_id: str) -> HTMLResponse:
    """The details block alone, for status polling and after actions."""
    doc = ctx.documents.get_document(document_id)
    return _render(request, ctx, "documents/_history.html", doc=doc)


@router.post(
    "/documents/{document_id}/versions", response_class=HTMLResponse, name="upload_version_ui"
)
def upload_version_ui(request: Request, ctx: Ctx, document_id: str, file: Upload) -> HTMLResponse:
    """Upload a new version from the details page."""
    info = ctx.documents.upload_version(document_id, file.filename or "", file.file)
    doc = ctx.documents.get_document(document_id)
    message = (
        f"رُفعت النسخة {info.version_number} وتجري معالجتها. تبقى النسخة الحالية معتمدة حتى تكتمل."
    )
    return _render(
        request,
        ctx,
        "documents/_history.html",
        doc=doc,
        alert={"kind": "success", "message": message},
    )


@router.post(
    "/documents/{document_id}/versions/{version_id}/activate",
    response_class=HTMLResponse,
    name="activate_version_ui",
)
def activate_version_ui(
    request: Request, ctx: Ctx, document_id: str, version_id: str
) -> HTMLResponse:
    """Make a ready version the one used for answers."""
    doc = ctx.documents.activate_version(document_id, version_id)
    number = doc.active.version_number if doc.active else ""
    message = f"اعتُمدت النسخة {number}، وستعتمد عليها الإجابات من الآن."
    return _render(
        request,
        ctx,
        "documents/_history.html",
        doc=doc,
        alert={"kind": "success", "message": message},
    )


@router.post(
    "/documents/{document_id}/versions/{version_id}/retry",
    response_class=HTMLResponse,
    name="retry_version_ui",
)
def retry_version_ui(request: Request, ctx: Ctx, document_id: str, version_id: str) -> HTMLResponse:
    """Queue a failed version again."""
    info = ctx.documents.retry_version(document_id, version_id)
    doc = ctx.documents.get_document(document_id)
    return _render(
        request,
        ctx,
        "documents/_history.html",
        doc=doc,
        alert={"kind": "info", "message": f"أُعيدت النسخة {info.version_number} إلى المعالجة."},
    )


@router.delete(
    "/documents/{document_id}/versions/{version_id}",
    response_class=HTMLResponse,
    name="delete_version_ui",
)
def delete_version_ui(request: Request, ctx: Ctx, document_id: str, version_id: str) -> Response:
    """Delete a non-active version (the whole document if it was the last one)."""
    doc = ctx.documents.get_document(document_id)
    if ctx.documents.delete_version(document_id, version_id):
        return _redirect(
            str(request.url_for("documents_page").include_query_params(deleted=doc.display_name))
        )
    return _render(
        request,
        ctx,
        "documents/_history.html",
        doc=ctx.documents.get_document(document_id),
        alert={"kind": "success", "message": "حُذفت النسخة."},
    )


@router.delete("/documents/{document_id}", name="delete_document_ui")
def delete_document_ui(request: Request, ctx: Ctx, document_id: str) -> Response:
    """Delete a document and go back to the library."""
    doc = ctx.documents.get_document(document_id)
    ctx.documents.delete_document(document_id)
    return _redirect(
        str(request.url_for("documents_page").include_query_params(deleted=doc.display_name))
    )
