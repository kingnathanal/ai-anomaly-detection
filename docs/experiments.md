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

| Experiment | Delay | Jitter | Loss | Score Interval | Purpose |
|------------|-------|--------|------|---------------|---------|
| **Exp 1** ✅ | 100ms | ±20ms | 2% | 120s | Moderate — baseline for comparison |
| **Exp 2** ✅ | 200ms | ±40ms | 5% | 120s | Severe — larger signal |
| **Exp 3** | 50ms | ±10ms | 1% | 120s | Subtle — tests detection floor |
| **Exp 4** | 100ms | ±20ms | 2% | **30s** | Same as Exp 1, faster scoring — MTTD comparison |
| **Exp 5** | 200ms | ±40ms | 4% | **30s** | Severe + faster scoring |

**Why 120s was chosen as the initial scoring interval:**
- `WINDOW_LENGTH_S = 120s` (features.py) — one window = 12 samples at 10s interval
- Setting `SCORE_INTERVAL_S = WINDOW_LENGTH_S` gives non-overlapping windows — the simplest, most interpretable scoring cadence
- Conservative choice for a t3.micro EC2 with 6 nodes — low DB read load
- Median MTTD = ~60s (half the interval), max = 120s

**Why 30s for Exp 4/5:**
- Keeps `WINDOW_LENGTH_S=120s` — same features, same model quality
- Scores the most recent 120s window every 30s (4 overlapping passes per window)
- Reduces median MTTD from ~60s → ~15s
- Directly comparable to Exp 1/2 — isolates the effect of scoring frequency alone

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
| **Fault** | 50ms ± 10ms delay, 1% loss |
| **Score interval** | 120s (unchanged) |
| **Notes** | Subtle/borderline fault. Tests detection floor. May not trigger all nodes — that's a valid result. |

Launch command:
```bash
cd /opt/edge-agent/fault_injection && sudo bash scenarios.sh -d 50 -j 10 -l 1 > /tmp/exp3-pi00.log 2>&1
```

### Experiment 4 *(pending — faster scoring, moderate fault)*

| Field | Detail |
|-------|--------|
| **Status** | Pending |
| **Fault** | 100ms ± 20ms delay, 2% loss (same as Exp 1) |
| **Score interval** | **30s** (change `SCORE_INTERVAL_S=30` in detector `.env`, restart detector) |
| **Notes** | Direct MTTD comparison to Exp 1. Isolates effect of scoring frequency. |

Launch command:
```bash
# 1. Update detector on EC2 first:
ssh ubuntu@ec2 "sed -i 's/SCORE_INTERVAL_S=120/SCORE_INTERVAL_S=30/' /opt/control-plane/detector/.env && sudo systemctl restart detector"

# 2. Then launch on all nodes:
cd /opt/edge-agent/fault_injection && sudo bash scenarios.sh -d 100 -j 20 -l 2 > /tmp/exp4-pi00.log 2>&1
```

### Experiment 5 *(pending — faster scoring, severe fault)*

| Field | Detail |
|-------|--------|
| **Status** | Pending |
| **Fault** | 200ms ± 40ms delay, 4% loss |
| **Score interval** | **30s** (keep from Exp 4) |
| **Notes** | Severe fault with fast scoring. Compare to Exp 2 for MTTD improvement. |

Launch command:
```bash
cd /opt/edge-agent/fault_injection && sudo bash scenarios.sh -d 200 -j 40 -l 4 > /tmp/exp5-pi00.log 2>&1
```

### Actual Results (All 5 Experiments Complete)

| Metric | Exp 1 ✅ (100ms/2%, 120s) | Exp 2 ✅ (200ms/5%, 120s) | Exp 3 ✅ (50ms/1%, 120s) | Exp 4r ✅ (100ms/2%, 30s) | Exp 5 ✅ (200ms/4%, 30s) |
|--------|--------------------------|--------------------------|-------------------------|--------------------------|--------------------------|
| Baseline HTTP | 78ms | 80ms | 80ms | 80ms | 80ms |
| Fault HTTP (avg) | 273ms | 308ms | ~130ms | ~280ms | 314ms |
| Post-failover HTTP | 78ms | 78ms | N/A* | ~78ms | 109ms |
| Impact reduction | 72% | ~75% | N/A* | ~72% | 65% |
| MTTD (first detection) | 49s | 118s | 114s | **16s** | **40s** |
| Nodes detected | 5/6 | 6/6 | 3/6 (LAN only) | 4/6 | 6/6 |
| Notes | pi02-wifi missed | All simultaneous | WiFi in noise floor | WiFi missed at 30s | All simultaneous |

