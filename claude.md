# Claude Instructions — Edge AI Latency Anomaly Detection Testbed

> Purpose: Use these instructions to guide GitHub Copilot (or any coding assistant) to generate consistent, production-like code for the graduate research project: **AI-Based Latency Anomaly Detection + Automated Mitigation** using Raspberry Pi edge agents and an AWS control plane.

## 0) Project Summary (What we are building)

We are building a small, reproducible testbed to study **reliability-focused** anomaly detection in edge networks (not security). The system detects **gray failures** (latency/jitter/loss degradations) and triggers automated mitigation.

**Architecture:** “Cloud decides, edge executes”
- **Edge nodes (Raspberry Pis):** run a lightweight probe agent that measures latency/jitter/loss + DNS + HTTP timings and publishes telemetry to the cloud.
- **AWS control plane (Ubuntu EC2):** runs MQTT broker, ingestion service, Postgres, Grafana, and the anomaly detection + mitigation controller.
- **Database:** Postgres stores raw telemetry + anomaly events + mitigation actions.
- **Visualization:** Grafana dashboards.
- **ML:** Unsupervised anomaly detection using Isolation Forest on **windowed features**.
- **Fault injection:** Use Linux `tc netem` on nodes to inject delay/jitter/loss for repeatable experiments.

## 1) Constraints and Key Decisions (Do not change unless requested)

- Sampling interval baseline: **10 seconds**
- Baseline training period: **24 hours** of normal telemetry
- Nodes: **6 Pis** total: **3 LAN (ethernet)** + **3 Wi‑Fi**
- Transport: **MQTT** (telemetry + commands), with QoS 1 for telemetry
- Postgres port **5432 should not be publicly exposed**; only local access from services on EC2
- Use simple, explainable features and operational metrics:
  - Primary evaluation: **MTTD**, **false alert rate**, and **impact reduction** after mitigation (not F1 score)

## 2) Repository Layout (proposed)

Create a monorepo with these folders:

```
.
├── edge-agent/
│   ├── agent.py
│   ├── config.py
│   ├── requirements.txt
│   ├── systemd/edge-probe.service
│   └── fault_injection/
│       ├── netem_apply.sh
│       ├── netem_clear.sh
│       └── scenarios.sh
├── control-plane/
│   ├── ingestion/
│   │   ├── app.py            # subscribes to MQTT and writes to Postgres
│   │   ├── mqtt_client.py
│   │   ├── db.py
│   │   └── requirements.txt
│   ├── detector/
│   │   ├── detector.py       # trains + scores Isolation Forest
│   │   ├── features.py       # window aggregation
│   │   ├── thresholds.py     # (optional) auto-threshold calibration
│   │   └── requirements.txt
│   ├── mitigator/
│   │   ├── controller.py     # publishes mitigation commands to MQTT
│   │   └── requirements.txt
│   └── systemd/
│       ├── ingestion.service
│       ├── detector.service
│       └── mitigator.service
├── sql/
│   ├── 001_init.sql
│   └── 002_indexes.sql
├── docs/
│   ├── mqtt_topics.md
│   ├── payload_schema.md
│   ├── experiments.md
│   └── runbook.md
└── README.md
```

## 3) Coding Standards (must follow)

- Language: **Python 3.11+** (or Ubuntu default Python 3, but code must be compatible)
- Formatting: Black-compatible style; use type hints where reasonable
- Logging: structured logs (JSON or consistent key=value), no print spam
- Error handling: timeouts everywhere; retry with backoff for MQTT reconnect
- Security posture: no public Postgres; secrets via env vars or local config files with restricted permissions

## 4) MQTT Contract (topics + payloads)

### 4.1 Telemetry publish topic
- Topic: `telemetry/<device_id>/<target_id>`
- QoS: 1
- Retain: false

### 4.2 Mitigation command topic (cloud → edge)
- Topic: `mitigation/<device_id>/command`
- QoS: 1

