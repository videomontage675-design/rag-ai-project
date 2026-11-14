-- Version numbers are never reused, even after the newest version is deleted, so an old
-- citation "version 3" can never be confused with a later upload (FR-VER-01, FR-CONV-05).
ALTER TABLE documents ADD COLUMN last_version_number INTEGER NOT NULL DEFAULT 0;

UPDATE documents
SET last_version_number = (
    SELECT COALESCE(MAX(v.version_number), 0)
    FROM document_versions v
    WHERE v.document_id = documents.id
);
