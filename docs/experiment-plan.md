# Fault Injection Experiment Plan

> **Status:** Waiting for 24h clean baseline (ready ~22:00 UTC Feb 17 / ~5:00 PM EST Tuesday)

---

## Network Environment

The testbed shares a residential internet connection with other household
devices. To account for potential bandwidth contention inflating latency
measurements, we capture a periodic bandwidth estimate alongside telemetry.

**Bandwidth Probe:**
- Every **30 probe cycles** (~5 minutes), each Pi downloads a ~1 MB file from
  Cloudflare's speed test CDN and records the estimated throughput in Mbps.
- Stored in the `bandwidth_mbps` column of `telemetry_measurements`.
- This lets us correlate latency spikes with bandwidth dips — if RTT jumps
  while bandwidth drops, the anomaly may be congestion rather than a gray failure.

**Experiment Best Practices:**
- Minimize heavy network usage (streaming, downloads) during fault injection runs.
- Note any known network activity in the experiment log.
- Use the bandwidth data post-hoc to filter or annotate results where congestion
  may have influenced measurements.

**Static Network Facts** (document once before experiments):
- ISP type and rated speed (e.g., "cable 300/20 Mbps")
- Router model and WiFi standard (e.g., "802.11ac, 5 GHz")
- Number of other devices typically on the network

**Node-Specific Observations:**
- **pi00-wifi** exhibits higher packet loss (~0.26% vs ~0.1% for pi01/pi02-wifi)
  and elevated WiFi retry count (~982 vs near-zero on Pi 5 nodes). All nodes are
  co-located in the same physical tower, so positioning is not the cause. **pi00-wifi
  is a Raspberry Pi 4** (Cypress CYW43455 WiFi chip) while pi01-wifi and pi02-wifi
  are **Raspberry Pi 5s** with newer wireless hardware. This hardware difference
  produces measurably higher baseline noise on pi00-wifi and is an important
  confounding variable when comparing WiFi detection results across experiments.
- LAN nodes (pi03-pi05) show 0% packet loss consistently; all are Pi 5s.

---

## Pre-Experiment Checklist

- [ ] Confirm 24h of gap-free telemetry for all 6 devices
- [ ] Revert `BASELINE_HOURS` from 28 → 24 on EC2 detector
- [ ] Restart detector — verify all 6 models retrain on clean baseline
- [ ] Deploy fault injection scripts to all 6 Pis
- [ ] Verify `tc netem` works on a Pi with a quick apply/clear test
- [ ] Confirm detector is actively scoring (anomaly_events accumulating)
- [ ] Note baseline false-alert rate (should be ~0 during clean period)
- [ ] Open Grafana dashboards: Anomaly Detection, Experiment/Fault Injection, Feature Window Explorer

---

## Experiment Design

We run **6 experiments** using a **2×3 factorial design** — every node is tested,
and each fault type is applied to both a LAN and a WiFi node. This enables direct
LAN vs. WiFi comparison for every fault type.

```
Fault Type        LAN Node      WiFi Node
──────────────────────────────────────────
Delay 100ms       pi03-lan      pi00-wifi
Packet loss 2%    pi04-lan      pi01-wifi
Full scenario     pi05-lan      pi02-wifi
```

Each experiment targets **one node** while all remaining nodes serve as controls.
Running both network types per fault type is critical for the research question:
*does the detector perform equally well on stable LAN vs. noisy WiFi links?*

---

### Experiment 1 — LAN Delay Injection (pi03-lan)

| Phase | Duration | Fault | Purpose |
|-------|----------|-------|---------|
| Pre-baseline | 3 min | None | Confirm normal scoring |
| **Delay** | **5 min** | **100ms ± 20ms** | Gray failure — elevated latency |
| Recovery | 3 min | None | Verify return to normal |

**Target:** `pi03-lan` via `eth0`
**Controls:** all other 5 nodes (no injection)

