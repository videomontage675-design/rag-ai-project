-- 0001_init: initial schema (DESIGN-001 §5, approved D-030).
-- Indexes follow the actual query patterns; see the comment above each one.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE documents (
    id                TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    active_version_id TEXT REFERENCES document_versions(id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE document_versions (
    id                     TEXT PRIMARY KEY,
    document_id            TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number         INTEGER NOT NULL CHECK (version_number >= 1),
    original_filename      TEXT NOT NULL,
    format                 TEXT NOT NULL CHECK (format IN ('pdf', 'markdown')),
    size_bytes             INTEGER NOT NULL CHECK (size_bytes > 0),
    content_hash           TEXT NOT NULL,
    stored_name            TEXT NOT NULL,
    status                 TEXT NOT NULL
        CHECK (status IN ('uploaded', 'processing', 'ready', 'failed', 'deleting')),
    stage                  TEXT,
    error_code             TEXT,
    error_message_ar       TEXT,
    page_count             INTEGER,
    chunk_count            INTEGER,
    embedding_model        TEXT,
    embedding_dim          INTEGER,
    uploaded_at            TEXT NOT NULL,
    processing_started_at  TEXT,
    processing_finished_at TEXT
);

-- Version history of a document, in order; also enforces unique version numbers.
CREATE UNIQUE INDEX ux_versions_document_number ON document_versions(document_id, version_number);
-- Duplicate detection across all versions (FR-DOC-04): an O(log n) lookup per upload.
CREATE UNIQUE INDEX ux_versions_content_hash ON document_versions(content_hash);
-- Status counts and recovery of interrupted processing at start-up (FR-ING-14).
CREATE INDEX ix_versions_status ON document_versions(status);

CREATE TABLE chunks (
    id              TEXT PRIMARY KEY,
    version_id      TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    heading_path    TEXT NOT NULL DEFAULT '',
    text_original   TEXT NOT NULL,
    text_normalized TEXT NOT NULL,
    page_start      INTEGER,
    page_end        INTEGER,
    char_start      INTEGER NOT NULL,
    char_end        INTEGER NOT NULL CHECK (char_end >= char_start)
);

-- Loading the active vectors joins chunks by version; also orders chunks within a version
-- and makes ON DELETE CASCADE from versions cheap.
CREATE UNIQUE INDEX ux_chunks_version_seq ON chunks(version_id, seq);

CREATE TABLE chunk_embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL CHECK (dim > 0),
    vector   BLOB NOT NULL CHECK (length(vector) = dim * 4)
) WITHOUT ROWID;

CREATE TABLE ingestion_jobs (
    id          TEXT PRIMARY KEY,
    version_id  TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('ingest', 'reindex')),
    status      TEXT NOT NULL
        CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    error_code  TEXT
);

-- The worker claims the oldest queued job: served directly by this index.
CREATE INDEX ix_jobs_status_created ON ingestion_jobs(status, created_at);
CREATE INDEX ix_jobs_version ON ingestion_jobs(version_id);

CREATE TABLE conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Conversation list, newest first (FR-CONV-03).
CREATE INDEX ix_conversations_updated ON conversations(updated_at DESC);

CREATE TABLE messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL,
    question         TEXT NOT NULL,
    answer           TEXT,
    outcome          TEXT NOT NULL
        CHECK (outcome IN ('answered', 'answered_unverified', 'insufficient_information', 'error')),
    error_code       TEXT,
    prompt_version   TEXT,
    generation_model TEXT,
    embedding_model  TEXT,
    latency_ms       INTEGER,
    created_at       TEXT NOT NULL
);

-- Messages of a conversation in order; also enforces unique sequence numbers.
CREATE UNIQUE INDEX ux_messages_conversation_seq ON messages(conversation_id, seq);

CREATE TABLE citations (
    id             TEXT PRIMARY KEY,
    message_id     TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    label          TEXT NOT NULL,
    chunk_id       TEXT REFERENCES chunks(id) ON DELETE SET NULL,
    document_id    TEXT,
    document_name  TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    location       TEXT NOT NULL,
    cited_text     TEXT NOT NULL
);

-- Sources of a message; chunk_id index keeps ON DELETE SET NULL from scanning all citations.
CREATE INDEX ix_citations_message ON citations(message_id);
CREATE INDEX ix_citations_chunk ON citations(chunk_id);

-- The only rows retrieval may see (FR-RET-04, FR-VER-02): ready, active versions.
CREATE VIEW active_chunk_vectors AS
SELECT c.id AS chunk_id, c.version_id, v.document_id, e.model, e.dim, e.vector
FROM documents d
JOIN document_versions v ON v.id = d.active_version_id AND v.status = 'ready'
JOIN chunks c ON c.version_id = v.id
JOIN chunk_embeddings e ON e.chunk_id = c.id;

INSERT INTO meta (key, value) VALUES
    ('index_generation', '0'),
    ('index_embedding_model', ''),
    ('index_embedding_dim', '0');
