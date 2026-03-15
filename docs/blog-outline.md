# Blog Post Outline — AI-Based Latency Anomaly Detection at the Edge

> Working title: *"Detecting Gray Failures in Edge Networks with Raspberry Pis and Isolation Forest"*

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
- **Diagram:** Pi cluster → MQTT → EC2 control plane → Postgres → Grafana
- "Cloud decides, edge executes" pattern
- Components:
  - **Edge agents** (6 Raspberry Pis: 3 LAN, 3 Wi-Fi) — probe ICMP/DNS/HTTP every 10s
  - **MQTT broker** — lightweight telemetry transport
  - **Ingestion service** — validates and stores telemetry
  - **Detector service** — Isolation Forest on windowed features
  - **Mitigator service** — automated response (endpoint failover, sampling rate adjustment)
  - **Grafana** — real-time visualization
- Photo(s) of the Pi setup

## 4. How Detection Works
- **Feature windowing:** aggregate 120s of raw telemetry into statistical features
  - RTT mean, std (jitter), max
  - Packet loss rate
  - DNS/HTTP latency, failure rates
- **Isolation Forest:** unsupervised — learns "normal" from 24h baseline, no labels needed
  - Brief explanation of how Isolation Forest works (random partitioning, anomaly = easy to isolate)
  - Why we chose it: simple, fast, explainable, works well for this use case
- **Threshold calibration:** percentile-based on baseline scores
- Code snippet or pseudocode showing the pipeline

## 5. Fault Injection — Creating Repeatable Experiments
- Linux `tc netem` for network impairment on the Pis
- Scenarios: added delay, jitter, packet loss
- Ground truth logging: exact start/end timestamps for each fault
- Why reproducibility matters for research
- Example: `sudo tc qdisc add dev eth0 root netem delay 100ms 20ms`

## 6. Automated Mitigation
- Detection triggers mitigation commands via MQTT
- Actions: failover to backup endpoint, increase sampling rate during anomalies
- Edge agents apply commands and acknowledge
- Measuring impact reduction: latency before vs after mitigation

## 7. Results
- **MTTD:** how fast did the system detect each fault type?
  - Theoretical: 2-4 minutes; actual measured values from experiments
- **False alert rate:** alerts/hour during clean baseline
- **Impact reduction:** mean/p95 latency improvement after mitigation
- Grafana screenshots showing:
  - Normal baseline telemetry
  - Anomaly detection firing during fault injection
  - Mitigation kicking in and recovering
- LAN vs Wi-Fi comparison — does link type affect detection performance?
- Tables/charts summarizing experiment results

## 8. Lessons Learned
- What worked well
- What was harder than expected
- Practical challenges (Pi networking quirks, MQTT reliability, etc.)
- If I did it again, what would I change?

## 9. Future Work
- More sophisticated models (ensemble methods, online learning)
- Edge-side inference (run lightweight model on the Pi itself)
- Multi-node correlation (detect network-wide events, not just per-device)
- Integration with real production monitoring stacks

## 10. Conclusion
- Summary of key findings
- The value of unsupervised anomaly detection for edge reliability
- Link to the GitHub repo / paper

---

## Assets to Collect

### Architecture & Setup (Collect Before Experiments)

- [ ] **Architecture diagram PNG** — export `docs/testbed-architecture.excalidraw` to PNG via excalidraw.com
- [ ] **Photo of Pi tower** — all 6 Pis racked together, cables visible, ideally with LEDs active
- [ ] **Grafana home screen** — showing all dashboards listed, proves system is operational
- [ ] **Node status screenshot** — Latency Overview dashboard, all 6 nodes active, last 10 min

### Baseline Visuals (Collect Before Experiments)

- [ ] **48h baseline RTT trace** — Latency Overview, all 6 devices, clean flat lines showing normal operation
- [ ] **LAN vs WiFi comparison** — Network Comparison dashboard, box plots or distributions showing ~39ms LAN vs ~54ms WiFi
- [ ] **Pi 4 vs Pi 5 baseline difference** — pi00-wifi vs pi01-wifi side-by-side (packet loss, retry counts) — illustrates hardware confound
- [ ] **IF anomaly score during baseline** — Anomaly Detection dashboard, 24h view, scores well below threshold — proves low false alert rate before experiments