```bash
# On pi03-lan
sudo bash /opt/edge-agent/fault_injection/netem_apply.sh -i eth0 -d 100 -j 20
# ... wait 5 min ...
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i eth0
```

**What to measure:**
- MTTD: time from netem_apply → first `is_anomaly=true` for pi03-lan
- False positives on control nodes during injection window
- RTT jump magnitude: expected baseline ~39ms → ~139ms

---

### Experiment 2 — WiFi Delay Injection (pi00-wifi)

| Phase | Duration | Fault | Purpose |
|-------|----------|-------|---------|
| Pre-baseline | 3 min | None | Confirm normal scoring |
| **Delay** | **5 min** | **100ms ± 20ms** | Same fault on higher-variance network |
| Recovery | 3 min | None | Verify return to normal |

**Target:** `pi00-wifi` via `wlan0`
**Controls:** all other 5 nodes (no injection)

> ⚠️ **Hardware note:** `pi00-wifi` is a **Raspberry Pi 4** while all other nodes are
> **Raspberry Pi 5**. The Pi 4 uses a Cypress CYW43455 WiFi chip (older generation)
> vs the Pi 5's newer wireless hardware. Despite all nodes sitting in the same physical
> tower, pi00-wifi shows higher baseline packet loss (~0.26% vs ~0.1% for pi01/pi02-wifi)
> and elevated WiFi retry counts (~982 vs near-zero on Pi 5 nodes). This is a hardware
> capability difference, not a placement or interference issue.
>
> **Research implication:** This makes Experiment 2 more interesting — the detector must
> learn pi00-wifi's noisier baseline and still detect a 100ms injected delay on top of it.
> If MTTD for Experiment 2 is longer than Experiment 1, the Pi 4 baseline noise is a
> contributing factor alongside the general WiFi variance effect.

```bash
# On pi00-wifi
sudo bash /opt/edge-agent/fault_injection/netem_apply.sh -i wlan0 -d 100 -j 20
# ... wait 5 min ...
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i wlan0
```

**What to measure:**
- MTTD: compare with Experiment 1 — WiFi baseline is noisier (~53ms RTT avg), and pi00-wifi
  has higher baseline loss (~0.26%) vs clean LAN, so 100ms delay must stand out against more noise
- Does the per-device threshold correctly isolate pi00-wifi's Pi 4 baseline from pi01/pi02-wifi?
- Compare pi00-wifi MTTD vs pi01-wifi/pi02-wifi in Experiments 4 and 6 — any consistent gap?

---

### Experiment 3 — LAN Packet Loss (pi04-lan)

| Phase | Duration | Fault | Purpose |
|-------|----------|-------|---------|
| Pre-baseline | 3 min | None | Confirm normal scoring |
| **Packet loss** | **5 min** | **5%** | Test loss-based detection (higher than default 2% for stronger signal) |
| Recovery | 3 min | None | Verify return to normal |

**Target:** `pi04-lan` via `eth0`
**Controls:** all other 5 nodes (no injection)

```bash
# On pi04-lan
sudo bash /opt/edge-agent/fault_injection/netem_apply.sh -i eth0 -l 5
# ... wait 5 min ...
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i eth0
```

**What to measure:**
- Does the model detect loss anomalies (not just latency)?
- ICMP loss_pct should jump from 0% → ~5%
- May also cause DNS/HTTP failures (cascading effect)

---

### Experiment 4 — WiFi Packet Loss (pi01-wifi)

| Phase | Duration | Fault | Purpose |
|-------|----------|-------|---------|
| Pre-baseline | 3 min | None | Confirm normal scoring |
| **Packet loss** | **5 min** | **5%** | Same loss fault on WiFi — harder signal amid natural variation |
| Recovery | 3 min | None | Verify return to normal |

**Target:** `pi01-wifi` via `wlan0`
**Controls:** all other 5 nodes (no injection)

