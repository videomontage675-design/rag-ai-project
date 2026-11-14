"""Arabic display helpers registered as Jinja filters: labels, counts, sizes, and dates."""

from __future__ import annotations

from datetime import datetime

from jinja2 import Environment

STATUS_LABELS = {
    "uploaded": "بانتظار المعالجة",
    "processing": "قيد المعالجة",
    "ready": "جاهز",
    "failed": "تعذّرت المعالجة",
    "deleting": "يجري الحذف",
}
STAGE_LABELS = {
    "validating": "التحقق من الملف",
    "extracting": "استخراج النص",
    "cleaning": "تنظيف النص",
    "chunking": "تقسيم النص إلى مقاطع",
    "embedding": "توليد التمثيلات الدلالية",
    "indexing": "الحفظ في المكتبة",
}
FORMAT_LABELS = {"pdf": "PDF", "markdown": "Markdown"}
_MONTHS = (
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
)  # fmt: skip


def arabic_count(n: int, one: str, two: str, few: str, many: str) -> str:
    """Count phrase following Arabic number agreement (1, 2, 3–10, 11+)."""
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n % 100 <= 10:
        return f"{n} {few}"
    return f"{n} {many}"


def filesize(size: int) -> str:
    """Human-readable size in Arabic units (1 KB = 1024 bytes, as Windows shows it)."""
    if size < 1024:
        return f"{size} بايت"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} كيلوبايت"
    return f"{size / (1024 * 1024):.1f} ميجابايت"


def datetime_ar(value: str) -> str:
    """Format a stored UTC timestamp in the machine's local time: ``14 نوفمبر 2026، 20:45``."""
    try:
        moment = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return value
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}، {moment:%H:%M}"


def register(env: Environment) -> None:
    """Add the display filters to a Jinja environment."""
    env.filters.update(
        status_label=lambda s: STATUS_LABELS.get(str(s), str(s)),
        stage_label=lambda s: STAGE_LABELS.get(str(s), str(s)),
        format_label=lambda s: FORMAT_LABELS.get(str(s), str(s)),
        filesize=filesize,
        datetime_ar=datetime_ar,
        documents_count_label=lambda n: arabic_count(
            n, "مستند واحد", "مستندان", "مستندات", "مستنداً"
        ),
        documents_ready_label=lambda n: (
            "لا توجد مستندات جاهزة بعد"
            if n == 0
            else arabic_count(n, "مستند جاهز", "مستندان جاهزان", "مستندات جاهزة", "مستنداً جاهزاً")
            .removeprefix(str(n))
            .strip()
        ),
        documents_processing_label=lambda n: arabic_count(
            n,
            "مستند قيد المعالجة",
            "مستندان قيد المعالجة",
            "مستندات قيد المعالجة",
            "مستنداً قيد المعالجة",
        ),
    )
