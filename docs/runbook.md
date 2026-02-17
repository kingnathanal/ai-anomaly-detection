# Runbook

## Architecture

```
  Pi Nodes (6x)                      AWS EC2 (54.198.26.122)
  ┌──────────┐        MQTT:1883     ┌──────────────────────┐
  │ edge-    │──────telemetry──────▶│ Mosquitto            │
  │ agent    │◀────mitigation/cmd──│                      │
  │          │──────mitigation/ack─▶│ Ingestion → Postgres │
  │          │                      │ Detector  (IF model) │
  │          │──GET /health:8080───▶│ Health :8080         │
  └──────────┘                      │ Mitigator            │
                                    │ Grafana :3000        │
                                    └──────────────────────┘
```

## Nodes

| Name      | IP             | Type | Interface | SSH                          |
|-----------|----------------|------|-----------|------------------------------|
| pi00-wifi | 192.168.1.126  | wifi | wlan0     | `ssh kingnathanal@pi00-wifi` |
| pi01-wifi | 192.168.1.135  | wifi | wlan0     | `ssh kingnathanal@pi01-wifi` |
| pi02-wifi | 192.168.1.138  | wifi | wlan0     | `ssh kingnathanal@pi02-wifi` |
| pi03-lan  | 192.168.1.134  | lan  | eth0      | `ssh kingnathanal@pi03-lan`  |
| pi04-lan  | 192.168.1.136  | lan  | eth0      | `ssh kingnathanal@pi04-lan`  |
| pi05-lan  | 192.168.1.137  | lan  | eth0      | `ssh kingnathanal@pi05-lan`  |

## Control Plane Access

```bash
ssh ubuntu@ec2     # 54.198.26.122 (private: 172.31.64.97)
```

### EC2 Security Group — Required Inbound Rules

| Port/Protocol  | Source          | Purpose                    |
|----------------|-----------------|----------------------------|
| TCP 22         | Your IP         | SSH                        |
| TCP 1883       | 0.0.0.0/0       | MQTT (Mosquitto)           |
| TCP 3000       | 0.0.0.0/0       | Grafana dashboard          |
| TCP 8080       | 0.0.0.0/0       | Health endpoint for probes |
| ICMP (All)     | 0.0.0.0/0       | Ping probes from agents    |

---

## Deployed Services — File Locations

### EC2 Control Plane

| Service    | Install Path                    | Venv                                | systemd Unit       | Config              |
|------------|---------------------------------|--------------------------------------|--------------------|---------------------|
| Mosquitto  | `/etc/mosquitto/`               | (system package)                     | `mosquitto`        | `/etc/mosquitto/conf.d/anomaly-detection.conf` |
| Ingestion  | `/opt/control-plane/ingestion/` | `/opt/control-plane/venv/`           | `ingestion`        | `/opt/control-plane/ingestion/.env` |
| Health     | `/opt/control-plane/health/`    | `/opt/control-plane/health/venv/`    | `health`           | `/opt/control-plane/health/.env` |
| Detector   | `/opt/control-plane/detector/`  | `/opt/control-plane/venv/`           | `detector`         | `/opt/control-plane/detector/.env` |
| EMA Det.   | `/opt/control-plane/detector/`  | `/opt/control-plane/venv/`           | `ema-detector`     | `/opt/control-plane/detector/.env` |
| Mitigator  | `/opt/control-plane/mitigator/` | `/opt/control-plane/venv/`           | `mitigator`        | `/opt/control-plane/mitigator/.env` |
| Postgres   | (system package)                | —                                    | `postgresql`       | `pg_hba.conf` (local only) |
| Grafana    | (system package)                | —                                    | `grafana-server`   | `/etc/grafana/grafana.ini` |

### Raspberry Pi Edge Agents

| Item           | Path                                |
|----------------|-------------------------------------|
| Agent code     | `/opt/edge-agent/agent.py`          |
| Config module  | `/opt/edge-agent/config.py`         |
| Venv           | `/opt/edge-agent/venv/`             |
| Environment    | `/opt/edge-agent/.env`              |
| systemd unit   | `/etc/systemd/system/edge-probe.service` |
| Fault scripts  | `/opt/edge-agent/fault_injection/`  |

