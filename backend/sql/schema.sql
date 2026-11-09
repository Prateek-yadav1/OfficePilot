-- OfficePilot document retrieval schema.
-- Embeddings from all-MiniLM-L6-v2 have 384 dimensions.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS office_documents (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT,
    client TEXT NOT NULL,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Existing unscoped rows remain NULL and are intentionally not retrievable.
ALTER TABLE office_documents
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

-- Replace the previous cross-tenant uniqueness rule without deleting rows.
DROP INDEX IF EXISTS idx_office_documents_client_title;

CREATE UNIQUE INDEX IF NOT EXISTS idx_office_documents_tenant_client_title
    ON office_documents (tenant_id, client, title);

CREATE INDEX IF NOT EXISTS idx_office_documents_tenant_client
    ON office_documents (tenant_id, client);

ALTER TABLE office_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE office_documents FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS office_documents_tenant_isolation
    ON office_documents;

CREATE POLICY office_documents_tenant_isolation
    ON office_documents
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')
    );
