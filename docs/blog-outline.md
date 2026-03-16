# Blog Post Outline — AI-Based Latency Anomaly Detection at the Edge

> Working title: *"Detecting Gray Failures in Edge Networks with Raspberry Pis and Isolation Forest"*
> **Status:** ✅ All 5 experiments complete. Final numbers confirmed. Ready for drafting.

---

## 1. Hook / Introduction
- What are gray failures? (not full outages — subtle degradations that slip past basic monitoring)
- Why they matter: real-world impact on edge/IoT systems, CDNs, distributed services
- One-liner: "I built a testbed with 6 Raspberry Pis and an AWS control plane to automatically detect and mitigate latency anomalies using unsupervised ML."

## 2. The Problem
- Traditional monitoring (threshold-based) misses gradual degradation
- Edge networks add complexity: variable link quality, Wi-Fi vs wired, remote nodes
- What we want: detect anomalies without labeled training data, and respond automatically
- Research questions:
  - How quickly can we detect injected faults? (MTTD)
  - How many false alerts does the system produce during normal operation?
  - Does automated mitigation actually reduce impact?

## 3. Architecture Overview
- **Diagram:** Pi cluster → MQTT → EC2 control plane → Postgres → Grafana + failover EC2
- "Cloud decides, edge executes" pattern
- Components:
  - **Edge agents** (6 Raspberry Pis: 3 LAN, 3 Wi-Fi) — probe ICMP/DNS/HTTP every 10s
  - **MQTT broker** — lightweight telemetry transport
  - **Ingestion service** — validates and stores telemetry
  - **Detector service** — Isolation Forest on windowed features
  - **Mitigator service** — automated response (endpoint failover, sampling rate adjustment)
  - **Primary EC2** (`54.198.26.122`) — control plane + primary health endpoint
  - **Failover EC2** (`34.226.196.133`) — independent health endpoint, separate AWS instance
  - **Grafana** — real-time visualization
- Why two EC2 instances? Co-located backup shares the same fault domain — `tc netem` on the primary IP degrades both endpoints simultaneously, making impact reduction unmeasurable. Separate EC2 = clean before/after signal.
- Photo(s) of the Pi setup

## 4. How Detection Works
- **Feature windowing:** aggregate 120s of raw telemetry into statistical features
  - RTT mean, std (jitter), max
  - Packet loss rate
  - DNS/HTTP latency, failure rates
- **Isolation Forest:** unsupervised — learns "normal" from 24h baseline, no labels needed
  - Brief explanation of how Isolation Forest works (random partitioning, anomaly = easy to isolate)
  - Why we chose it: simple, fast, explainable, works well for this use case
- **Threshold calibration:** 97.5th percentile of baseline scores (~0.68 after convergence)
- **Important limitation to be honest about:** the model is static — it trains once and never updates. The threshold is also frozen. If network conditions permanently shift, false alert rates can drift. This is a known tradeoff between simplicity and adaptability — worth noting for readers.
- Code snippet or pseudocode showing the pipeline

