-- PostgreSQL 16 Multi-Tenant Row-Level Security (RLS) & Immutable WORM Append-Only Trigger
-- AeroRegu Evidence Layer (Block 2 Enterprise Cluster Initialization)

CREATE TABLE IF NOT EXISTS ledger_events (
    seq BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    prev_hash TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ledger_events_tenant_seq
    ON ledger_events (tenant_id, seq);

CREATE INDEX IF NOT EXISTS idx_ledger_events_tenant_hash
    ON ledger_events (tenant_id, event_hash);

-- Strict Multi-Tenant Row-Level Security
ALTER TABLE ledger_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ledger_tenant_isolation ON ledger_events;
CREATE POLICY ledger_tenant_isolation ON ledger_events
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

-- Strict Append-Only WORM Trigger (blocks UPDATE/DELETE across all roles)
CREATE OR REPLACE FUNCTION prevent_ledger_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'ledger_events is WORM append-only: % is prohibited', TG_OP
        USING ERRCODE = '42501';
END;
$$;

DROP TRIGGER IF EXISTS trg_ledger_events_worm ON ledger_events;
CREATE TRIGGER trg_ledger_events_worm
    BEFORE UPDATE OR DELETE ON ledger_events
    FOR EACH ROW
    EXECUTE FUNCTION prevent_ledger_mutation();