```bash
# On pi01-wifi
sudo bash /opt/edge-agent/fault_injection/netem_apply.sh -i wlan0 -l 5
# ... wait 5 min ...
sudo bash /opt/edge-agent/fault_injection/netem_clear.sh -i wlan0
```

**What to measure:**
- MTTD vs Experiment 3 (LAN) — does WiFi packet loss take longer to detect?
- WiFi already has some natural variance; model must discriminate 5% injected loss from baseline fluctuations
- Compare false positive rate on LAN controls during this WiFi experiment

---

### Experiment 5 — LAN Full Scenario (pi05-lan)

| Phase | Duration | Fault | Purpose |
|-------|----------|-------|---------|
| Baseline | 2 min | None | Clean reference |
| Delay | 5 min | 100ms ± 20ms | Latency fault |
| Recovery 1 | 2 min | None | Does model recover? |
| Packet loss | 3 min | 2% | Loss fault |
| Recovery 2 | 2 min | None | Final recovery |

**Target:** `pi05-lan` via `eth0`
**Controls:** all other 5 nodes (no injection)

```bash
# On pi05-lan — runs all phases automatically
sudo bash /opt/edge-agent/fault_injection/scenarios.sh eth0 | tee /tmp/scenario_$(date +%s).jsonl
```

**What to measure:**
- End-to-end automated scenario with ground truth timestamps
- Two distinct fault types in one run; recovery detection between faults
- Does detection of second fault (loss) come faster after model has seen the device before?

---

### Experiment 6 — WiFi Full Scenario (pi02-wifi)

| Phase | Duration | Fault | Purpose |
|-------|----------|-------|---------|
| Baseline | 2 min | None | Clean reference |
| Delay | 5 min | 100ms ± 20ms | Latency fault on WiFi |
| Recovery 1 | 2 min | None | Recovery |
| Packet loss | 3 min | 2% | Loss fault on WiFi |
| Recovery 2 | 2 min | None | Final recovery |

**Target:** `pi02-wifi` via `wlan0`
**Controls:** all other 5 nodes (no injection)

```bash
# On pi02-wifi — runs all phases automatically
sudo bash /opt/edge-agent/fault_injection/scenarios.sh wlan0 | tee /tmp/scenario_$(date +%s).jsonl
```

**What to measure:**
- Direct WiFi vs. LAN comparison for multi-fault scenario (Experiment 5 vs. 6)
- MTTD per fault type on WiFi — is there a consistent detection gap vs. LAN?
- Recovery time on WiFi vs. LAN

---

## Experiment Schedule

Run experiments with **30-minute gaps** between them so the detector fully recovers
and scoring windows don't overlap between experiments.

| Order | Time | Experiment | Node | Fault Type |
|-------|------|------------|------|------------|
| 1 | T+0 | LAN Delay | pi03-lan | 100ms delay |
| 2 | T+30min | WiFi Delay | pi00-wifi | 100ms delay |
| 3 | T+60min | LAN Loss | pi04-lan | 5% loss |
| 4 | T+90min | WiFi Loss | pi01-wifi | 5% loss |
| 5 | T+120min | LAN Full Scenario | pi05-lan | delay → loss |
| 6 | T+150min | WiFi Full Scenario | pi02-wifi | delay → loss |

**Total experiment window:** ~3.5 hours

---

## Data Collection

### Ground truth (save on each Pi)

```bash
# Manual experiments — log apply/clear timestamps
sudo bash netem_apply.sh -i eth0 -d 100 -j 20 | tee -a /tmp/ground_truth.jsonl
# ... wait ...
sudo bash netem_clear.sh -i eth0 | tee -a /tmp/ground_truth.jsonl
```

### After experiments — pull results from Postgres

