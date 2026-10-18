-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Incident runbooks table
CREATE TABLE IF NOT EXISTS runbooks (
    id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    service VARCHAR(128) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    symptoms TEXT NOT NULL,
    root_causes TEXT[] DEFAULT '{}',
    diagnostic_steps JSONB NOT NULL DEFAULT '[]',
    remediation_steps JSONB NOT NULL DEFAULT '[]',
    risk_level VARCHAR(32) NOT NULL DEFAULT 'MEDIUM', -- LOW, MEDIUM, CRITICAL
    requires_approval BOOLEAN NOT NULL DEFAULT true,
    embedding vector(1536),
    search_vector tsvector,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Full-Text Search (BM25-style tsvector) GIN Index
CREATE INDEX IF NOT EXISTS idx_runbooks_search_vector ON runbooks USING GIN(search_vector);

-- Vector Cosine Similarity HNSW Index
CREATE INDEX IF NOT EXISTS idx_runbooks_embedding ON runbooks USING hnsw (embedding vector_cosine_ops);

-- Automated trigger to maintain search_vector
CREATE OR REPLACE FUNCTION runbooks_tsvector_trigger() RETURNS trigger AS $$
BEGIN
  new.search_vector :=
    setweight(to_tsvector('english', coalesce(new.title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(new.service, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(new.symptoms, '')), 'C');
  return new;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tsvectorupdate ON runbooks;
CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
ON runbooks FOR EACH ROW EXECUTE FUNCTION runbooks_tsvector_trigger();

-- Checkpointing table for LangGraph PostgresSaver
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(128) NOT NULL,
    parent_checkpoint_id VARCHAR(128),
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_langgraph_checkpoints_thread 
ON langgraph_checkpoints(thread_id, checkpoint_id DESC);