### 4.3 Mitigation status/ack topic (edge → cloud)
- Topic: `mitigation/<device_id>/status`
- QoS: 1

### 4.4 Telemetry JSON payload (edge → cloud)
Must be JSON, one message per probe cycle.

Example:
```json
{
  "ts": "2026-01-16T01:23:45.678Z",
  "device_id": "pi-lan-01",
  "network_type": "lan",
  "target_id": "primary",
  "interval_s": 10,
  "metrics": {
    "icmp": {"ok": true, "rtt_min_ms": 18.9, "rtt_avg_ms": 21.3, "rtt_max_ms": 27.1, "loss_pct": 0.0},
    "dns":  {"ok": true, "query": "example.com", "latency_ms": 12.4},
    "http": {"ok": true, "url": "https://primary.example.com/health", "status": 200, "latency_ms": 155.2}
  }
}
```

### 4.5 Mitigation command payload (cloud → edge)
```json
{
  "ts": "2026-01-16T01:30:00.000Z",
  "command_id": "uuid-or-ulid",
  "action": "failover_endpoint",
  "params": {
    "target_id": "backup",
    "http_url": "https://backup.example.com/health"
  }
}
```

Supported actions (minimum):
- `failover_endpoint` — switch probed HTTP URL/target
- `set_interval` — change sampling interval (e.g., 10s → 2s during anomaly)

### 4.6 Mitigation status payload (edge → cloud)
```json
{
  "ts": "2026-01-16T01:30:01.200Z",
  "command_id": "uuid-or-ulid",
  "device_id": "pi-lan-01",
  "status": "applied",
  "details": "Switched to backup endpoint"
}
```

## 5) Database (Postgres) Schema Requirements

Create SQL migrations in `/sql/`.

### 5.1 telemetry_measurements (raw)
- Insert each telemetry message (or extract key fields) with a server-side received timestamp.

Required columns (suggested):
- id (bigserial pk)
- ts (timestamptz) — timestamp from device
- received_ts (timestamptz default now())
- device_id (text)
- network_type (text)
- target_id (text)
- interval_s (int)
- icmp_rtt_min_ms, icmp_rtt_avg_ms, icmp_rtt_max_ms (double precision)
- icmp_loss_pct (double precision)
- dns_latency_ms (double precision), dns_ok (boolean)
- http_latency_ms (double precision), http_status (int), http_ok (boolean)

### 5.2 anomaly_events
- id (bigserial pk)
- event_ts (timestamptz)
- device_id, target_id
- model_version (text)
- anomaly_score (double precision)
- threshold (double precision)
- is_anomaly (boolean)
- window_start_ts, window_end_ts (timestamptz)
- features (jsonb) — optional; store feature vector for debugging

### 5.3 mitigation_actions
- id (bigserial pk)
- command_id (text unique)
- issued_ts (timestamptz)
- device_id
- action (text)
- params (jsonb)
- status (text) — issued/applied/failed/timeout
- status_ts (timestamptz)
- notes (text)

### 5.4 Indexes
Add indexes for time-series queries:
- telemetry_measurements(ts), telemetry_measurements(device_id, ts)
- anomaly_events(device_id, event_ts)
- mitigation_actions(device_id, issued_ts)

## 6) Feature Windowing (What the model sees)

We do **windowed features** (not embeddings, not RAG).

Default:
- Sample interval: 10s
- Window length: 60s (6 samples) or 120s (12 samples) — choose one and stay consistent

Compute features per (device_id, target_id, window):
- RTT mean, RTT std (jitter), RTT max
- Loss mean
- DNS latency mean + failure rate
- HTTP latency mean + p95 + error rate

Store window metadata in anomaly_events.

## 7) ML Detector Requirements

Primary model: **Isolation Forest**
- Train using baseline telemetry (first 24 hours, no injected faults).
- Score windows continuously after baseline.
- Output anomaly_score + is_anomaly decision.
- Threshold calibration: keep it simple; default use model’s contamination or percentile on baseline scores. (Auto-tuning can be a future enhancement.)

