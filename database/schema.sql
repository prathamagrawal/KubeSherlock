-- KubeSherlock investigation history schema
-- Stores investigations, findings, and metrics for historical analysis and learning

CREATE TABLE IF NOT EXISTS investigations (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    namespace VARCHAR(255),
    resource_name VARCHAR(255),
    root_cause TEXT,
    recommendations TEXT,
    answer TEXT NOT NULL,
    provider VARCHAR(50),
    iterations INT,
    tool_calls_count INT,
    duration_seconds FLOAT,
    status VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investigation_findings (
    id SERIAL PRIMARY KEY,
    investigation_id INT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    finding_type VARCHAR(100),
    severity VARCHAR(50),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investigation_tool_calls (
    id SERIAL PRIMARY KEY,
    investigation_id INT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    tool_name VARCHAR(255) NOT NULL,
    arguments JSONB,
    result_summary TEXT,
    execution_time_ms INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metrics (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metric_name VARCHAR(255) NOT NULL,
    metric_value FLOAT NOT NULL,
    labels JSONB,
    INDEX idx_metric_name (metric_name),
    INDEX idx_timestamp (timestamp)
);

-- Indexes for common queries
CREATE INDEX idx_investigations_namespace ON investigations(namespace);
CREATE INDEX idx_investigations_resource ON investigations(resource_name);
CREATE INDEX idx_investigations_created_at ON investigations(created_at DESC);
CREATE INDEX idx_findings_type ON investigation_findings(finding_type);
CREATE INDEX idx_tool_calls_investigation ON investigation_tool_calls(investigation_id);
CREATE INDEX idx_tool_calls_name ON investigation_tool_calls(tool_name);
