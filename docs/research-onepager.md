# AI-Based Latency Anomaly Detection & Automated Mitigation in Edge Networks

**Graduate Research** · 6-Node Raspberry Pi Testbed + AWS EC2 Control Plane · March 2026

![experiments](https://img.shields.io/badge/Experiments-5%20Complete-brightgreen) ![nodes](https://img.shields.io/badge/Nodes-6%2F6%20Active-blue) ![rows](https://img.shields.io/badge/Telemetry-1.09M%20rows-lightgrey)

---

## Overview

This research designs and evaluates an **unsupervised anomaly detection system** for edge networks that detects gray failures (latency/jitter/loss degradations) and triggers automated mitigation — without labeled training data. The system uses Isolation Forest on windowed ICMP/DNS/HTTP features, MQTT transport, and automated failover via a cloud-controlled mitigation loop.

**Research questions:**
1. Can unsupervised IF detect subtle gray failures (≥50ms delay, ≥1% loss) within a single scoring interval?
2. How does scoring window length trade off MTTD vs. detection rate?
3. Does automated failover meaningfully reduce latency impact?

---

## System Architecture

| Component | Details |
|-----------|---------|
| **Edge nodes** | 6× Raspberry Pi 4 — 3 LAN (eth0) + 3 WiFi (wlan0) |
| **Transport** | MQTT QoS 1 · `telemetry/<device>/<target>` · 10s interval |
| **Broker** | Mosquitto on AWS EC2 t3.micro (Ubuntu 22.04) |
| **Database** | PostgreSQL 16 + TimescaleDB · 1.09M rows · 27 days |
| **Detector** | Isolation Forest · 9 windowed features · 120s window (12 samples) |
| **Threshold** | p97.5 of 24h per-node baseline scores (≈ 0.65–0.71) |
| **Mitigation** | `failover_endpoint` + `set_interval` via MQTT command |
| **Backup EP** | Separate EC2 instance — independent fault domain |

---

## Feature Engineering (9 windowed features per 120s window)

| Protocol | Features |
|----------|---------|
| **ICMP** | `rtt_mean`, `rtt_std` (jitter), `rtt_max`, `loss_mean` |
| **DNS** | `dns_latency_mean`, `dns_fail_rate` |
| **HTTP** | `http_latency_mean`, `http_latency_p95`, `http_error_rate` |

> **Model:** `IsolationForest(n_estimators=100, contamination=0.01)` · Retrained on service restart only · Threshold: p97.5 of baseline score distribution per node

---

## Experiment Results — MTTD by Node

Fault injected via `tc netem` scoped to PRIMARY_IP · All 6 nodes simultaneous · ~12 min per run

| Node | Type | E1 · 100ms/2% · 120s | E2 · 200ms/5% · 120s | E3 · 50ms/1% · 120s | E4r · 100ms/2% · **30s** | E5 · 200ms/4% · **30s** |
|------|------|:---:|:---:|:---:|:---:|:---:|
| pi00-wifi | WiFi | 92s | 118s | ❌ | ❌ | 40s |
| pi01-wifi | WiFi | 49s | 118s | ❌ | 76s | 40s |
| pi02-wifi | WiFi | ❌ | 118s | ❌ | ❌ | 40s |
| pi03-lan | LAN | 49s | 118s | 114s | 46s | 40s |
| pi04-lan | LAN | 49s | 118s | 114s | **16s** | 40s |
| pi05-lan | LAN | 49s | 118s | 114s | 46s | 40s |
| **Detected** | | **5/6** | **6/6** | **3/6** | **4/6** | **6/6** |
| **Median MTTD** | | **49s** | **118s** | **114s** *(LAN only)* | **46s** | **40s** |

> E4r = Exp 4-redux (re-run after threshold contamination fix with clean baseline)

---

## Scoring Interval Impact (Core Finding)

| Fault | 120s Scoring | 30s Scoring | MTTD Reduction | Detection Rate |
|-------|:---:|:---:|:---:|:---:|
| 100ms / 2% loss | 49s · 5/6 | **16s** · 4/6 | **−67%** | −1 node (WiFi noise) |
| 200ms / 4% loss | 118s · 6/6 | **40s** · 6/6 | **−66%** | No change ✓ |

> **Key insight:** MTTD is governed by *when the scoring cycle fires relative to fault injection*, not fault severity. Larger faults do not produce faster detection — they produce higher scores.

---

## Automated Mitigation — End-to-End Timeline (Exp 5)

```
T+0s     Fault injected — tc netem 200ms delay + 4% loss on PRIMARY_IP
T+40s    First anomaly detected — all 6 nodes (scores 0.72–0.79 vs thresholds 0.65–0.71)
T+146s   Mitigator fires — 3 consecutive anomaly windows × 30s + processing lag
T+147s   MQTT command delivered: failover_endpoint + set_interval:2s
T+148s   All 6 nodes ACK "applied" — HTTP traffic switched to backup EC2
T+158s   HTTP latency recovers — 314ms → 109ms  (65% reduction)
```

> `ANOMALY_PERSIST_WINDOWS=3` requires 3 consecutive detections before mitigating (90s minimum at 30s scoring)

---

## Impact Reduction — HTTP Latency (Exp 1 reference)

| Phase | LAN avg | LAN p95 | WiFi avg | WiFi p95 |
|-------|:---:|:---:|:---:|:---:|
| Baseline | 78ms | 86ms | 103ms | 120ms |
| Fault (pre-failover) | 273ms | 300ms | 314ms | 351ms |
| Post-failover | 78ms | 85ms | 109ms | 135ms |
| **Impact reduction** | **72%** | **72%** | **65%** | **61%** |

---

## Key Findings

1. ✅ **67% MTTD reduction** — 30s scoring windows vs 120s (49s → 16s first detection)
2. ✅ **6/6 detection** at 200ms fault — both WiFi and LAN nodes detected simultaneously
3. ✅ **65–72% HTTP latency reduction** within 10s of failover apply
4. ✅ **Sub-1s MQTT delivery** — command issued + all 6 ACKs within 1 second
5. ⚠️ **Detection floor** — 50ms/1% detectable on LAN (3/3); WiFi requires ≥100ms (natural jitter masks subtle faults)
6. ⚠️ **30s window tradeoff** — lower MTTD but higher per-window variance → borderline WiFi faults missed (4/6 vs 5/6)
7. ⚠️ **Packet loss alone insufficient** — 2–5% loss without delay did not independently trigger IF detection
8. 🔵 **p97.5 threshold sweet spot** — robust to ~5% baseline contamination; p95 causes false positives, p99 causes missed detections
9. 🔵 **Per-node thresholds diverge** — WiFi nodes 0.04+ higher than LAN peers due to natural jitter baked into baseline
10. 🔵 **Adaptive scoring** (recommended) — 120s default, drop to 30s on first anomaly for lowest MTTD without sacrificing detection rate

---

## Model Comparison — Isolation Forest vs EMA Z-Score (26-day baseline)

Two detectors ran concurrently: **Isolation Forest** (9-feature multivariate, windowed) and **EMA Z-Score** (univariate per metric, rolling mean ± 3σ).

| Metric | EMA Z-Score | Isolation Forest |
|--------|:-----------:|:----------------:|
| Baseline avg score | 1.17 | 0.38 |
| Baseline p95 score | 2.55 | 0.55 |
| Threshold | 3.00 (fixed 3σ) | 0.65–0.71 (p97.5 per node) |
| **LAN false alert rate** | **0.08/hr** | 0.28/hr |
| **WiFi false alert rate** | **0.25/hr** | 0.50/hr |
| Nodes detected (5-exp suite) | 6/6 | 6/6 |
| Anomaly windows flagged (exp period) | 26 | 113 |
| Detection approach | Any single metric >3σ from EMA | Joint 9-feature anomaly score |

**Key tradeoff:** EMA produces 3.5× fewer false alerts on LAN and 2× fewer on WiFi. IF flags 4.4× more windows per experiment — higher sensitivity to sustained multivariate degradation. Both detected all 6 nodes across the suite. Model disagreements were almost entirely IF false positives during noisy WiFi baseline that EMA correctly ignored.

---

## Experimental Design Summary

| Exp | Delay | Loss | Scoring | Detected | MTTD (first) | Purpose |
|-----|-------|------|:---:|:---:|:---:|---------|
| 1 | 100ms ±20ms | 2% | 120s | 5/6 | 49s | Moderate fault — baseline |
| 2 | 200ms ±40ms | 5% | 120s | 6/6 | 118s | Severe fault severity |
| 3 | 50ms ±10ms | 1% | 120s | 3/6 | 114s | Subtle — detection floor |
| 4r | 100ms ±20ms | 2% | **30s** | 4/6 | **16s** | Interval comparison |
| 5 | 200ms ±40ms | 4% | **30s** | 6/6 | **40s** | Interval + severity |

---

*GitHub: [kingnathanal/ai-anomaly-detection](https://github.com/kingnathanal/ai-anomaly-detection) · 5 experiments · 6 nodes · 1.09M telemetry rows · 27 days baseline*
