-- ============================================
-- LAB 04: Идемпотентность платежных запросов
-- ============================================

CREATE TABLE idempotency_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    idempotency_key VARCHAR(255) NOT NULL,
    request_method VARCHAR(16) NOT NULL,
    request_path TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'processing',
    status_code INTEGER,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT idempotency_status_check CHECK (status IN ('processing', 'completed', 'failed')),
    CONSTRAINT idempotency_unique_key UNIQUE (idempotency_key, request_method, request_path)
);

CREATE INDEX idx_idempotency_keys_expires_at ON idempotency_keys (expires_at);
CREATE INDEX idx_idempotency_keys_key ON idempotency_keys (idempotency_key);
CREATE INDEX idx_idempotency_keys_lookup ON idempotency_keys (idempotency_key, request_method, request_path);

-- TODO (опционально):
-- триггер автообновления updated_at
CREATE OR REPLACE FUNCTION log_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END; 
$$ language plpgsql;

CREATE TRIGGER trigger_log_updated_at
BEFORE UPDATE ON idempotency_keys
FOR EACH ROW
EXECUTE FUNCTION log_updated_at();