### Credentials (environment variables)

| Credential       | Value               | Used By                    |
|------------------|----------------------|----------------------------|
| `MQTT_USER`      | `telemetry_agent`   | Edge agents, ingestion     |
| `MQTT_PASS`      | (see `.env` files)  | Edge agents, ingestion     |
| `DB_NAME`        | `telemetry`         | Ingestion, detector        |
| `DB_USER`        | `telemetry_user`    | Ingestion, detector        |
| `DB_PASS`        | (see `.env` files)  | Ingestion, detector        |
| Grafana admin    | `admin` / (custom)  | Grafana web UI             |

---

## Starting / Stopping Services

### Edge Agent (on each Pi)

```bash
sudo systemctl enable edge-probe
sudo systemctl start edge-probe
sudo systemctl stop edge-probe
sudo journalctl -u edge-probe -f
```

### Control Plane (on EC2)

```bash
# Start all services
sudo systemctl enable mosquitto health ingestion detector ema-detector mitigator
sudo systemctl start mosquitto health ingestion detector ema-detector mitigator

# Check status
sudo systemctl status mosquitto health ingestion detector ema-detector mitigator

# Restart a single service
sudo systemctl restart ingestion
```

## Checking Logs

```bash
# Edge agent (on Pi)
sudo journalctl -u edge-probe --since "1 hour ago"
sudo journalctl -u edge-probe -f              # live tail

# Control plane services (on EC2)
sudo journalctl -u mosquitto -f
sudo journalctl -u ingestion -f
sudo journalctl -u detector -f
sudo journalctl -u mitigator -f
sudo journalctl -u health -f
```

## Database Access

```bash
# On EC2 only (Postgres is not publicly exposed, port 5432 local only)
sudo -u postgres psql -d telemetry

# Useful queries:
SELECT COUNT(*) FROM telemetry_measurements;
SELECT device_id, network_type, COUNT(*) FROM telemetry_measurements GROUP BY device_id, network_type ORDER BY device_id;
SELECT * FROM telemetry_measurements ORDER BY ts DESC LIMIT 5;
SELECT * FROM anomaly_events ORDER BY event_ts DESC LIMIT 10;
SELECT * FROM mitigation_actions ORDER BY issued_ts DESC LIMIT 10;

# Check recent telemetry health (last 30 seconds)
SELECT device_id, icmp_rtt_avg_ms, icmp_loss_pct, dns_latency_ms, http_latency_ms
FROM telemetry_measurements
WHERE ts > now() - interval '30 seconds'
ORDER BY device_id;
```

### Database Tables

| Table                    | Purpose                           |
|--------------------------|-----------------------------------|
| `telemetry_measurements` | Raw telemetry from all probes (hypertable) |
| `anomaly_events`         | Isolation Forest + EMA detection events (hypertable) |
| `mitigation_actions`     | Issued commands and their status  |

### Key Columns — `telemetry_measurements`

| Column | Type | Notes |
|--------|------|-------|
| `ts` | timestamptz | Timestamp from device |
| `received_ts` | timestamptz | Server-side insert time |
| `device_id` | text | e.g., `pi03-lan` |
| `network_type` | text | `lan` or `wifi` |
| `icmp_rtt_avg_ms` | double precision | Average ICMP round-trip time |
| `icmp_loss_pct` | double precision | Packet loss percentage |
| `dns_latency_ms` | double precision | DNS resolution time |
| `http_latency_ms` | double precision | HTTP GET latency |
| `bandwidth_mbps` | double precision | Periodic bandwidth estimate (~every 5 min, NULL otherwise) |

## Grafana

Access at `http://ec2-54-198-26-122.compute-1.amazonaws.com:3000`

Default credentials configured during deployment.

---

## Initial Deployment Procedures

### Deploy Mosquitto MQTT Broker (EC2)

