-- 002_indexes.sql
-- Indexes for time-series queries.

-- telemetry_measurements
CREATE INDEX IF NOT EXISTS idx_telemetry_ts
    ON telemetry_measurements (ts);

CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts
    ON telemetry_measurements (device_id, ts);

-- anomaly_events
CREATE INDEX IF NOT EXISTS idx_anomaly_device_event_ts
    ON anomaly_events (device_id, event_ts);

-- mitigation_actions
CREATE INDEX IF NOT EXISTS idx_mitigation_device_issued_ts
    ON mitigation_actions (device_id, issued_ts);