### Per-Experiment Visuals (Collect During Each of 6 Experiments)

For **each experiment**, capture a 3-panel screenshot set:

1. **The fault** — RTT or loss metric spiking with a visible inflection point at injection time
2. **The detection** — anomaly score crossing threshold; include both IF and EMA in one frame if possible
3. **The recovery** — score returning to baseline after `netem_clear.sh`

Best Grafana view: **Model Comparison dashboard**, set time range to `[T-3min to T+12min]` around each experiment.

### Results & Analysis (Collect After All Experiments)

- [ ] **MTTD bar chart** — 6 experiments × 2 models = 12 bars, grouped by experiment. This is the headline result figure.
- [ ] **LAN vs WiFi MTTD comparison** — grouped bar: delay/loss/full × LAN/WiFi
- [ ] **False alert rate comparison** — IF vs EMA, per node type (LAN / WiFi / Pi4-WiFi)
- [ ] **Feature importance heatmap** — Feature Window Explorer: which features triggered during delay vs loss faults
- [ ] **Full scenario timeline** — Exp 05 or 06, annotated with fault phases, showing both detection events and recovery
- [ ] **Mitigation before/after** — RTT before and after failover command applied (if mitigation triggers)
- [ ] **Model agreement table** — how often did IF and EMA agree vs disagree, and what happened in disagreements

### Code Snippets to Include

- [ ] Feature windowing (`control-plane/detector/features.py`) — the 9-feature vector construction
- [ ] Isolation Forest training call (5-6 lines from `detector.py`)
- [ ] EMA/Z-score scoring logic (the core scoring loop from `ema_detector.py`)
- [ ] Fault injection command: `sudo tc qdisc add dev wlan0 root netem delay 100ms 20ms`
- [ ] Mitigation payload example (from `docs/payload_schema.md`)

### Data to Export for Charts (Postgres Queries)

```sql
-- MTTD per experiment (fill in ground truth timestamps after each run)
SELECT
  ae.device_id,
  ae.model_version,
  MIN(ae.event_ts) AS first_detection,
  -- subtract fault_start_ts from ground truth log
  EXTRACT(EPOCH FROM MIN(ae.event_ts) - '<fault_start_ts>'::timestamptz) AS mttd_seconds
FROM anomaly_events ae
WHERE ae.event_ts BETWEEN '<exp_start>' AND '<exp_end>'
  AND ae.device_id = '<target_node>'
  AND ae.is_anomaly = true
GROUP BY ae.device_id, ae.model_version;

-- False alert rate during baseline (alerts per hour, per model)
SELECT
  model_version,
  device_id,
  COUNT(*) FILTER (WHERE is_anomaly) AS anomaly_count,
  EXTRACT(EPOCH FROM (MAX(event_ts) - MIN(event_ts))) / 3600.0 AS hours_observed,
  ROUND(COUNT(*) FILTER (WHERE is_anomaly) /
    NULLIF(EXTRACT(EPOCH FROM (MAX(event_ts) - MIN(event_ts))) / 3600.0, 0), 2)
    AS alerts_per_hour
FROM anomaly_events
WHERE event_ts BETWEEN '<baseline_start>' AND '<baseline_end>'
GROUP BY model_version, device_id
ORDER BY model_version, device_id;
```

---

## Publishing Notes
- Target audience: software engineers, SREs, ML practitioners, grad students
- Tone: technical but accessible — explain ML concepts without assuming deep background
- Length: ~2000-3000 words + diagrams/screenshots
- Potential platforms: personal blog, Medium, dev.to, Hashnode
- **Key differentiators vs. other ML posts:** real hardware, real network faults, two-model comparison, LAN vs WiFi analysis, Pi 4 vs Pi 5 hardware confound
