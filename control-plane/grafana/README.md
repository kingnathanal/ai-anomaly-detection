# Grafana Setup for Edge AI Anomaly Detection

This directory contains Grafana installation scripts, datasource configurations, and pre-built dashboards for visualizing telemetry and anomaly detection metrics.

## Quick Start

### 1. Install Grafana on EC2 Control Plane

SSH into your EC2 instance:
```bash
ssh ubuntu@ec2
```

Navigate to the grafana directory and run the installation script:
```bash
cd ~/ai-anomaly-detection/control-plane/grafana
chmod +x install.sh
./install.sh
```

The script will:
- Install Grafana from the official repository
- Configure it as a systemd service
- Set up automatic provisioning for datasources and dashboards
- Start Grafana on port 3000

### 2. Configure Database Credentials

Before the Postgres datasource will work, ensure your database credentials are set as environment variables or update the datasource config:

Edit `/etc/grafana/provisioning/datasources/postgres.yml` if needed:
```bash
sudo nano /etc/grafana/provisioning/datasources/postgres.yml
```

The datasource uses these environment variables (with defaults):
- `DB_NAME` (default: telemetry)
- `DB_USER` (default: telemetry_user)
- `DB_PASS` (default: change_me_now)

To use environment variables, add them to Grafana's systemd service:
```bash
sudo systemctl edit grafana-server
```

Add:
```ini
[Service]
Environment="DB_NAME=telemetry"
Environment="DB_USER=telemetry_user"
Environment="DB_PASS=your_actual_password"
```

Then restart:
```bash
sudo systemctl restart grafana-server
```

### 3. Open Firewall Port

Ensure port 3000 is accessible in your EC2 security group:
- Go to AWS Console → EC2 → Security Groups
- Add inbound rule: Type: Custom TCP, Port: 3000, Source: Your IP or 0.0.0.0/0 (for testing)

### 4. Access Grafana

Open your browser:
```
http://<ec2-public-ip>:3000
```

Default credentials:
- Username: `admin`
- Password: `admin`

You'll be prompted to change the password on first login.

## Pre-configured Dashboards

Three dashboards are automatically provisioned:

### 1. **Latency Overview** (`latency-overview`)
- Real-time visualization of ICMP, HTTP, and DNS latency
- Packet loss monitoring
- Device selector with multi-select support
- Anomaly annotations from `anomaly_events` table
- Auto-refresh every 10 seconds

**Panels:**
- ICMP RTT (Average) - Round-trip time for each device
- HTTP Latency - Application-layer latency
- DNS Latency - DNS resolution time
- ICMP Packet Loss - Network reliability metric

### 2. **Anomaly Detection** (`anomaly-detection`)
- ML model performance tracking
- Anomaly event history and scoring
- Mitigation action tracking

**Panels:**
- Total Anomalies Detected (current time range)
- False Alert Rate (alerts per hour)
- Mitigations Applied (count)
- Current Model Version
- Anomaly Scores Over Time (with threshold line)
- Recent Anomaly Events (table view)

### 3. **LAN vs WiFi Comparison** (`network-comparison`)
- Side-by-side comparison of wired vs wireless performance
- Aggregated metrics for network type analysis

**Panels:**
- LAN vs WiFi - ICMP RTT
- LAN vs WiFi - Packet Loss
- Network Performance Summary (table with p95 statistics)

## Datasource Configuration

The Postgres datasource is configured in `provisioning/datasources/postgres.yml`:

- **Name:** Telemetry Postgres
- **Type:** PostgreSQL
- **Connection:** localhost:5432
- **Database:** telemetry (configurable via `DB_NAME`)
- **SSL Mode:** disabled (local connection)

## Managing Grafana

### Service Control
```bash
# Check status
sudo systemctl status grafana-server

# Start/stop/restart
sudo systemctl start grafana-server
sudo systemctl stop grafana-server
sudo systemctl restart grafana-server

# View logs
sudo journalctl -u grafana-server -f
```

### Configuration Files
- Main config: `/etc/grafana/grafana.ini`
- Datasources: `/etc/grafana/provisioning/datasources/`
- Dashboards: `/var/lib/grafana/dashboards/`
- Logs: `/var/log/grafana/`

## Customizing Dashboards

All dashboards are set to `allowUiUpdates: true`, so you can modify them directly in the Grafana UI. Changes will persist.

To export a modified dashboard:
1. Go to Dashboard Settings (gear icon) → JSON Model
2. Copy the JSON
3. Save to `dashboards/` directory in this repo

To add new dashboards:
1. Create the dashboard in Grafana UI
2. Export JSON
3. Place in `/var/lib/grafana/dashboards/`
4. Grafana will auto-import within 10 seconds

## Troubleshooting

### Datasource Connection Failed
```bash
# Check Postgres is running
sudo systemctl status postgresql

# Verify database exists
sudo -u postgres psql -l | grep telemetry

# Test connection
sudo -u postgres psql -d telemetry -c "SELECT COUNT(*) FROM telemetry_measurements;"

# Check Grafana logs for connection errors
sudo journalctl -u grafana-server -n 50
```

### No Data in Dashboards
1. Verify telemetry is being ingested:
   ```bash
   sudo -u postgres psql -d telemetry -c "SELECT COUNT(*), MAX(ts) FROM telemetry_measurements;"
   ```

2. Check time range in Grafana (top right)

3. Verify device_id values exist:
   ```bash
   sudo -u postgres psql -d telemetry -c "SELECT DISTINCT device_id FROM telemetry_measurements;"
   ```

### Dashboards Not Loading
```bash
# Check provisioning directory permissions
ls -la /var/lib/grafana/dashboards/

# Verify JSON syntax
cat /var/lib/grafana/dashboards/latency-overview.json | jq empty

# Restart Grafana to re-provision
sudo systemctl restart grafana-server
```

## Notes on Time-Series Functions

The dashboards use `time_bucket()` function for aggregation (e.g., in network-comparison dashboard). This function is not native to PostgreSQL.

If you see errors like `function time_bucket() does not exist`:

**Option 1:** Install TimescaleDB extension:
```bash
sudo apt install postgresql-14-timescaledb
sudo -u postgres psql -d telemetry -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

**Option 2:** Replace `time_bucket()` with standard PostgreSQL:
```sql
-- Change from:
time_bucket('30 seconds', ts) AS time

-- To:
date_trunc('minute', ts) AS time
```

Edit dashboard JSON and search/replace the queries.

## Security Considerations

- Default installation binds to `0.0.0.0:3000` (all interfaces)
- For production, consider:
  - Setting up HTTPS/TLS
  - Restricting EC2 security group to specific IPs
  - Using Grafana's built-in authentication or OAuth
  - Running behind nginx reverse proxy

## Additional Resources

- [Grafana Documentation](https://grafana.com/docs/grafana/latest/)
- [PostgreSQL Data Source](https://grafana.com/docs/grafana/latest/datasources/postgres/)
- [Dashboard Provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/#dashboards)