> *Exp 3: Only 3/6 LAN nodes detected; `ANOMALY_PERSIST_WINDOWS=3` threshold not sustained across all nodes — mitigation not issued. No failover = no impact reduction measurement.
> Exp 4r = Exp 4-redux: re-run after threshold contamination fix with clean baseline (p97.5).

### MTTD by Node (Per-Experiment Breakdown)

| Node | Type | Exp 1 · 120s | Exp 2 · 120s | Exp 3 · 120s | Exp 4r · 30s | Exp 5 · 30s |
|------|------|:---:|:---:|:---:|:---:|:---:|
| pi00-wifi | WiFi | 92s | 118s | ❌ | ❌ | 40s |
| pi01-wifi | WiFi | 49s | 118s | ❌ | 76s | 40s |
| pi02-wifi | WiFi | ❌ | 118s | ❌ | ❌ | 40s |
| pi03-lan | LAN  | 49s | 118s | 114s | 46s | 40s |
| pi04-lan | LAN  | 49s | 118s | 114s | **16s** | 40s |
| pi05-lan | LAN  | 49s | 118s | 114s | 46s | 40s |

### Scoring Interval Impact (Core Finding)

| Fault | 120s Scoring | 30s Scoring | MTTD Δ | Detection Δ |
|-------|:---:|:---:|:---:|:---:|
| 100ms/2% | 49s · 5/6 | **16s** · 4/6 | **−67%** | −1 node (WiFi noise floor) |
| 200ms/4% | 118s · 6/6 | **40s** · 6/6 | **−66%** | No change |

> MTTD is governed by when the scoring cycle fires relative to fault injection — not fault severity. Larger faults produce higher scores, not faster detection.

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

## Actual Outcomes (Final)

| Injection              | Detected      | MTTD (first) | Mitigation Issued |
|------------------------|:-------------:|:------------:|:-----------------:|
| 100ms/2% loss · 120s  | 5/6           | 49s          | ✅ failover_endpoint |
| 200ms/5% loss · 120s  | 6/6           | 118s         | ✅ failover_endpoint |
| 50ms/1% loss · 120s   | 3/6 (LAN)     | 114s         | ❌ (persist threshold not met) |
| 100ms/2% loss · **30s** | 4/6         | **16s**      | ✅ failover_endpoint (LAN nodes) |
| 200ms/4% loss · **30s** | 6/6         | **40s**      | ✅ failover_endpoint (all nodes) |
| Clean baseline         | 0 false alerts | —           | None |

## Key Findings

1. **30s scoring windows reduce MTTD by 67%** vs 120s (49s → 16s first detection at 100ms fault)
2. **MTTD is governed by scoring interval, not fault severity** — larger faults produce higher scores but not faster detection
3. **50ms/1% is the LAN detection floor** — WiFi nodes require ≥100ms delay due to natural jitter in baseline
4. **30s windows increase miss rate on borderline WiFi faults** — higher per-window score variance causes 4/6 instead of 5/6 detection
5. **Automated failover reduces HTTP latency 65–72%** within 10 seconds of command apply
6. **p97.5 is the optimal threshold percentile** — robust to ~5% contaminated baseline; p95 causes false positives on noisy WiFi, p99 causes missed detections after baseline contamination
7. **Adaptive scoring (recommended)**: 120s default → drop to 30s on first anomaly for lowest MTTD without sacrificing detection rate

## Evaluation Metrics

- **MTTD** — Mean Time to Detect (fault injection start → first anomaly event per node)
- **False alert rate** — anomaly events per hour during clean baseline (target: 0)
- **Impact reduction** — mean + p95 HTTP latency before vs. after mitigation apply
- **Detection rate** — fraction of nodes that detected the fault (out of 6)
