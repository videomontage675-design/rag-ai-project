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


class EmbeddingTask(StrEnum):
    """What a text is embedded for; asymmetric models encode passages and questions differently."""

    DOCUMENT = "document"
    QUERY = "query"


class JobStatus(StrEnum):
    """Status of an ingestion job (DESIGN-001 §5)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """One version in a document's history (DESIGN-001 §11.1 ``VersionInfo``)."""

    id: str
    version_number: int
    status: VersionStatus
    stage: ProcessingStage | None
    is_active: bool
    original_filename: str
    format: DocumentFormat
    size_bytes: int
    page_count: int | None
    chunk_count: int | None
    error_code: str | None
    error_message: str | None
    uploaded_at: str
    processing_finished_at: str | None


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    """One row of the document list (``DocumentSummary``).

    ``status``, ``format`` and ``size_bytes`` describe the newest version, which is what the
    user is waiting for after an upload; ``active_version`` is the one used for answers.
    """

    id: str
    display_name: str
    active_version: int | None
    latest_version: int
    versions: int
    status: VersionStatus
    stage: ProcessingStage | None
    format: DocumentFormat
    size_bytes: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class DocumentDetail:
    """A document with its full version history, newest first (``DocumentDetail``)."""

    id: str
    display_name: str
    active_version_id: str | None
    created_at: str
    updated_at: str
    versions: tuple[VersionInfo, ...]

    @property
    def active(self) -> VersionInfo | None:
        """The version currently used for answers, if any."""
        return next((v for v in self.versions if v.is_active), None)

    @property
    def is_processing(self) -> bool:
        """True while any version waits for or undergoes processing (drives UI polling)."""
        return any(
            v.status in (VersionStatus.UPLOADED, VersionStatus.PROCESSING) for v in self.versions
        )


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """An ingestion job claimed by the worker, with what it needs to process the file."""

    job_id: str
    version_id: str
    document_id: str
    stored_name: str
    format: DocumentFormat
    attempts: int
