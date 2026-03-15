# AI-Based Latency Anomaly Detection & Automated Mitigation

A graduate research testbed for studying **reliability-focused anomaly detection** in edge networks using Raspberry Pi edge agents and an AWS control plane.

## Architecture

**"Cloud decides, edge executes"**

- **6 Raspberry Pi edge nodes** (3 LAN + 3 Wi-Fi) run a lightweight probe agent that measures ICMP RTT/loss, DNS resolution, and HTTP latency, publishing telemetry via MQTT.
- **AWS EC2 primary control plane** (`ubuntu@ec2` — 54.198.26.122) runs the MQTT broker, ingestion service, Postgres, Grafana, and the anomaly detection + mitigation controller.
- **AWS EC2 failover endpoint** (`ubuntu@failover` — 34.226.196.133) runs only the health app (port 8080). Provides a completely separate backup target so that after mitigator triggers failover, HTTP traffic leaves the primary EC2 entirely — enabling clean impact reduction measurement.
- **Isolation Forest** model detects gray failures (latency/jitter/loss degradations) on windowed features.
- **Automated mitigation** triggers endpoint failover and sampling rate adjustments.

### Infrastructure

| Role | Host | IP | Services |
|------|------|----|----------|
| Primary control plane | `ubuntu@ec2` | 54.198.26.122 | Mosquitto, Ingestion, Detector, EMA-Detector, Mitigator, Health :8080, Grafana :3000, Postgres :5432 |
| Failover endpoint | `ubuntu@failover` | 34.226.196.133 | Health :8080 |

## Nodes

| Node      | IP             | Type |
|-----------|----------------|------|
| pi00-wifi | 192.168.1.126  | wifi |
| pi01-wifi | 192.168.1.135  | wifi |
| pi02-wifi | 192.168.1.138  | wifi |
| pi03-lan  | 192.168.1.134  | lan  |
| pi04-lan  | 192.168.1.136  | lan  |
| pi05-lan  | 192.168.1.137  | lan  |

## Repository Structure

```
edge-agent/             # Runs on each Raspberry Pi
  agent.py              # Probe agent (ICMP/DNS/HTTP → MQTT)
  config.py             # Env-var configuration
  fault_injection/      # tc netem scripts for experiments
  systemd/              # edge-probe.service

control-plane/          # Runs on EC2
  ingestion/            # MQTT → Postgres
  detector/             # Isolation Forest anomaly detection
  mitigator/            # Mitigation command controller
  systemd/              # Service unit files

sql/                    # Postgres schema migrations
docs/                   # MQTT topics, experiments, runbook
nodes/                  # Pi inventory and setup scripts
```

## Quick Start

### Prerequisites

- Raspberry Pis set up with `nodes/setup-rpi.sh`
- EC2 instance with Mosquitto, Postgres, Grafana

### Edge Agent (each Pi)

```bash
# Copy files to /opt/edge-agent
cp edge-agent/*.py /opt/edge-agent/
cp edge-agent/.env.example /opt/edge-agent/.env
# Edit .env with correct DEVICE_ID, NETWORK_TYPE, MQTT_HOST

# Install service
sudo cp edge-agent/systemd/edge-probe.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now edge-probe
```

### Control Plane (EC2)

```bash
# Initialize database
sudo -u postgres psql -d telemetry -f sql/001_init.sql
sudo -u postgres psql -d telemetry -f sql/002_indexes.sql

# Set up Python venv
python3 -m venv /opt/control-plane/venv
/opt/control-plane/venv/bin/pip install -r control-plane/ingestion/requirements.txt
/opt/control-plane/venv/bin/pip install -r control-plane/detector/requirements.txt
/opt/control-plane/venv/bin/pip install -r control-plane/mitigator/requirements.txt

# Copy services and .env files, then:
sudo systemctl enable --now ingestion detector mitigator
```

### Run an Experiment

```bash
ssh kingnathanal@pi03-lan
sudo bash /opt/edge-agent/fault_injection/scenarios.sh eth0
```

## Documentation

- [MQTT Topics & Payloads](docs/mqtt_topics.md)
- [Payload Schema](docs/payload_schema.md)
- [Experiments](docs/experiments.md)
- [Runbook](docs/runbook.md)

## Environment Variables

See `.env.example` files in each component directory.

| Variable      | Description                    | Default          |
|---------------|--------------------------------|------------------|
| `DEVICE_ID`   | Pi identifier                  | `pi03-lan`       |
| `MQTT_HOST`   | MQTT broker address            | `localhost`      |
| `MQTT_PORT`   | MQTT broker port               | `1883`           |
| `DB_HOST`     | Postgres host (EC2 local only) | `localhost`      |
| `DB_NAME`     | Database name                  | `telemetry`      |
