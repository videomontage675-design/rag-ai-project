"""Domain vocabulary (DESIGN-001 §5–§6): closed value sets and immutable value objects."""

from dataclasses import dataclass
from enum import StrEnum


class VersionStatus(StrEnum):
    """Lifecycle status of a document version (DESIGN-001 §6)."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"


class DocumentFormat(StrEnum):
    """Supported upload formats (D-003)."""

    PDF = "pdf"
    MARKDOWN = "markdown"


class AnswerOutcome(StrEnum):
    """Outcome of answering a question (FR-VAL-05)."""

    ANSWERED = "answered"
    ANSWERED_UNVERIFIED = "answered_unverified"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    ERROR = "error"


class ProcessingStage(StrEnum):
    """Stage shown to the user while a version is processed (FR-ING-02)."""

    VALIDATING = "validating"
    EXTRACTING = "extracting"
    CLEANING = "cleaning"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"


class BlockKind(StrEnum):
    """Smallest structural unit of extracted text; chunking never splits one unless too long."""

    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE_ROW = "table_row"


@dataclass(frozen=True, slots=True)
class Block:
    """A paragraph, list item, or table row with the headings it sits under."""

    text: str
    kind: BlockKind
    heading_path: tuple[str, ...]
    page: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """Output of extraction + cleaning: ordered blocks and, for PDFs, the page count."""

    blocks: tuple[Block, ...]
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk ready to be stored (DESIGN-001 §5).

    ``text_original`` is shown to the user; ``text_normalized`` is used for search.
    """

    seq: int
    heading_path: str
    text_original: str
    text_normalized: str
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
