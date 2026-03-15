# Experiments

## Overview

All experiments use `tc netem` fault injection on the Raspberry Pi nodes to
create **repeatable, ground-truth incidents**.  The `scenarios.sh` script
automates the sequence and logs timestamps for each phase.

---

## Architecture Change: Dedicated Failover Server

As of the Exp 4 planning phase, the backup/failover HTTP endpoint moved from
a second port on the primary EC2 to a **completely separate AWS EC2 instance**.

| Role | Host | IP | Health URL |
|------|------|----|------------|
| Primary control plane | `ubuntu@ec2` | 54.198.26.122 | `http://54.198.26.122:8080/health` |
| Failover endpoint | `ubuntu@failover` | 34.226.196.133 | `http://34.226.196.133:8080/health` |

**Why this matters:** `scenarios.sh` scopes netem faults to `PRIMARY_IP=54.198.26.122`
only.  After the mitigator triggers failover, the edge agent switches to probing
`34.226.196.133:8080/health` — a different physical host with no netem rules applied.
HTTP traffic to the failover server flows completely unimpeded, producing a clean
before/after signal for impact reduction measurement.

Previously, the backup endpoint was port 8082 on the same EC2 instance. That
co-located design meant netem rules on the primary IP still affected both endpoints,
contaminating impact reduction measurements.

---

## Exploratory / Setup Runs *(archived — not used for paper metrics)*

These runs were used to build, debug, and validate the pipeline. They had
configuration issues that make their metrics inconsistent or not directly
comparable. They are archived here for reference only.

| Run | Issue | Valid for |
|-----|-------|-----------|
| Setup Run A | Mitigator not deployed | Detection MTTD only |
| Setup Run B | Tuple-unpack bug in mitigator (`controller.py`) | Partial detection only |
| Setup Run C | Backup co-located (port 8082, same EC2) — shared fault domain | Pipeline validation only |
| Setup Run D | WiFi nodes used `eth0` instead of `wlan0` — only 3/6 nodes faulted | LAN-only clean data |

See `docs/troubleshooting-log.md` Issues #9 and #10 for details on bugs fixed.

---

## Canonical Paper Experiments

Three experiments with **varying fault severity** to characterize detection sensitivity across a range of conditions. All experiments use the same nodes, timing structure, and infrastructure — only the fault parameters change.

All 6 nodes faulted. Separate failover EC2. Interface auto-detected. ~45 minutes apart to allow system to settle between runs.

### Configuration (all 3 experiments — shared)

| Setting | Value |
|---------|-------|
| Nodes | All 6 (pi00–pi02 WiFi on `wlan0`, pi03–pi05 LAN on `eth0`) |
| Scenario timing | 2m baseline + 5m delay + 2m recovery + 3m loss + 2m recovery = **14 min** |
| Primary endpoint | `http://54.198.26.122:8080/health` |
| Failover endpoint | `http://34.226.196.133:8080/health` (separate EC2, netem-free) |
| netem scoping | `PRIMARY_IP=54.198.26.122` only |
| Interface | Auto-detected from hostname (`*wifi*` → `wlan0`, else `eth0`) |
| Gap between runs | ~45 min (edge agents restarted to reset failover state) |

### Fault Parameters (varies per experiment)

| Experiment | Delay | Jitter | Loss | Purpose |
|------------|-------|--------|------|---------|
| **Exp 1** ✅ | 100ms | ±20ms | 2% | Moderate/realistic — baseline for comparison |
| **Exp 2** | 200ms | ±40ms | 5% | Severe — larger signal, expected faster MTTD |
| **Exp 3** | 50ms | ±10ms | 1% | Subtle/borderline — tests detection floor |

### Scenario Phases

| Phase | Duration | Parameters |
|-------|----------|------------|
| Baseline | 2 min | Clean (no netem) |
| Delay | 5 min | 100ms ± 20ms (normal distribution), scoped to `PRIMARY_IP` |
| Recovery 1 | 2 min | Clean |
| Packet loss | 3 min | 2% loss, scoped to `PRIMARY_IP` |
| Recovery 2 | 2 min | Clean |

### Experiment 1 *(pending)*

| Field | Detail |
|-------|--------|
| **Status** | Pending |
| **Planned start** | ~1 hr after system reset (~22:00Z) |
| **Notes** | First canonical run. All 6 nodes. Interface auto-detection active. |

### Experiment 2 *(pending — severe fault)*

| Field | Detail |
|-------|--------|
| **Status** | Pending |
| **Planned start** | ~45 min after Exp 1 completes (~22:59Z) |
| **Delay** | **200ms ± 40ms** |
| **Loss** | **5%** |
| **Notes** | Severe fault. Expected faster MTTD (larger signal). Tests upper detection bound. |

Launch command:
```bash
# On each node:
cd /opt/edge-agent/fault_injection && sudo bash scenarios.sh -d 200 -j 40 -l 5 > /tmp/exp2-pi00.log 2>&1
```

### Experiment 3 *(pending — subtle fault)*

| Field | Detail |
|-------|--------|
| **Status** | Pending |
| **Planned start** | ~45 min after Exp 2 completes (~23:58Z) |
| **Delay** | **50ms ± 10ms** |
| **Loss** | **1%** |
| **Notes** | Subtle/borderline fault. Tests detection floor. May not trigger all nodes — that's a valid result. |

Launch command:
```bash
# On each node:
cd /opt/edge-agent/fault_injection && sudo bash scenarios.sh -d 50 -j 10 -l 1 > /tmp/exp3-pi00.log 2>&1
```

### Expected Metrics