```bash
# Run from the repo root on your Mac:
bash control-plane/mqtt/deploy.sh
```

The deploy script:
1. Installs `mosquitto` and `mosquitto-clients` via apt
2. Writes `/etc/mosquitto/mosquitto.conf` (persistence, listener)
3. Copies `anomaly-detection.conf` to `/etc/mosquitto/conf.d/`
4. Creates the password file at `/etc/mosquitto/passwd`
5. Restarts Mosquitto

Verify: `ssh ubuntu@ec2 'mosquitto_sub -h localhost -u telemetry_agent -P <pass> -t "test" -W 2'`

### Deploy Ingestion Service (EC2)

```bash
# Create directory and venv
ssh ubuntu@ec2 'sudo mkdir -p /opt/control-plane/ingestion && sudo chown -R ubuntu:ubuntu /opt/control-plane'
ssh ubuntu@ec2 'python3 -m venv /opt/control-plane/venv && /opt/control-plane/venv/bin/pip install paho-mqtt psycopg2-binary'

# Copy code
scp control-plane/ingestion/*.py ubuntu@ec2:/opt/control-plane/ingestion/

# Write .env (set DB_PASS, MQTT_USER, MQTT_PASS)
ssh ubuntu@ec2 'cat > /opt/control-plane/ingestion/.env << EOF
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USER=telemetry_agent
MQTT_PASS=<mqtt_password>
DB_HOST=localhost
DB_PORT=5432
DB_NAME=telemetry
DB_USER=telemetry_user
DB_PASS=<db_password>
LOG_LEVEL=INFO
EOF'

# Install systemd service
scp control-plane/systemd/ingestion.service ubuntu@ec2:/tmp/
ssh ubuntu@ec2 'sudo cp /tmp/ingestion.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now ingestion'
```

### Deploy Health Service (EC2)

```bash
ssh ubuntu@ec2 'sudo mkdir -p /opt/control-plane/health && sudo chown -R ubuntu:ubuntu /opt/control-plane/health'
ssh ubuntu@ec2 'python3 -m venv /opt/control-plane/health/venv && /opt/control-plane/health/venv/bin/pip install flask gunicorn'
scp control-plane/health/app.py ubuntu@ec2:/opt/control-plane/health/
ssh ubuntu@ec2 'cat > /opt/control-plane/health/.env << EOF
HEALTH_HOST=0.0.0.0
HEALTH_PORT=8080
LOG_LEVEL=INFO
EOF'
scp control-plane/systemd/health.service ubuntu@ec2:/tmp/
ssh ubuntu@ec2 'sudo cp /tmp/health.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now health'
```

### Deploy Edge Agent (per Pi)

```bash
# For each node — replace DEVICE_ID, NETWORK_TYPE per node
NODE=pi03-lan
NET=lan

ssh kingnathanal@${NODE} 'sudo mkdir -p /opt/edge-agent && sudo chown kingnathanal:kingnathanal /opt/edge-agent'
ssh kingnathanal@${NODE} 'python3 -m venv /opt/edge-agent/venv && /opt/edge-agent/venv/bin/pip install "paho-mqtt>=2.0,<3.0" "requests>=2.31,<3.0"'
scp edge-agent/agent.py edge-agent/config.py kingnathanal@${NODE}:/opt/edge-agent/

ssh kingnathanal@${NODE} "cat > /opt/edge-agent/.env << EOF
DEVICE_ID=${NODE}
NETWORK_TYPE=${NET}
MQTT_HOST=54.198.26.122
MQTT_PORT=1883
MQTT_USER=telemetry_agent
MQTT_PASS=<mqtt_password>
PROBE_INTERVAL_S=10
ICMP_TARGET=54.198.26.122
ICMP_COUNT=3
ICMP_TIMEOUT_S=5
DNS_QUERY=example.com
DNS_TIMEOUT_S=5
HTTP_URL_PRIMARY=http://54.198.26.122:8080/health
HTTP_URL_BACKUP=https://1.1.1.1
ACTIVE_TARGET_ID=primary
HTTP_TIMEOUT_S=10
BANDWIDTH_URL=https://speed.cloudflare.com/__down?bytes=1000000
BANDWIDTH_INTERVAL=30
BANDWIDTH_TIMEOUT_S=15
LOG_LEVEL=INFO
EOF"

scp edge-agent/systemd/edge-probe.service kingnathanal@${NODE}:/tmp/
ssh kingnathanal@${NODE} 'sudo cp /tmp/edge-probe.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now edge-probe'
```