```sql
-- MTTD calculation per experiment
SELECT device_id,
  MIN(event_ts) FILTER (WHERE is_anomaly) as first_detection,
  COUNT(*) FILTER (WHERE is_anomaly) as anomaly_count,
  COUNT(*) as total_scored
FROM anomaly_events
WHERE event_ts BETWEEN '<experiment_start>' AND '<experiment_end>'
  AND device_id = '<target_device>'
GROUP BY device_id;

-- False alert rate on control nodes
SELECT device_id, COUNT(*) FILTER (WHERE is_anomaly) as false_positives
FROM anomaly_events
WHERE event_ts BETWEEN '<experiment_start>' AND '<experiment_end>'
  AND device_id IN ('<control_1>', '<control_2>')
GROUP BY device_id;

-- Baseline false alert rate (24h before experiments)
SELECT device_id,
  COUNT(*) FILTER (WHERE is_anomaly) as false_alerts,
  ROUND(COUNT(*) FILTER (WHERE is_anomaly) / 24.0, 2) as per_hour
FROM anomaly_events
WHERE event_ts BETWEEN '<baseline_start>' AND '<experiment_start>'
GROUP BY device_id;
```

---

## Success Criteria

| Metric | Target | Notes |
|--------|--------|-------|
| MTTD (LAN delay) | < 5 min | 2–3 scoring windows (120s each) |
| MTTD (WiFi delay) | < 5 min | May be longer due to noise |
| MTTD (packet loss) | < 5 min | Loss features should spike |
| False alert rate (baseline) | < 0.5/hour | During clean 24h period |
| False positives (controls) | 0 | No alerts on non-injected nodes |
| Recovery detection | < 5 min | Model returns to normal scoring after clear |

---

## Phase 2 — Model Comparison: Isolation Forest vs EMA/Z-Score

### Motivation

Isolation Forest is a multivariate ML model — it considers all 9 features at once
but produces an opaque anomaly score. A natural question for the paper:
**Can a simple statistical baseline match an ML model for gray failure detection?**

We compare against an **Exponential Moving Average (EMA) with Z-score** detector —
a univariate, per-metric approach that any network operator could implement.

### How EMA/Z-Score Works

For each metric (RTT avg, loss, DNS latency, HTTP latency):

1. Maintain a running EMA: `ema_t = α * x_t + (1 - α) * ema_{t-1}`
2. Maintain a running EMA of squared deviations (for σ)
3. Compute Z-score: `z = (x_t - ema) / σ`
4. Flag anomaly if **any** metric exceeds `|z| > k` (default k=3)

Parameters:
- `α = 0.1` (smoothing factor — ~10-sample effective window)
- `k = 3.0` (Z-score threshold — 3 standard deviations)
- Warm-up period: 60 samples (~10 min) before scoring begins

### Implementation Plan

- New file: `control-plane/detector/ema_detector.py`
- Same DB table (`anomaly_events`) with `model_version = "ema-zscore-v1"`
- Same scoring interval (120s), same feature windows for fair comparison
- Runs as a separate process or integrated into the existing detector loop
- No new dependencies (pure NumPy)

### Comparison Experiment Design

**Run both detectors simultaneously** on the same fault injection experiments.
Each writes to `anomaly_events` with its own `model_version`, allowing direct
comparison from the same time window.

| Dimension | Isolation Forest | EMA/Z-Score |
|-----------|-----------------|-------------|
| Model type | Multivariate ML | Univariate statistical |
| Features used | 9 (combined) | 4 independently (RTT, loss, DNS, HTTP) |
| Training | 24h baseline batch | Online warm-up (~10 min) |
| Threshold | Learned (percentile on baseline scores) | Fixed (k=3 σ) |
| Output | Anomaly score (0–1) | Max Z-score across metrics |
| Explainability | Low — single score | High — which metric, how many σ |
| Dependencies | scikit-learn | NumPy only |

### Metrics to Compare

| Metric | Definition | Better = |
|--------|-----------|----------|
| MTTD | Fault inject start → first `is_anomaly=true` | Lower |
| False alert rate | Anomalies/hour during clean baseline | Lower |
| True positive rate | % of fault windows correctly flagged | Higher |
| Recovery time | Last `is_anomaly=true` → fault cleared | Lower (closer to actual clear) |
| LAN vs WiFi gap | MTTD difference between network types | Smaller = more robust |

