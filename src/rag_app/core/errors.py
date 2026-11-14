"""Typed application errors with a single catalog of HTTP statuses and Arabic messages.

Every expected failure is raised as :class:`AppError` with a stable :class:`ErrorCode`.
The web layer turns it into an HTTP response; the CLI prints it. Keeping all user-facing
Arabic messages here means they are reviewed and translated in one place (STD-001 §7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable error identifiers; part of the public API contract (DESIGN-001 §13.1)."""

    # Configuration and environment
    CONFIG_INVALID = "CONFIG_INVALID"
    POPPLER_MISSING = "POPPLER_MISSING"
    # Generic request errors
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Documents and versions
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    EMPTY_FILE = "EMPTY_FILE"
    INVALID_UTF8 = "INVALID_UTF8"
    DUPLICATE_CONTENT = "DUPLICATE_CONTENT"
    PDF_NO_TEXT = "PDF_NO_TEXT"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    PDF_CORRUPT = "PDF_CORRUPT"
    EXTRACTION_TIMEOUT = "EXTRACTION_TIMEOUT"
    VERSION_IS_ACTIVE = "VERSION_IS_ACTIVE"
    VERSION_NOT_READY = "VERSION_NOT_READY"
    VERSION_NOT_FAILED = "VERSION_NOT_FAILED"
    # Questions and answers
    QUESTION_INVALID = "QUESTION_INVALID"
    REINDEX_REQUIRED = "REINDEX_REQUIRED"
    # Providers
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_AUTH = "PROVIDER_AUTH"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """How an error code is presented: HTTP status and Arabic message template."""

    http_status: int
    message_ar: str


CATALOG: Mapping[ErrorCode, ErrorSpec] = {
    ErrorCode.CONFIG_INVALID: ErrorSpec(500, "إعدادات التطبيق غير صالحة: {reason}"),
    ErrorCode.POPPLER_MISSING: ErrorSpec(
        500, "أداة استخراج نص PDF غير مثبتة. راجع تعليمات التثبيت."
    ),
    ErrorCode.NOT_FOUND: ErrorSpec(404, "العنصر المطلوب غير موجود."),
    ErrorCode.VALIDATION_ERROR: ErrorSpec(400, "البيانات المرسلة غير صالحة."),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(500, "حدث خطأ غير متوقع. حاول مرة أخرى."),
    ErrorCode.FILE_TOO_LARGE: ErrorSpec(
        413, "حجم الملف يتجاوز الحد المسموح ({limit_mb} ميجابايت)."
    ),
    ErrorCode.UNSUPPORTED_TYPE: ErrorSpec(
        400, "نوع الملف غير مدعوم. الصيغ المدعومة: PDF نصي وMarkdown."
    ),
    ErrorCode.EMPTY_FILE: ErrorSpec(400, "الملف فارغ."),
    ErrorCode.INVALID_UTF8: ErrorSpec(400, "ملف Markdown ليس بترميز UTF-8 صالح."),
    ErrorCode.DUPLICATE_CONTENT: ErrorSpec(
        409, "هذا الملف مطابق لمحتوى موجود مسبقاً: «{document}» (النسخة {version})."
    ),
    ErrorCode.PDF_NO_TEXT: ErrorSpec(
        422, "لا يحتوي ملف PDF على نص قابل للاستخراج؛ الملفات الممسوحة ضوئياً غير مدعومة."
    ),
    ErrorCode.PDF_ENCRYPTED: ErrorSpec(422, "ملف PDF محمي بكلمة مرور ولا يمكن معالجته."),
    ErrorCode.PDF_CORRUPT: ErrorSpec(422, "ملف PDF تالف أو لا يمكن قراءته."),
    ErrorCode.EXTRACTION_TIMEOUT: ErrorSpec(422, "استغرق استخراج النص وقتاً أطول من المسموح."),
    ErrorCode.VERSION_IS_ACTIVE: ErrorSpec(
        409, "لا يمكن حذف النسخة النشطة. فعّل نسخة أخرى أو احذف المستند كاملاً."
    ),
    ErrorCode.VERSION_NOT_READY: ErrorSpec(409, "لا يمكن تفعيل نسخة لم تكتمل معالجتها."),
    ErrorCode.VERSION_NOT_FAILED: ErrorSpec(409, "إعادة المحاولة متاحة للنسخ الفاشلة فقط."),
    ErrorCode.QUESTION_INVALID: ErrorSpec(400, "يرجى كتابة سؤال لا يتجاوز {max_chars} حرف."),
    ErrorCode.REINDEX_REQUIRED: ErrorSpec(
        503, "تغيّر نموذج التمثيلات الدلالية؛ يلزم إعادة الفهرسة قبل طرح الأسئلة."
    ),
    ErrorCode.PROVIDER_RATE_LIMITED: ErrorSpec(
        429, "تم بلوغ حد الاستخدام لدى مزود النموذج. حاول بعد قليل."
    ),
    ErrorCode.PROVIDER_UNAVAILABLE: ErrorSpec(503, "خدمة النموذج غير متاحة حالياً. حاول لاحقاً."),
    ErrorCode.PROVIDER_AUTH: ErrorSpec(502, "مفتاح مزود النموذج غير صالح. راجع الإعدادات."),
}


class AppError(Exception):
    """An expected, user-explainable failure identified by an :class:`ErrorCode`.

    Args:
        code: The stable error identifier.
        details: Machine-readable context returned to API clients (never secrets).
        **params: Values for placeholders in the catalog message, e.g. ``limit_mb=10``.
    """

    def __init__(
        self,
        code: ErrorCode,
        *,
        details: Mapping[str, object] | None = None,
        **params: object,
    ) -> None:
        """Create the error; the message is rendered lazily from the catalog."""
        self.code = code
        self.details: dict[str, object] = dict(details or {})
        self.params = params
        super().__init__(f"{code}: {self.message_ar}")

    @property
    def http_status(self) -> int:
        """HTTP status the web layer should use for this error."""
        return CATALOG[self.code].http_status

    @property
    def message_ar(self) -> str:
        """The Arabic message shown to the user, with placeholders filled in."""
        template = CATALOG[self.code].message_ar
        try:
            return template.format(**self.params)
        except (KeyError, IndexError):
            # A missing placeholder must never hide the original error.
            return template
