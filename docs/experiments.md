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

## Research Experiment Plan

### Experiment 1 — Detection Only *(completed)*

| Field | Detail |
|-------|--------|
| **Status** | Done |
| **Scope** | Detection only — mitigator was not deployed |
| **Nodes** | All 6 |
| **Scenario** | Standard (delay 100ms + loss 2%) |
| **Valid for** | MTTD detection measurement |
| **Notes** | Established baseline detection performance; 35 anomaly events flagged across all nodes. Mitigator was not deployed so zero mitigation commands issued. |

### Experiment 2 — Partial Mitigation / LAN Only *(completed)*

| Field | Detail |
|-------|--------|
| **Status** | Done |
| **Scope** | Mitigator deployed but tuple-unpack bug caused silent failure for first ~9 min |
| **Nodes** | All 6 (LAN mitigation only in valid window) |
| **Scenario** | Standard (delay 100ms + loss 2%) |
| **Valid for** | Detection MTTD + partial mitigation pipeline validation |
| **Notes** | Mitigator deployed; bug in `controller.py` (`for device_id, target_id in pairs:` → query returns 3-tuple) caused all mitigation commands to fail silently until the bug was fixed live at 17:55Z. LAN nodes received valid mitigations after the fix. See Issue #9 in troubleshooting-log.md. |

### Experiment 3 — Full End-to-End, Co-Located Backup *(completed)*

| Field | Detail |
|-------|--------|
| **Status** | Done |
| **Scope** | Full pipeline: all 6 nodes detected + mitigated |
| **Nodes** | All 6 |
| **Scenario** | Standard (delay 100ms + loss 2%) |
| **Backup endpoint** | Port 8082 on primary EC2 (co-located) |
| **Valid for** | Detection + mitigation pipeline validation (end-to-end flow confirmed) |
| **Notes** | Backup was co-located on the same EC2 (port 8082). Netem rules on the primary IP still affected backup traffic, so impact reduction measurements are not clean. Use Exp 4 for impact reduction analysis. |

### Experiment 4 — Full End-to-End, Proper Failover Server *(planned)*

| Field | Detail |
|-------|--------|
| **Status** | Planned |
| **Scope** | Full pipeline with separate failover EC2 — canonical clean run for impact reduction |
| **Nodes** | All 6 |
| **Scenario** | Standard: delay 100ms ± 20ms for 5 min + loss 2% for 3 min |
| **Backup endpoint** | `http://34.226.196.133:8080/health` (separate EC2, unaffected by netem) |
| **netem scoping** | `PRIMARY_IP=54.198.26.122` only — failover traffic to 34.226.196.133 is unimpeded |

#### Expected Metrics

| Metric | Expected Value |
|--------|----------------|
| Baseline HTTP latency | ~45 ms (primary, no fault) |
| HTTP latency during fault | ~295 ms (100ms netem added) |
| HTTP latency after failover | ~45 ms (backup EC2, no netem) |
| Impact reduction | ~85% HTTP latency reduction |
| Detection MTTD | ~30–50 s (based on Exp 1–3) |
| Mitigation MTTD | ~180–240 s (`ANOMALY_PERSIST_WINDOWS=2` × 120 s window + 60 s poll) |

#### Pre-Experiment Checklist

- [ ] All 6 edge agents running (`systemctl is-active edge-probe` on each Pi)
- [ ] All control-plane services active: `systemctl is-active ingestion detector ema-detector mitigator`
- [ ] Failover server responding: `curl http://34.226.196.133:8080/health`
- [ ] Primary health endpoint responding: `curl http://54.198.26.122:8080/health`
- [ ] Edge agent `.env` has `HTTP_URL_BACKUP=http://34.226.196.133:8080/health`
- [ ] `ANOMALY_PERSIST_WINDOWS=2` in mitigator `.env`
- [ ] netem cleared on all Pis from any prior run
- [ ] Grafana open, time range set to "last 15 min", auto-refresh 10s

#### Running

```bash
# On each Pi simultaneously (run all 6 in separate terminals or tmux):
sudo bash /opt/edge-agent/fault_injection/scenarios.sh eth0   # LAN nodes
sudo bash /opt/edge-agent/fault_injection/scenarios.sh wlan0  # WiFi nodes

# Save ground truth timestamps:
sudo bash /opt/edge-agent/fault_injection/scenarios.sh eth0 | tee /tmp/exp4_$(date +%s).jsonl
```

### Experiment 5 — Stress Test, High Severity *(planned)*

| Field | Detail |
|-------|--------|
| **Status** | Planned |
| **Scope** | Detection robustness + mitigation effectiveness under severe fault conditions |
| **Nodes** | All 6 |
| **Scenario** | Stress: delay 200ms ± 30ms for 5 min + loss 5% for 5 min |
| **Backup endpoint** | `http://34.226.196.133:8080/health` (same separate EC2 as Exp 4) |

#### Scenario Phases

| Phase | Duration | Parameters |
|-------|----------|------------|
| Baseline | 2 min | Clean (no netem) |
| Delay | 5 min | 200ms ± 30ms delay (normal distribution) |
| Recovery 1 | 2 min | Clean |
| Loss | 5 min | 5% packet loss |
| Recovery 2 | 2 min | Clean |

**Total duration:** 16 minutes

#### Research Questions

- Does detection still occur at MTTD < 60s under 2× the standard delay?
- Does the Isolation Forest score saturate at high severity, or scale proportionally?
- Does the EMA detector flag faster than IF under severe conditions?
- Is impact reduction still measurable after failover (backup unaffected)?
- Are there any false-negative windows where the model misses a severe fault?

#### Expected Outcomes

| Metric | Expected Value |
|--------|----------------|
| Baseline HTTP latency | ~45 ms |
| HTTP latency during 200ms fault | ~445 ms |
| HTTP latency during 5% loss fault | elevated + jitter from retransmits |
| HTTP latency after failover | ~45 ms (backup EC2) |
| Detection MTTD | < 30 s (larger signal → faster detection) |
| False negatives | None expected at this severity |

#### Custom `scenarios.sh` for Exp 5

Run manually with `netem_apply.sh` since the default `scenarios.sh` uses 100ms + 2%:

```bash
# On each Pi:
# Phase 1: baseline 2 min
echo '{"phase":"baseline","start":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}'
sleep 120

# Phase 2: delay 200ms ±30ms for 5 min
sudo bash /opt/edge-agent/fault_injection/netem_apply.sh -i eth0 -d 200 -j 30 -t 54.198.26.122
echo '{"phase":"delay_200ms","start":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}'
sleep 300
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i eth0

# Phase 3: recovery 2 min
echo '{"phase":"recover_1","start":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}'
sleep 120

# Phase 4: loss 5% for 5 min
sudo bash /opt/edge-agent/fault_injection/netem_apply.sh -i eth0 -l 5 -t 54.198.26.122
echo '{"phase":"loss_5pct","start":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}'
sleep 300
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i eth0

# Phase 5: recovery 2 min
echo '{"phase":"recover_2","start":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}'
sleep 120
echo '{"phase":"done","end":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}'
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
