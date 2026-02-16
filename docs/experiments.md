# Experiments

## Overview

All experiments use `tc netem` fault injection on the Raspberry Pi nodes to
create **repeatable, ground-truth incidents**.  The `scenarios.sh` script
automates the sequence and logs timestamps for each phase.

## Baseline Run

Before any fault injection, collect **24 hours** of clean telemetry to train
the Isolation Forest model.

1. Ensure all 6 nodes are running `edge-agent` with default 10 s interval.
2. Verify telemetry is flowing: check Grafana or query Postgres.
3. Wait 24 hours.
4. The detector service will auto-train on the baseline data.

## Standard Scenario (scenarios.sh)

The default scenario runs on a single Pi:

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
