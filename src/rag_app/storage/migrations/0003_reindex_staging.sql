-- 0003_reindex_staging: vectors computed by `rag reindex` before they replace the live ones
-- (DESIGN-001 §7.4, FR-CFG-05). Each batch is committed here as soon as it is embedded, so an
-- interrupted re-index resumes without spending the provider quota again, and the live index
-- stays untouched until one final transaction swaps everything in.

CREATE TABLE reindex_staging (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL CHECK (dim > 0),
    vector   BLOB NOT NULL CHECK (length(vector) = dim * 4)
) WITHOUT ROWID;

-- Re-indexing and consistency checks look up vectors by model.
CREATE INDEX ix_chunk_embeddings_model ON chunk_embeddings(model);
