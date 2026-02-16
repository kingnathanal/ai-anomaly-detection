# MQTT Topics & Payload Schema

## Topics

| Direction     | Topic Pattern                         | QoS | Retain |
|---------------|---------------------------------------|-----|--------|
| Edge → Cloud  | `telemetry/<device_id>/<target_id>`   | 1   | false  |
| Cloud → Edge  | `mitigation/<device_id>/command`      | 1   | false  |
| Edge → Cloud  | `mitigation/<device_id>/status`       | 1   | false  |

### Device IDs

| Node       | device_id   | network_type |
|------------|-------------|--------------|
| Pi 0       | pi00-wifi   | wifi         |
| Pi 1       | pi01-wifi   | wifi         |
| Pi 2       | pi02-wifi   | wifi         |
| Pi 3       | pi03-lan    | lan          |
| Pi 4       | pi04-lan    | lan          |
| Pi 5       | pi05-lan    | lan          |

---

## Payloads

### 1. Telemetry (edge → cloud)

Published every `interval_s` seconds (default: 10).

```json
{
  "ts": "2026-01-16T01:23:45.678Z",
  "device_id": "pi03-lan",
  "network_type": "lan",
  "target_id": "primary",
  "interval_s": 10,
  "metrics": {
    "icmp": {
      "ok": true,
      "rtt_min_ms": 18.9,
      "rtt_avg_ms": 21.3,
      "rtt_max_ms": 27.1,
      "loss_pct": 0.0
    },
    "dns": {
      "ok": true,
      "query": "example.com",
      "latency_ms": 12.4
    },
    "http": {
      "ok": true,
      "url": "https://primary.example.com/health",
      "status": 200,
      "latency_ms": 155.2
    }
  }
}
```

### 2. Mitigation Command (cloud → edge)

```json
{
  "ts": "2026-01-16T01:30:00.000Z",
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "action": "failover_endpoint",
  "params": {
    "target_id": "backup",
    "http_url": "https://backup.example.com/health"
  }
}
```

**Supported actions:**

| Action              | Description                         | Params                              |
|---------------------|-------------------------------------|--------------------------------------|
| `failover_endpoint` | Switch the probed HTTP target       | `target_id`, `http_url`             |
| `set_interval`      | Change the probe sampling interval  | `interval_s` (e.g., 2)             |

### 3. Mitigation Status / Ack (edge → cloud)

```json
{
  "ts": "2026-01-16T01:30:01.200Z",
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "pi03-lan",
  "status": "applied",
  "details": "Switched to backup endpoint"
}
```

**Status values:** `applied`, `failed`
