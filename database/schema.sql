-- KubeSherlock investigation history schema
-- All objects live in the dedicated "kubesherlock" schema, not "public".
-- This isolates KubeSherlock from other applications sharing the same database
-- and allows clean revocation: REVOKE ALL ON SCHEMA public FROM kubesherlock_role.

-- ── Schema ────────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS kubesherlock;

-- ── Tables ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kubesherlock.investigations (
    id               SERIAL PRIMARY KEY,
    question         TEXT          NOT NULL,
    namespace        VARCHAR(255),
    resource_name    VARCHAR(255),
    root_cause       TEXT,
    recommendations  TEXT,
    answer           TEXT,                   -- populated by update_investigation() after the LLM completes
    provider         VARCHAR(50),
    iterations       INT,
    tool_calls_count INT,
    duration_seconds FLOAT,
    status           VARCHAR(50),
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kubesherlock.investigation_findings (
    id               SERIAL PRIMARY KEY,
    investigation_id INT NOT NULL REFERENCES kubesherlock.investigations(id) ON DELETE CASCADE,
    finding_type     VARCHAR(100),
    severity         VARCHAR(50),
    content          TEXT NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kubesherlock.investigation_tool_calls (
    id               SERIAL PRIMARY KEY,
    investigation_id INT NOT NULL REFERENCES kubesherlock.investigations(id) ON DELETE CASCADE,
    tool_name        VARCHAR(255) NOT NULL,
    arguments        JSONB,
    result_summary   TEXT,
    execution_time_ms INT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kubesherlock.metrics (
    id           SERIAL PRIMARY KEY,
    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metric_name  VARCHAR(255) NOT NULL,
    metric_value FLOAT        NOT NULL,
    labels       JSONB
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_investigations_namespace  ON kubesherlock.investigations(namespace);
CREATE INDEX IF NOT EXISTS idx_investigations_resource   ON kubesherlock.investigations(resource_name);
CREATE INDEX IF NOT EXISTS idx_investigations_created_at ON kubesherlock.investigations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_type             ON kubesherlock.investigation_findings(finding_type);
CREATE INDEX IF NOT EXISTS idx_tool_calls_investigation  ON kubesherlock.investigation_tool_calls(investigation_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name           ON kubesherlock.investigation_tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_metric_name               ON kubesherlock.metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metric_timestamp          ON kubesherlock.metrics(timestamp);