### Expected Hypotheses

1. **MTTD:** Isolation Forest may be slower (needs full window) vs EMA reacting immediately — but EMA may produce more false alerts on WiFi due to natural variance.
2. **False alerts:** Isolation Forest should have fewer false alerts because it learns the multivariate baseline distribution. EMA may fire on WiFi jitter spikes.
3. **Loss detection:** EMA should detect packet loss faster (direct metric monitoring) vs Isolation Forest where loss is 1 of 9 features.
4. **Explainability:** EMA wins — it tells you *which* metric triggered. Isolation Forest just says "anomalous".
5. **Pi 4 vs Pi 5 effect:** pi00-wifi (Pi 4) may show longer MTTD and/or higher false alert rate vs pi01-wifi / pi02-wifi (Pi 5) on identical faults. If per-device thresholds are working correctly, the models should absorb pi00-wifi's noisier baseline — any persistent MTTD gap becomes evidence of hardware capability as a detection confound.

### Paper Narrative

> "We evaluate two approaches to gray failure detection in edge networks:
> an Isolation Forest model trained on multivariate windowed features, and
> a lightweight EMA/Z-score detector operating on individual metrics.
> Our experiments show [results] across LAN and WiFi network types,
> suggesting that [conclusion about when ML adds value vs simple statistics]."

---

## Post-Experiment Analysis

1. **Calculate MTTD** for each experiment using ground truth timestamps vs first anomaly event — **per model**
2. **Compare LAN vs WiFi** detection sensitivity — does WiFi's higher variance make detection harder? Does it affect both models equally?
3. **Model comparison table** — side-by-side MTTD, false alert rate, true positive rate for Isolation Forest vs EMA/Z-score
4. **Feature analysis** — which features contributed most to Isolation Forest detection (use Feature Window Explorer dashboard); which metrics triggered EMA alerts
5. **Anomaly score trajectory** — plot both models' scores over time across fault/recovery phases
6. **WiFi robustness** — does EMA's per-metric approach suffer more false alerts on noisy WiFi links?
7. **Pi 4 vs Pi 5 hardware analysis** — compare Exp 01/02 (delay), Exp 03/04 (loss), Exp 05/06 (full) LAN results against pi00-wifi specifically. If pi00-wifi MTTD consistently lags pi01-wifi and pi02-wifi, report this as a hardware-driven detection sensitivity difference. Both models should be assessed.
8. **Write up results** for blog post and paper using data from Grafana dashboards

---

## Commands Quick Reference

```bash
# Deploy scripts (run from local machine)
for host in pi00-wifi pi01-wifi pi02-wifi pi03-lan pi04-lan pi05-lan; do
  scp -i ~/.ssh/remote-key.pem -r edge-agent/fault_injection/ kingnathanal@$host:/tmp/fault_injection/
  ssh -i ~/.ssh/remote-key.pem kingnathanal@$host 'sudo mkdir -p /opt/edge-agent/fault_injection && sudo cp /tmp/fault_injection/* /opt/edge-agent/fault_injection/ && sudo chmod +x /opt/edge-agent/fault_injection/*.sh'
done

# Revert detector baseline
ssh ubuntu@ec2 "sudo sed -i 's/BASELINE_HOURS=28/BASELINE_HOURS=24/' /opt/control-plane/detector/.env && sudo systemctl restart detector"

# Monitor scoring in real-time
ssh ubuntu@ec2 "sudo journalctl -u detector -f"

# Quick anomaly check
ssh ubuntu@ec2 "sudo -u postgres psql -d telemetry -c \"
  SELECT device_id, anomaly_score, threshold, is_anomaly, event_ts
  FROM anomaly_events WHERE event_ts > now() - INTERVAL '10 minutes'
  ORDER BY event_ts DESC;\""
```
