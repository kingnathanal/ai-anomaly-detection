-- 001_init.sql
-- Creates the core tables for the anomaly detection testbed.

-- ── telemetry_measurements ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS telemetry_measurements (
    id              BIGSERIAL       PRIMARY KEY,
    ts              TIMESTAMPTZ     NOT NULL,
    received_ts     TIMESTAMPTZ     NOT NULL DEFAULT now(),
    device_id       TEXT            NOT NULL,
    network_type    TEXT            NOT NULL,
    target_id       TEXT            NOT NULL,
    interval_s      INT             NOT NULL,
    icmp_ok         BOOLEAN,
    icmp_rtt_min_ms DOUBLE PRECISION,
    icmp_rtt_avg_ms DOUBLE PRECISION,
    icmp_rtt_max_ms DOUBLE PRECISION,
    icmp_loss_pct   DOUBLE PRECISION,
    dns_ok          BOOLEAN,
    dns_latency_ms  DOUBLE PRECISION,
    http_ok         BOOLEAN,
    http_latency_ms DOUBLE PRECISION,
    http_status     INT,
    http_url        TEXT
);

-- ── anomaly_events ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS anomaly_events (
    id              BIGSERIAL       PRIMARY KEY,
    event_ts        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    device_id       TEXT            NOT NULL,
    target_id       TEXT            NOT NULL,
    model_version   TEXT            NOT NULL,
    anomaly_score   DOUBLE PRECISION NOT NULL,
    threshold       DOUBLE PRECISION NOT NULL,
    is_anomaly      BOOLEAN          NOT NULL,
    window_start_ts TIMESTAMPTZ     NOT NULL,
    window_end_ts   TIMESTAMPTZ     NOT NULL,
    features        JSONB
);

-- ── mitigation_actions ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mitigation_actions (
    id              BIGSERIAL       PRIMARY KEY,
    command_id      TEXT            NOT NULL UNIQUE,
    issued_ts       TIMESTAMPTZ     NOT NULL DEFAULT now(),
    device_id       TEXT            NOT NULL,
    action          TEXT            NOT NULL,
    params          JSONB,
    status          TEXT            NOT NULL DEFAULT 'issued',
    status_ts       TIMESTAMPTZ,
    notes           TEXT
);
