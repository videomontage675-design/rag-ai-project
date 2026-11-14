"""Document library endpoints (DESIGN-001 §11.1). Thin: validate input, call the service."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from rag_app.web.api.schemas import DocumentDetailOut, DocumentSummaryOut, VersionOut
from rag_app.web.context import AppContext, get_context

router = APIRouter(prefix="/documents", tags=["documents"])
Ctx = Annotated[AppContext, Depends(get_context)]
Upload = Annotated[UploadFile, File(description="A text PDF or a UTF-8 Markdown file")]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def upload_document(ctx: Ctx, file: Upload) -> DocumentDetailOut:
    """Upload a new document. Processing continues in the background (poll the details)."""
    return DocumentDetailOut.of(ctx.documents.upload_document(file.filename or "", file.file))


@router.get("")
def list_documents(ctx: Ctx) -> list[DocumentSummaryOut]:
    """All documents, most recently updated first."""
    return [DocumentSummaryOut.of(d) for d in ctx.documents.list_documents()]


@router.get("/{document_id}")
def get_document(ctx: Ctx, document_id: str) -> DocumentDetailOut:
    """A document with its version history."""
    return DocumentDetailOut.of(ctx.documents.get_document(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(ctx: Ctx, document_id: str) -> Response:
    """Delete a document and all its versions; a version being processed is cancelled."""
    ctx.documents.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{document_id}/versions", status_code=status.HTTP_202_ACCEPTED)
def upload_version(ctx: Ctx, document_id: str, file: Upload) -> VersionOut:
    """Upload a new version; the current version stays active until the new one is ready."""
    return VersionOut.of(ctx.documents.upload_version(document_id, file.filename or "", file.file))


@router.post("/{document_id}/versions/{version_id}/activate")
def activate_version(ctx: Ctx, document_id: str, version_id: str) -> DocumentDetailOut:
    """Make a ready version the one used for answers."""
    return DocumentDetailOut.of(ctx.documents.activate_version(document_id, version_id))


@router.delete("/{document_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(ctx: Ctx, document_id: str, version_id: str) -> Response:
    """Delete a version that is not active (deleting the last one deletes the document)."""
    ctx.documents.delete_version(document_id, version_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{document_id}/versions/{version_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_version(ctx: Ctx, document_id: str, version_id: str) -> VersionOut:
    """Queue a failed version for processing again."""
    return VersionOut.of(ctx.documents.retry_version(document_id, version_id))