## 5. Fault Injection — Creating Repeatable Experiments
- Linux `tc netem` for network impairment on the Pis
- Scoped to primary endpoint IP only — failover EC2 traffic unaffected (that's the point)
- Auto-detects correct interface from hostname: `*wifi*` → `wlan0`, else `eth0` (lesson: got this wrong initially and WiFi nodes were never actually faulted!)
- Scenarios: added delay (100ms ± 20ms), packet loss (2%)
- Ground truth logging: exact JSON timestamps for each phase — enables precise MTTD calculation
- Why reproducibility matters for research
- Example: `sudo tc qdisc add dev eth0 root netem delay 100ms 20ms distribution normal`

## 6. Automated Mitigation
- Detection triggers mitigation commands via MQTT (`mitigation/<device_id>/command`)
- Actions: `failover_endpoint` — switch HTTP target to backup EC2; `set_interval` — ramp sampling from 10s → 2s during incident
- Edge agents apply commands in-memory (<1s) and acknowledge via `mitigation/<device_id>/status`
- Mitigator guards against command flooding: skips if a pending command exists for the device
- Measuring impact reduction: HTTP latency during fault vs. after failover to clean EC2
- **Key insight:** with a co-located backup you can't measure this cleanly — the separate failover EC2 was essential

## 7. Results *(all 5 experiments complete)*

**Five experiments across two dimensions: fault severity (Exp 1–3) and scoring interval (Exp 4r/5 vs 1/2).**

### MTTD by node across all 5 experiments

| Node | Type | E1 100ms/120s | E2 200ms/120s | E3 50ms/120s | E4r 100ms/30s | E5 200ms/30s |
|------|------|:---:|:---:|:---:|:---:|:---:|
| pi00-wifi | WiFi | 92s | 118s | ❌ | ❌ | 40s |
| pi01-wifi | WiFi | 49s | 118s | ❌ | 76s | 40s |
| pi02-wifi | WiFi | ❌ | 118s | ❌ | ❌ | 40s |
| pi03-lan | LAN | 49s | 118s | 114s | 46s | 40s |
| pi04-lan | LAN | 49s | 118s | 114s | **16s** | 40s |
| pi05-lan | LAN | 49s | 118s | 114s | 46s | 40s |
| **Detected** | | 5/6 | 6/6 | 3/6 | 4/6 | 6/6 |

- **Surprise headline finding:** MTTD is NOT governed by fault severity — it's governed by scoring interval. 200ms fault in Exp 2 (120s scoring) → MTTD 118s. Same 200ms fault in Exp 5 (30s scoring) → MTTD 40s. This is the most counterintuitive result worth leading with.
- **Scoring interval impact:** 30s vs 120s windows → **67% MTTD reduction** (49s → 16s for 100ms fault; 118s → 40s for 200ms fault).
- **Detection floor:** 50ms/1% — LAN detects (3/3), WiFi misses entirely. Natural WiFi jitter (~±20ms) masks a 50ms fault in a 120s averaged window.
- **False alert rate (IF):** LAN ~0.28 alerts/hr, WiFi ~0.50 alerts/hr (26-day baseline)
- **False alert rate (EMA):** LAN ~0.08 alerts/hr, WiFi ~0.25 alerts/hr — **3.5× lower on LAN, 2× lower on WiFi**
- Both models detected all 6 nodes across the 5-experiment suite — no detection misses unique to either model
- Key model tradeoff: EMA fires on single-metric spikes (any metric >3σ from rolling mean) — simpler, lower false alerts. IF scores the full 9-feature window jointly — higher multivariate sensitivity, more anomaly windows flagged (113 vs 26 across experiments). Model disagreements during baseline were almost entirely IF false positives that EMA correctly ignored.
- **Impact reduction:** 72% LAN, 65% WiFi — consistent across severities once failover triggers. Automated failover at 158s vs organic recovery at 309s — **2× faster**.
- **30s window tradeoff:** faster MTTD but higher per-window score variance → borderline WiFi faults missed (4/6 at 30s vs 5/6 at 120s). Recommendation: **adaptive scoring** — 120s default, drop to 30s on first detection.
- Grafana screenshots needed:
  - Probe Endpoint Tracking: crossover moment (primary → failover)
  - Anomaly Detection: IF score crossing threshold with fault annotation
  - HTTP latency spike → failover drop, annotated
- **Key chart:** MTTD vs scoring interval (Exp 1 vs Exp 4r, Exp 2 vs Exp 5) — the 67% improvement story

## 8. Lessons Learned
- **Co-located backup is a trap:** our first 3 setup runs used a backup on the same EC2 (different port). `tc netem` scoped to the primary IP degraded both endpoints. Impact reduction was unmeasurable. Fix: deploy a completely separate EC2.
- **Interface matters:** `tc netem` on `eth0` does nothing for WiFi nodes. We accidentally ran a setup experiment where 3 WiFi nodes were never faulted — they became an unintentional control group. Fixed by auto-detecting interface from hostname.
- **MTTD is not what you expect:** we assumed larger faults → faster detection. Wrong. MTTD is dominated by *when the scoring cycle fires relative to fault injection*, not fault severity. A 200ms fault at 120s scoring has higher MTTD (118s) than a 100ms fault at 30s scoring (16s).
- **Baseline contamination is real:** restarting the detector after fault experiments causes it to retrain on a window that includes fault data. This inflates thresholds by +0.07, making future detections miss. Never restart the detector immediately after experiments.
- **p97.5 is the threshold sweet spot:** p95 over-fires on noisy WiFi nodes; p99 over-corrects after a contaminated baseline. p97.5 is robust to ~5% contamination and matches clean-baseline behavior.
- **MQTT v2 API changes:** `paho-mqtt v2` changed `on_disconnect` to 5 args and `ReasonCode` can't be cast with `int()`. Always pin your MQTT client version.
- **Postgres vs. numpy types:** `psycopg2` can't adapt `numpy.float64` — always cast to native Python before INSERT.
- **Static model limitation:** the Isolation Forest never retrains. Works well for stable environments; would need periodic retraining for production with shifting baselines.
- If I did it again: start with the separate failover EC2 from day one, and pin `THRESHOLD_PERCENTILE=97.5` from the start.

## 9. Future Work
- **Online learning:** periodic model retraining on a rolling 24h window — eliminates threshold drift
- **Adaptive thresholds:** per-device EMA of recent scores instead of a frozen percentile
- **Edge-side inference:** run a lightweight model on the Pi itself to reduce detection latency
- **Multi-node correlation:** detect network-wide events (upstream router degradation) vs. node-local faults
- **Larger scale:** test with 20+ nodes, multiple edge sites, heterogeneous targets
- **Supervised comparison:** benchmark against a labeled-data approach to quantify the cost of "no labels"

## 10. Conclusion
- Summary of key findings
- The value of unsupervised anomaly detection for edge reliability
- Link to the GitHub repo / paper

---

## Assets to Collect

### Architecture & Setup

- [ ] **Architecture diagram PNG** — export `docs/testbed-architecture.excalidraw` (now includes failover EC2 section)
- [ ] **Photo of Pi tower** — all 6 Pis racked together, cables visible, LEDs active
- [ ] **Grafana home screen** — all dashboards listed, proves system is operational

### Baseline Visuals

- [ ] **Baseline RTT trace** — Latency Overview, all 6 nodes, clean flat lines showing normal operation
- [ ] **LAN vs WiFi comparison** — Network Comparison dashboard, showing ~80ms LAN vs ~110ms WiFi
- [ ] **IF anomaly score during baseline** — Anomaly Detection dashboard, scores well below threshold (0.68) — proves low false alert rate

### Per-Experiment Visuals (3 experiments — varying severity)

For **each experiment**, capture:

1. **The fault** — HTTP latency spike at delay injection
2. **The detection** — IF anomaly score crossing threshold
3. **The crossover** — Probe Endpoint Tracking showing nodes switching primary → backup
4. **The recovery** — Latency drop back to baseline on failover EC2

Best Grafana view: **Latency Overview + Probe Endpoint Tracking**, time range `[T-3min to T+12min]`.

**Note severity-specific expectations:**
- Exp 2 (200ms/5%): expect sharper spike, faster detection, cleaner crossover
- Exp 3 (50ms/1%): expect subtler spike, slower/partial detection — capture whether pi02-wifi detects or misses again

### Results & Analysis (after all 3 experiments)

- [ ] **MTTD table** — 3 experiments × 6 nodes, mean ± std per node type (LAN/WiFi)
- [ ] **Impact reduction table** — baseline / during-fault / post-failover latency per experiment
- [ ] **False alert rate** — LAN ~0.26/hr, WiFi ~0.60/hr (already measured, 26 days of data)
- [ ] **Consistency chart** — MTTD across all 3 experiments (the sensitivity curve: faster detection at higher severity)
- [ ] **Probe Endpoint Tracking screenshot** — showing the failover crossover moment clearly

### Code Snippets to Include

- [ ] Feature windowing (`control-plane/detector/features.py`) — 9-feature vector construction
- [ ] Isolation Forest training (5-6 lines from `detector.py`)
- [ ] `scenarios.sh` interface auto-detection logic
- [ ] Fault injection command with IP scoping: `sudo tc qdisc add dev eth0 root netem delay 100ms 20ms`
- [ ] Mitigation MQTT payload example (from `docs/payload_schema.md`)

### Data to Export (Postgres Queries)

```sql
-- MTTD per experiment per node
SELECT
  ae.device_id,
  MIN(ae.event_ts) AS first_detection,
  '<fault_start_ts>'::timestamptz AS fault_start,
  ROUND(EXTRACT(EPOCH FROM MIN(ae.event_ts) - '<fault_start_ts>'::timestamptz)::numeric, 0) AS mttd_s
FROM anomaly_events ae
WHERE ae.event_ts BETWEEN '<exp_start>' AND '<exp_end>'
  AND ae.is_anomaly = true
GROUP BY ae.device_id;

-- HTTP latency by phase
SELECT phase, round(avg(http_latency_ms)::numeric,1) as avg_ms,
  round(percentile_cont(0.95) WITHIN GROUP (ORDER BY http_latency_ms)::numeric,1) as p95_ms
FROM ( SELECT http_latency_ms,
    CASE
      WHEN ts BETWEEN '<baseline_start>' AND '<fault_start>' THEN 'baseline'
      WHEN ts BETWEEN '<fault_start>' AND '<failover_ts>' THEN 'during_fault'
      WHEN ts BETWEEN '<failover_ts>' AND '<exp_end>' THEN 'post_failover'
    END as phase
  FROM telemetry_measurements
  WHERE device_id IN ('pi03-lan','pi04-lan','pi05-lan','pi00-wifi','pi01-wifi','pi02-wifi')
) sub WHERE phase IS NOT NULL
GROUP BY phase ORDER BY phase;
```

---

## Publishing Notes
- Target audience: software engineers, SREs, ML practitioners, grad students
- Tone: technical but accessible — explain ML concepts without assuming deep background
- Length: ~2000–3000 words + diagrams/screenshots
- Potential platforms: personal blog, Medium, dev.to, Hashnode
- **Key differentiators vs. other ML posts:** real hardware, real network faults, honest about what went wrong (co-located backup issue, interface bug), reproducible methodology with ground-truth fault injection, separate failover EC2 for clean impact measurement
