# Blog Post Outline — AI-Based Latency Anomaly Detection at the Edge

> Working title: *"Detecting Gray Failures in Edge Networks with Raspberry Pis and Isolation Forest"*
> **Status:** Outline updated post-Exp 4. Final numbers pending 3 canonical experiments (~22:00–23:44Z tonight).

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

## 7. Results *(fill after 3 canonical experiments complete)*
- **Experiments:** 3 identical replications, ~45 min apart, all 6 nodes, same parameters
- **MTTD:** [X]s mean, [Y]s std across 3 runs and 6 nodes — *preliminary from setup: ~104s on LAN nodes*
- **False alert rate:** LAN ~0.26 alerts/hr, WiFi ~0.60 alerts/hr (WiFi naturally jitterier)
- **Impact reduction:** [Z]% mean — *preliminary from setup run: ~72% (80ms baseline → 278ms fault → 78ms post-failover)*
- **LAN vs Wi-Fi:** LAN detected reliably; WiFi higher false alert rate due to natural wireless variance
- Grafana screenshots showing:
  - Probe Endpoint Tracking: the crossover moment when nodes switch from primary → failover
  - Anomaly Detection: IF score crossing threshold with fault annotation
  - HTTP latency before/during/after with failover marker
- **Consistency claim:** standard deviation across 3 runs < [threshold] — this is the reproducibility argument

## 8. Lessons Learned
- **Co-located backup is a trap:** our first 3 setup runs used a backup on the same EC2 (different port). Looked fine in testing — but `tc netem` scoped to the primary IP degraded both endpoints. Impact reduction was unmeasurable. The fix: deploy a completely separate EC2.
- **Interface matters:** `tc netem` applied to `eth0` does nothing for WiFi nodes. We accidentally ran an entire experiment where 3 WiFi nodes were never faulted — they became an unintentional control group. Fixed by auto-detecting interface from hostname.
- **MQTT v2 API changes:** `paho-mqtt v2` changed the `on_disconnect` signature (5 args vs 4) and `ReasonCode` behavior. Easy to miss in upgrade — always pin your MQTT client version.
- **Postgres vs. numpy types:** `psycopg2` can't adapt `numpy.float64` — always cast to native Python types before INSERT.
- **Static model limitation:** the Isolation Forest never retrains. Works well for stable environments; would need periodic retraining for production deployments with shifting baselines.
- What was harder than expected: getting repeatable, consistent experiments across all 6 nodes simultaneously
- If I did it again: start with the separate failover EC2 from day one

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

### Per-Experiment Visuals (3 canonical experiments)

For **each experiment**, capture:

1. **The fault** — HTTP latency spiking at delay injection (~80ms → ~280ms)
2. **The detection** — IF anomaly score crossing threshold (score ~0.77 > threshold ~0.68)
3. **The crossover** — Probe Endpoint Tracking dashboard showing nodes switching from `primary` → `backup`
4. **The recovery** — HTTP latency dropping back to ~80ms on the failover EC2

Best Grafana view: **Latency Overview + Probe Endpoint Tracking**, time range `[T-3min to T+12min]`.

### Results & Analysis (after all 3 experiments)

- [ ] **MTTD table** — 3 experiments × 6 nodes, mean ± std per node type (LAN/WiFi)
- [ ] **Impact reduction table** — baseline / during-fault / post-failover latency per experiment
- [ ] **False alert rate** — LAN ~0.26/hr, WiFi ~0.60/hr (already measured, 26 days of data)
- [ ] **Consistency chart** — MTTD standard deviation across 3 runs (the reproducibility claim)
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