---

## Deploying Code Updates

### Edge Agents

```bash
# From your workstation (Mac):
for node in pi00-wifi pi01-wifi pi02-wifi pi03-lan pi04-lan pi05-lan; do
  scp -i ~/.ssh/remote-key.pem edge-agent/agent.py edge-agent/config.py kingnathanal@${node}:/tmp/
  ssh -i ~/.ssh/remote-key.pem kingnathanal@${node} \
    'sudo cp /tmp/agent.py /tmp/config.py /opt/edge-agent/ && sudo rm -f /opt/edge-agent/__pycache__/*.pyc && sudo systemctl restart edge-probe'
done
```

> **Important:** Always clear `__pycache__/*.pyc` when deploying updated `.py` files.
> Python may load stale bytecode otherwise (see Issue #5).

### Control Plane

```bash
# Ingestion
scp control-plane/ingestion/*.py ubuntu@ec2:/opt/control-plane/ingestion/
ssh ubuntu@ec2 'sudo systemctl restart ingestion'

# Health
scp control-plane/health/app.py ubuntu@ec2:/opt/control-plane/health/
ssh ubuntu@ec2 'sudo systemctl restart health'

# Detector
scp control-plane/detector/*.py ubuntu@ec2:/opt/control-plane/detector/
ssh ubuntu@ec2 'sudo rm -f /opt/control-plane/detector/__pycache__/*.pyc && sudo systemctl restart detector'

# EMA Detector
scp control-plane/detector/ema_detector.py ubuntu@ec2:/opt/control-plane/detector/
ssh ubuntu@ec2 'sudo rm -f /opt/control-plane/detector/__pycache__/*.pyc && sudo systemctl restart ema-detector'

# Mitigator
scp control-plane/mitigator/*.py ubuntu@ec2:/opt/control-plane/mitigator/
ssh ubuntu@ec2 'sudo systemctl restart mitigator'
```

## Fault Injection

```bash
# SSH into a Pi and run a scenario:
ssh kingnathanal@pi03-lan
sudo bash /opt/edge-agent/fault_injection/scenarios.sh eth0

# Or apply manually:
sudo bash /opt/edge-agent/fault_injection/netem_apply.sh -i eth0 -d 100 -j 20
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i eth0
```

**Note:** Fault injection scripts must first be deployed to the Pis:
```bash
for node in pi00-wifi pi01-wifi pi02-wifi pi03-lan pi04-lan pi05-lan; do
  ssh kingnathanal@${node} 'mkdir -p /opt/edge-agent/fault_injection'
  scp edge-agent/fault_injection/*.sh kingnathanal@${node}:/opt/edge-agent/fault_injection/
  ssh kingnathanal@${node} 'chmod +x /opt/edge-agent/fault_injection/*.sh'
done
```

---

## Recovery / Troubleshooting

### Agent not sending telemetry
1. Check the service: `sudo systemctl status edge-probe`
2. Check logs: `sudo journalctl -u edge-probe --since "10 min ago"`
3. Verify MQTT broker is reachable: `mosquitto_pub -h 54.198.26.122 -u telemetry_agent -P <pass> -t test -m hello`
4. Verify `.env` has correct `MQTT_HOST=54.198.26.122`
5. Check that EC2 security group allows TCP 1883 inbound

### ICMP probes showing 100% loss
1. Verify EC2 security group allows **ICMP (All ICMP - IPv4)** inbound from `0.0.0.0/0`
2. Test from Pi: `ping -c 3 54.198.26.122`

### Ingestion not writing to DB
1. Check logs: `sudo journalctl -u ingestion -f`
2. Verify Postgres is running: `sudo systemctl status postgresql`
3. Test DB connection: `psql -h localhost -U telemetry_user -d telemetry`
4. Verify `.env` has correct `DB_PASS`
5. Check MQTT subscription: `mosquitto_sub -h localhost -u telemetry_agent -P <pass> -t 'telemetry/#' -v`

### Detector not scoring
1. Check logs: `sudo journalctl -u detector -f`
2. Ensure 24h baseline data exists
3. Verify telemetry rows: `SELECT COUNT(*) FROM telemetry_measurements WHERE ts > now() - interval '24 hours';`

### Service keeps crashing (any service)
```bash
sudo systemctl status <service-name>
sudo journalctl -u <service-name> --since "5 min ago" --no-pager
# Check for missing deps or bad .env
cat /opt/control-plane/<service>/.env   # EC2
cat /opt/edge-agent/.env                # Pi
```

### Clear netem after experiments
```bash
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i eth0
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i wlan0
```

### Bandwidth probe not recording
1. Check the agent is running the updated code: `grep "probe_bandwidth" /opt/edge-agent/agent.py`
2. Bandwidth fires every 30 cycles (~5 min). Wait at least 5 min after restart.
3. Check agent logs: `sudo journalctl -u edge-probe | grep bandwidth`
4. Verify the download URL is reachable: `curl -o /dev/null -w "%{time_total}" https://speed.cloudflare.com/__down?bytes=1000000`
5. Check DB: `sudo -u postgres psql -d telemetry -c "SELECT device_id, ts, bandwidth_mbps FROM telemetry_measurements WHERE bandwidth_mbps IS NOT NULL ORDER BY ts DESC LIMIT 6;"`

---

## Health Endpoint

The health endpoint runs on EC2 at `http://54.198.26.122:8080/health`. Edge agents
probe this as their **primary** HTTP target so latency measurements
reflect the real edge → cloud path.

```bash
# Check status (from EC2)
curl http://localhost:8080/health

# Check status (from Mac or Pi)
curl http://54.198.26.122:8080/health

# Simulate server-side degradation (adds 500ms to responses)
curl -X POST http://localhost:8080/degrade -H 'Content-Type: application/json' -d '{"delay_ms": 500}'

# Check degradation state
curl http://localhost:8080/degrade

# Clear degradation
curl -X DELETE http://localhost:8080/degrade
```

Backup/failover target: `https://1.1.1.1` (Cloudflare — always reachable).

---

## Deployment History

| Date       | Action                                    | Notes                                    |
|------------|-------------------------------------------|------------------------------------------|
| 2026-02-15 | Deployed Mosquitto MQTT broker on EC2     | Port 1883, user `telemetry_agent`        |
| 2026-02-15 | Created Postgres tables and indexes       | `001_init.sql`, `002_indexes.sql`        |
| 2026-02-15 | Deployed ingestion service on EC2         | Shared venv at `/opt/control-plane/venv` |
| 2026-02-15 | Deployed health service on EC2            | Own venv, gunicorn on port 8080          |
| 2026-02-15 | Deployed edge agents on all 6 Pis         | All reporting telemetry successfully     |
| 2026-02-15 | Added ICMP inbound rule to EC2 SG         | Ping probes now return 0% loss           |
| 2026-02-16 | Fixed paho-mqtt v2 callbacks (Issues #3-5)| All agents + ingestion updated           |
| 2026-02-16 | Deployed Isolation Forest detector on EC2 | BASELINE_HOURS=28 (temporary)            |
| 2026-02-16 | Installed TimescaleDB on EC2              | v2.25.0, both main tables → hypertables |
| 2026-02-16 | Deployed Grafana alert rules              | 8 rules: 4 threshold + 4 model health   |
| 2026-02-17 | Added bandwidth probe to edge agents      | ~1MB Cloudflare download every ~5 min    |
| 2026-02-17 | Added bandwidth panels to 3 dashboards    | Latency, Experiment, Network Comparison  |
