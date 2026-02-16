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

## Assets to Collect During Experiments
- [ ] Photo(s) of Raspberry Pi cluster setup
- [ ] Architecture diagram (clean version for the blog)
- [ ] Grafana screenshots: baseline, anomaly detection, mitigation
- [ ] Result tables: MTTD per fault type, false alert rate, impact reduction
- [ ] Code snippets: feature windowing, Isolation Forest training, mitigation flow
- [ ] Timeline graphic of a full experiment run (baseline → fault → detection → mitigation → recovery)

## Publishing Notes
- Target audience: software engineers, SREs, ML practitioners, grad students
- Tone: technical but accessible — explain ML concepts without assuming deep background
- Length: ~2000-3000 words + diagrams/screenshots
- Potential platforms: personal blog, Medium, dev.to, Hashnode