Operational metrics to compute later (for experiments):
- MTTD per incident (from fault injection start → detection time)
- false alert rate during baseline (alerts/hour)
- impact reduction after mitigation (mean/p95 latency before vs after)

## 8) Fault Injection Requirements (tc netem)

Use bash scripts in `edge-agent/fault_injection/` to apply and clear netem.

Minimum capabilities:
- Apply delay (ms) and optional jitter (ms)
- Apply packet loss (%)
- Clear qdisc cleanly
- Support selecting interface (eth0/wlan0)
- Support scoping to a destination IP (optional stretch goal)

Example interface-only delay:
```bash
sudo tc qdisc add dev eth0 root netem delay 100ms 20ms distribution normal
```

Clear:
```bash
sudo tc qdisc del dev eth0 root
```

Include a `scenarios.sh` that runs scripted experiments:
- baseline 2m
- delay 100ms for 5m
- recover 2m
- loss 2% for 3m
- recover 2m

Log start/end timestamps for each scenario (stdout JSON or CSV) so experiments have ground truth.

## 9) Agent Requirements (edge-agent)

Agent must:
- Probe ICMP ping (RTT + loss), DNS resolution time, HTTP GET latency/status
- Publish one telemetry message per interval
- Subscribe to mitigation commands and apply them:
  - update target http_url or target_id
  - adjust interval_s
- Publish mitigation status acknowledgements

Agent must be robust:
- reconnect to MQTT broker
- do not block forever; use timeouts
- minimal dependencies

Run long-term via **systemd** (no pm2).

## 10) Control Plane Services

### 10.1 Ingestion Service
- Subscribe to `telemetry/#`
- Validate payload schema (light validation)
- Write rows to telemetry_measurements
- Optionally publish basic “ingestion_ok” metrics/logs

### 10.2 Detector Service
- Periodically build feature windows from telemetry_measurements
- Score windows; write anomaly_events
- When anomaly is detected, notify mitigator (could be via DB polling or internal queue; keep simple)

### 10.3 Mitigator Service
- Decide mitigation policy:
  - If anomaly for device persists N windows, issue command
  - Prefer failover endpoint first; optionally increase sampling interval during anomalies
- Publish mitigation commands to `mitigation/<device_id>/command`
- Listen for `mitigation/+/status` and update mitigation_actions

## 11) Docs that Copilot should generate (required)

- `docs/mqtt_topics.md` — topics + payload examples
- `docs/experiments.md` — baseline run + netem scenarios + expected outcomes
- `docs/runbook.md` — how to run services, check logs, and recover

## 12) Acceptance Criteria (definition of done)

Minimum viable end-to-end:
1. Edge agent publishes telemetry to MQTT reliably
2. Ingestion service stores telemetry in Postgres
3. Grafana can visualize latency metrics from Postgres
4. Detector trains on baseline and flags injected anomalies
5. Mitigator issues a failover or sampling-rate command and the agent applies it
6. Fault injection scripts produce repeatable incidents with logged timestamps

## 13) Non-Goals (keep scope reasonable)

- No embeddings, no vector databases, no RAG
- No deep time-series forecasting (LSTM/Transformers) for baseline project
- No public exposure of Postgres
- No complex distributed Kafka setup

---

## Quick Start Notes (for Copilot to generate later)

- Use environment variables for config:
  - MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS
  - DB_HOST (localhost), DB_PORT (5432), DB_NAME (telemetry), DB_USER (telemetry_user), DB_PASS (change_me_now)
- Use a `.env.example` file for each component.
- Provide systemd unit files for long running services.

information about the nodes can be found in `nodes/nodes.md`, example `kingnathanal@pi00-wifi`.

the control plane runs on an Ubuntu EC2 instance and the edge agents run on Raspberry Pi devices.

the control plane can be accessed via `ubuntu@ec2`