| Metric | Exp 1 (100ms/2%) | Exp 2 (200ms/5%) | Exp 3 (50ms/1%) |
|--------|-----------------|-----------------|-----------------|
| Baseline HTTP latency | ~80ms | ~80ms | ~80ms |
| HTTP latency during fault | ~280ms | ~380ms | ~130ms |
| HTTP latency after failover | ~80ms | ~80ms | ~80ms |
| Impact reduction (est.) | ~72% | ~79% | ~38% |
| Detection MTTD (est.) | ~49–92s | ~30–60s (faster) | ~90–180s (slower/borderline) |
| Mitigation lag (est.) | ~148–208s | ~120–180s | ~200–300s |
| Notes | Baseline ✅ done | Larger signal, faster | May not detect all nodes |

### Pre-Experiment Checklist

Run before **each** experiment:

```bash
# 1. Restart all edge agents to reset failover state → primary
for node in pi00-wifi pi01-wifi pi02-wifi pi03-lan pi04-lan pi05-lan; do
  ssh -i ~/.ssh/remote-key.pem kingnathanal@${node} "sudo systemctl restart edge-probe"
done

# 2. Confirm all 6 are on primary target
ssh -i ~/.ssh/remote-key.pem ubuntu@ec2 \
  "sudo -u postgres psql -d telemetry -c \"
    SELECT DISTINCT ON (device_id) device_id, target_id, ts
    FROM telemetry_measurements
    ORDER BY device_id, ts DESC;\""

# 3. Confirm both health endpoints are up
curl -s http://54.198.26.122:8080/health && curl -s http://34.226.196.133:8080/health

# 4. Confirm no active netem on any node
for node in pi00-wifi pi01-wifi pi02-wifi pi03-lan pi04-lan pi05-lan; do
  ssh -i ~/.ssh/remote-key.pem kingnathanal@${node} "sudo tc qdisc show dev eth0; sudo tc qdisc show dev wlan0" 2>/dev/null
done

# 5. Confirm 0 anomalies in last 5 min (system settled)
ssh -i ~/.ssh/remote-key.pem ubuntu@ec2 \
  "sudo -u postgres psql -d telemetry -c \"
    SELECT count(*) FROM anomaly_events
    WHERE is_anomaly=true AND event_ts > now() - interval '5 minutes';\""
```

### Launch Command (all 6 nodes simultaneously)

```bash
EXP=exp1  # change to exp2, exp3 for subsequent runs

for node in pi00-wifi pi01-wifi pi02-wifi pi03-lan pi04-lan pi05-lan; do
  short=${node%%-*}
  ssh -i ~/.ssh/remote-key.pem kingnathanal@${node} \
    "cd /opt/edge-agent/fault_injection && sudo bash scenarios.sh > /tmp/${EXP}-${short}.log 2>&1" &
done
wait && echo "All nodes complete"

# Collect ground truth logs
mkdir -p docs/screenshots/experiments/ground-truth/${EXP}
for node in pi00-wifi pi01-wifi pi02-wifi pi03-lan pi04-lan pi05-lan; do
  short=${node%%-*}
  scp -i ~/.ssh/remote-key.pem kingnathanal@${node}:/tmp/${EXP}-${short}.log \
    docs/screenshots/experiments/ground-truth/${EXP}/${EXP}-${node}.log
done
```

---

## Baseline Run

Before any fault injection, collect **24 hours** of clean telemetry to train
the Isolation Forest model.

1. Ensure all 6 nodes are running `edge-agent` with default 10 s interval.
2. Verify telemetry is flowing: check Grafana or query Postgres.
3. Wait 24 hours.
4. The detector service will auto-train on the baseline data.

## Standard Scenario (scenarios.sh)

The default scenario (used in Exp 1–4) runs on a single Pi:

| Phase        | Duration | Parameters                       |
|--------------|----------|----------------------------------|
| Baseline     | 2 min    | Clean (no netem)                 |
| Delay        | 5 min    | 100 ms ± 20 ms delay (normal)   |
| Recovery 1   | 2 min    | Clean                            |
| Packet Loss  | 3 min    | 2% packet loss                   |
| Recovery 2   | 2 min    | Clean                            |

**Total duration:** 14 minutes

### Running

```bash
# On a Pi node (e.g., pi03-lan):
sudo bash /opt/edge-agent/fault_injection/scenarios.sh eth0
```

Output: JSON lines with phase timestamps — save to a file for ground truth.

```bash
sudo bash scenarios.sh eth0 | tee /tmp/scenario_$(date +%s).jsonl
```

## Custom Experiments

### Delay only
```bash
sudo bash netem_apply.sh -i eth0 -d 200 -j 50
# ... wait ...
sudo bash netem_clear.sh -i eth0
```

### Loss only
```bash
sudo bash netem_apply.sh -i wlan0 -l 5
# ... wait ...
sudo bash netem_clear.sh -i wlan0
```

### Combined delay + loss
```bash
sudo bash netem_apply.sh -i eth0 -d 100 -j 20 -l 1
```

## Expected Outcomes

| Injection           | Expected Detection | Expected Mitigation          |
|---------------------|--------------------|------------------------------|
| 100 ms delay        | MTTD < 5 min       | `failover_endpoint` issued   |
| 2% packet loss      | MTTD < 5 min       | `failover_endpoint` issued   |
| Clean (no fault)    | No alerts           | None                         |

## Evaluation Metrics

- **MTTD** — Mean Time to Detect (fault injection start → first anomaly event)
- **False alert rate** — anomaly events per hour during baseline
- **Impact reduction** — compare p95 latency before vs. after mitigation
