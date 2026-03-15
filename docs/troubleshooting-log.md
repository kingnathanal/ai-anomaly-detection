# Troubleshooting Log — Edge AI Anomaly Detection Testbed

> A chronological record of issues encountered during the build-out and early
> operation of the testbed. Written for future reference, the project blog, and
> anyone reproducing this setup.

---

## Issue #1 — Grafana 12 Rejects Empty Contact-Point Email

| Field | Detail |
|-------|--------|
| **Date** | 2026-02-16 |
| **Severity** | Service outage (Grafana) |
| **Component** | Grafana alerting provisioning |
| **Symptom** | Grafana refused to start after deploying `alerts.yml`. Journal showed a validation error about an empty email address in the contact-point configuration. |
| **Root Cause** | Grafana 12 added strict validation for provisioned alerting resources. Our `alerts.yml` included a `contactPoints` section with an empty `addresses: ""` field, which older versions silently accepted but Grafana 12 rejects at startup. |
| **Fix** | Removed the `contactPoints` and `policies` sections from `alerts.yml` entirely, relying on Grafana's built-in default contact point. Alert notification channels can be configured later through the UI. |
| **Lesson** | Always test provisioning YAML against the exact Grafana version running in production. Grafana's unified alerting validation tightened significantly in v12. |

---

## Issue #2 — Experiment Dashboard LATERAL JOIN Syntax Error

| Field | Detail |
|-------|--------|
| **Date** | 2026-02-16 |
| **Severity** | Dashboard panel error |
| **Component** | `experiment-fault-injection.json` — Average MTTD panel |
| **Symptom** | Panel displayed "pq: syntax error near LATERAL". |
| **Root Cause** | The SQL query used a bare `LATERAL (...)` subquery without a preceding `JOIN` keyword and without the required `ON true` clause. PostgreSQL requires the full syntax: `... JOIN LATERAL (...) sub ON true`. |
| **Fix** | Added `JOIN` before `LATERAL` and `ON true` after the closing alias. Redeployed the corrected dashboard JSON. |
| **Lesson** | `LATERAL` subqueries in PostgreSQL **must** be preceded by `JOIN` (or `LEFT JOIN LATERAL`) and followed by `ON true` when there is no real join condition. This is different from some other SQL dialects. |

---

## Issue #3 — 13-Hour Data Gap: Internet Outage + paho-mqtt v2 Callback Crash

| Field | Detail |
|-------|--------|
| **Date** | 2026-02-16 (discovered ~21:30 UTC) |
| **Severity** | Full data pipeline outage (~13 hours) |
| **Component** | Edge agents (`agent.py`) on all 6 Raspberry Pis |
| **Symptom** | No telemetry rows in Postgres for ~13 hours despite all 6 `edge-probe` systemd services reporting `active (running)`. Agents appeared healthy — the main loop kept executing and logging "telemetry published" — but no messages reached the MQTT broker. |

### Timeline

| Time (EST) | Event |
|------------|-------|
| ~03:46 | Home internet outage; all 6 Pis lose connectivity to EC2 MQTT broker. |
| ~03:46 | paho-mqtt network loop detects TCP disconnect and invokes `on_disconnect()`. |
| ~03:46 | `on_disconnect()` crashes: `TypeError: on_disconnect() takes from 3 to 4 positional arguments but 5 were given`. The MQTT background thread dies silently. |
| ~03:46–08:45 | Internet restores at some point, but the MQTT thread is dead. `client.publish()` accepts messages into a local queue but never transmits them. The agent's main loop sees no error. |
| 08:45 | Last telemetry row written (from messages queued before the crash). |
| ~21:30 | Issue discovered during investigation. |

### Root Cause

The agent created its MQTT client with **`CallbackAPIVersion.VERSION2`** (paho-mqtt v2.x), but the `on_disconnect` callback used the **v1 signature** (3–4 positional args). In v2, paho passes **5 positional arguments**: `(client, userdata, disconnect_flags, reason_code, properties)`. The signature mismatch caused a `TypeError` that killed the MQTT network-loop thread. Because paho-mqtt runs the network loop in a daemon thread and `publish()` doesn't check connection liveness, the main telemetry loop continued running indefinitely with no indication of failure.

### Fix

Updated both `on_connect` and `on_disconnect` to accept v2-style arguments:

```python
# BEFORE (broken)
def on_disconnect(client, _userdata, rc=None):
    if rc != 0:
        log.warning("mqtt unexpected disconnect rc=%s", rc)

# AFTER (fixed)
def on_disconnect(client, _userdata, _flags=None, reason_code=None, _properties=None):
    is_failure = False
    if reason_code is not None:
        if hasattr(reason_code, 'is_failure'):
            is_failure = reason_code.is_failure
        elif reason_code != 0:
            is_failure = True
    if is_failure:
        log.warning("mqtt unexpected disconnect rc=%s, will reconnect", reason_code)
```

Deployed the fix to all 6 Pis and restarted `edge-probe`. Data resumed immediately.

### Lesson

- When using `CallbackAPIVersion.VERSION2`, **all** callbacks must use the v2 signatures — especially `on_disconnect`, which gains a `disconnect_flags` parameter.
- `publish()` in paho-mqtt **does not** raise an error when the connection is dead; it silently queues messages. Never assume "no exception = working".
- Always add connection-state logging or health checks to long-running MQTT publishers.

---

## Issue #4 — `on_connect` Crash: `int(ReasonCode)` TypeError

| Field | Detail |
|-------|--------|
| **Date** | 2026-02-16 (~22:04 UTC) |
| **Severity** | Data pipeline outage (repeat) |
| **Component** | Edge agents (`agent.py`) — same callback area |
| **Symptom** | After fixing Issue #3 and redeploying, nodes connected briefly (~5 minutes of data) then all 6 disconnected simultaneously again. Mosquitto logs showed "Client … has exceeded timeout, disconnecting" for all 6 clients at 22:04–22:05 UTC. Agents continued logging "telemetry published" (zombie state). |

### Root Cause

The fix for Issue #3 updated the callback signatures but used `int(rc)` to convert the `ReasonCode` object to an integer:

```python
# Still broken
rc_value = int(rc) if hasattr(rc, 'value') else rc
```

In paho-mqtt v2, `ReasonCode` objects **cannot** be cast via `int()`. The `int()` call raises `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'ReasonCode'`. This crashed `on_connect`, which killed the MQTT thread on the very first successful connection. The agents published for a few minutes using the initial pre-callback connection state, then the broker timed them out for missing keepalives.

### Fix

Replaced all `int(rc)` casts with proper `ReasonCode` API usage:

```python
# CORRECT
def on_connect(client, _userdata, _flags, reason_code, _properties=None):
    if reason_code == 0 or (hasattr(reason_code, 'is_failure') and not reason_code.is_failure):
        log.info("mqtt connected")
        client.subscribe(topic, qos=1)
    else:
        log.error("mqtt connect failed rc=%s", reason_code)
```

Also added a `client.is_connected()` guard in the telemetry publish loop to prevent silent zombie publishing:

```python
if not client.is_connected():
    log.warning("mqtt not connected, skipping publish (will auto-reconnect)")
else:
    # ... publish telemetry
```

### Lesson

- paho-mqtt v2 `ReasonCode` supports `==` comparison with integers (`rc == 0` works) and has an `is_failure` property, but does **not** support `int()` casting.
- Always test MQTT callback changes by simulating a disconnect/reconnect cycle, not just a clean first connection.
- Adding `client.is_connected()` checks prevents the "zombie publisher" pattern.

---

## Issue #5 — Ingestion Service Same v2 Callback Bug + Stale `.pyc` Cache

| Field | Detail |
|-------|--------|
| **Date** | 2026-02-16 (~22:20 UTC) |
| **Severity** | Brief ingestion outage (auto-recovered via systemd restart) |
| **Component** | `control-plane/ingestion/mqtt_client.py` on EC2 |
| **Symptom** | After deploying the fixed `mqtt_client.py` to EC2, the ingestion service crashed on the first disconnect with `TypeError: _on_disconnect() takes from 3 to 4 positional arguments but 5 were given` — despite the file on disk containing the correct 5-arg signature. |

### Root Cause (two issues)

1. **Same paho-mqtt v2 callback bug** as Issues #3/#4 — the ingestion service also used `CallbackAPIVersion.VERSION2` with v1-style callback signatures. Specifically, `_on_disconnect` only accepted 4 args `(_c, _ud, rc, _props)` instead of 5 `(_c, _ud, _flags, reason_code, _props)`.

2. **Stale `.pyc` bytecode cache** — After deploying the corrected `.py` file, Python loaded the old compiled `.pyc` from `__pycache__/` instead of the updated source file.

### Fix

Applied the same v2 callback fixes to `mqtt_client.py`, then:

```bash
sudo rm -f /opt/control-plane/ingestion/__pycache__/*.pyc
sudo systemctl restart ingestion
```

### Lesson

- When hotfixing Python files on a running system, **always clear `__pycache__/`** or Python may load the stale bytecode.
- Every component using paho-mqtt v2 needs the same callback signature updates — audit all MQTT client code, not just the one that crashed first.

---

## Issue #6 — Detector Scoring Produced Zero Events (Silent No-Op)

| Field | Detail |
|-------|--------|
| **Date** | 2026-02-16 (~22:14 UTC) |
| **Severity** | Detection not functioning |
| **Component** | `control-plane/detector/detector.py` on EC2 |
| **Symptom** | Detector service was `active (running)`, all 6 models trained successfully (logged thresholds), but `anomaly_events` table remained empty after multiple scoring cycles. No errors in logs. |

### Root Cause

Two contributing factors:

1. **No data in scoring window** — Due to Issue #4, no telemetry was being ingested during the scoring period. The `compute_window_features()` function returned `None` for empty windows, and `score_window()` silently returned `None` (by design — skip windows with no data). Since normal scoring logs at `DEBUG` level and the service was configured with `LOG_LEVEL=INFO`, nothing was logged.

2. **First-loop `continue` skip** — The detector's main loop trains models on the first iteration (when the key is not in `models`) and calls `continue`, skipping scoring. This is correct behavior — you train first, then score on subsequent iterations. But combined with the data gap, it meant the first few scoring iterations had nothing to score.

### Fix

Once Issues #3/#4/#5 were resolved and telemetry flowed again, the detector began scoring successfully on its next cycle. Six `anomaly_events` rows appeared (one per device, all `is_anomaly = false`).

### Lesson

- When scoring returns `None` (no data), consider logging at `INFO` level rather than silently skipping. A "no data in window" warning would have immediately indicated the upstream pipeline was broken.
- Add a simple "heartbeat" log to the scoring loop (e.g., "scoring cycle complete, N devices scored, M skipped") so operators can confirm the loop is alive.

---

## Issue #7 — TimescaleDB Extension Missing / `time_bucket` Errors

| Field | Detail |
|-------|--------|
| **Date** | 2026-02-16 |
| **Severity** | Dashboard panel errors |
| **Component** | Grafana dashboards + PostgreSQL |
| **Symptom** | Several Grafana dashboard panels showed errors: `function time_bucket(unknown, timestamp with time zone) does not exist`. |

### Root Cause

Dashboard queries used `time_bucket()`, a TimescaleDB function, but the PostgreSQL instance only had the vanilla extension. TimescaleDB was not installed.

### Fix

1. Installed `timescaledb-2-postgresql-16` package on EC2
2. Added `timescaledb` to `shared_preload_libraries` in `postgresql.conf`
3. Restarted PostgreSQL
4. Created extension: `CREATE EXTENSION IF NOT EXISTS timescaledb;`
5. Converted `telemetry_measurements` and `anomaly_events` to hypertables (required changing PKs to composite: `(id, ts)` and `(id, event_ts)`)

### Lesson

- TimescaleDB must be installed and configured as a shared preload library **before** `CREATE EXTENSION` will work.
- Converting a table to a hypertable requires the time column to be part of the primary key (or the PK must be dropped/replaced with a composite key).

---

## Issue #8 — Mitigator Service Never Deployed; No Mitigations Applied During Experiment

| Field | Detail |
|-------|--------|
| **Date** | 2026-03-15 |
| **Severity** | Missing functionality (mitigation loop silent) |
| **Component** | `control-plane/mitigator/controller.py` + systemd |
| **Symptom** | Fault injection experiment ran successfully — detector flagged 35 anomalies across all 6 nodes — but zero mitigation commands were issued. `mitigation_actions` table was empty. |

### Root Cause

The mitigator service (`control-plane/mitigator/`) existed in the repository but had **never been deployed to EC2**. No `/opt/control-plane/mitigator/` directory existed, and no `mitigator.service` systemd unit was installed. The ingestion and detector services were deployed previously; the mitigator was overlooked.

Additionally, the default `ANOMALY_PERSIST_WINDOWS=3` (lookback = 6 minutes, requires 3 anomaly windows) was too conservative for the fault injection phases:
- Delay phase: 5 minutes → borderline (2–3 windows)
- Loss phase: 3 minutes → would fire too late or not at all

### Fix

1. Deployed mitigator code to EC2:
   ```bash
   scp control-plane/mitigator/{controller.py,requirements.txt} ubuntu@ec2:/tmp/
   ssh ubuntu@ec2 "sudo mkdir -p /opt/control-plane/mitigator && sudo cp /tmp/controller.py /tmp/requirements.txt /opt/control-plane/mitigator/"
   ```
2. Created `/opt/control-plane/mitigator/.env` with credentials + tuned config:
   - `ANOMALY_PERSIST_WINDOWS=2` (4-minute lookback, requires 2 anomaly windows)
   - `BACKUP_HTTP_URL=https://1.1.1.1` (matches `HTTP_URL_BACKUP` in edge agent `.env`)
3. Installed deps: `/opt/control-plane/venv/bin/pip install -r requirements.txt`
4. Deployed `control-plane/systemd/mitigator.service` to `/etc/systemd/system/`
5. Enabled and started: `systemctl enable --now mitigator`

Service confirmed running as of 2026-03-15T17:24:08Z. Mitigation commands will now be issued after 2 consecutive anomaly windows (~4 minutes) of persistent anomaly for a device.

### Lesson

- All three control-plane services (ingestion, detector, mitigator) must be deployed as a set. A deployment checklist should verify all three are `active (running)` before running experiments.
- Tune `ANOMALY_PERSIST_WINDOWS` relative to fault phase duration: at least 1 window shorter than the shortest fault phase. For 3-minute phases with 2-minute windows, use `ANOMALY_PERSIST_WINDOWS=1` or `2`.
- Before any experiment run, confirm: `systemctl is-active ingestion detector ema-detector mitigator`

### Verification Command

```bash
# All four services should report "active"
ssh ubuntu@ec2 "systemctl is-active ingestion detector ema-detector mitigator"

# Confirm mitigation actions appear during/after fault injection
PGPASSWORD='...' psql -h localhost -U telemetry_user -d telemetry -c \
  "SELECT device_id, action, status, issued_ts FROM mitigation_actions ORDER BY issued_ts DESC LIMIT 10;"
```

---

## Issue #9 — Mitigator Tuple Unpack Error Caused Silent Failure During Exp 2

| Field | Detail |
|-------|--------|
| **Date** | 2026-03-15 (~17:46Z – 17:55Z) |
| **Severity** | Silent mitigation failure (~9 min window) |
| **Component** | `control-plane/mitigator/controller.py` |
| **Symptom** | Mitigator service was `active (running)` and polling the anomaly DB, but zero mitigation commands were issued during the first ~9 minutes of Exp 2 despite active anomaly events for all 6 nodes. No error messages appeared in the service log at `INFO` level. |

### Root Cause

The SQL query in the mitigator's persist-check loop returns a **3-tuple** per row:
`(device_id, target_id, cnt)` — where `cnt` is the count of persistent anomaly windows.
The loop unpacked it as a **2-tuple**:

```python
# BROKEN — IndexError / silent failure
for device_id, target_id in pairs:
    ...
```

Python raises a `ValueError: too many values to unpack` when iterating a 3-element
sequence into 2 variables.  The exception was swallowed by a broad `except Exception`
handler in the polling loop, which logged at `DEBUG` level (below the configured
`LOG_LEVEL=INFO`), making the failure invisible in normal operation.

### Fix

Changed the loop variable to properly unpack the 3-tuple, discarding the count:

```python
# FIXED
for device_id, target_id, _cnt in pairs:
    ...
```

File: `control-plane/mitigator/controller.py`

Deployed live to EC2 at 17:55Z during Exp 2. Mitigation commands began firing
immediately after the fix was applied and the service restarted.

### Impact on Experiments

- **Exp 2:** Mitigations failed silently for the first ~9 minutes of the run.
  LAN nodes received valid commands after the bug was fixed at 17:55Z. Results
  are valid for detection MTTD; mitigation data is partial (LAN only, post-fix window).
- **Exp 1:** Not affected (mitigator was not deployed during Exp 1).
- **Exp 3+:** Not affected (bug was fixed before Exp 3).

### Lesson

- Always test the exact return shape of DB queries before deploying. A quick
  `SELECT` + `print(rows[0])` in a local Python session would have caught this
  immediately.
- Broad `except Exception` handlers that log below `INFO` create invisible failure
  modes. At minimum, log unexpected exceptions at `WARNING` regardless of `LOG_LEVEL`.
- Add a unit test for the query unpacking: mock the DB cursor to return a 3-tuple
  and assert the loop processes it without error.

---

## Change Log — Non-Issue Changes

### 2026-02-17: Bandwidth Probe Added

Added a periodic bandwidth estimate to all edge agents. Every ~5 minutes
(30 probe cycles), each Pi downloads a ~1 MB file from Cloudflare's speed
test CDN and records the estimated throughput in Mbps.

**Why:** The testbed shares a residential internet connection. Bandwidth
contention from other devices could inflate latency measurements, making
normal data look anomalous. The bandwidth column lets us correlate latency
spikes with bandwidth dips post-hoc and annotate experiment results.

**Changes:**
- `edge-agent/agent.py` — new `probe_bandwidth()` function
- `edge-agent/config.py` — `BANDWIDTH_URL`, `BANDWIDTH_INTERVAL`, `BANDWIDTH_TIMEOUT_S`
- `control-plane/ingestion/db.py` — stores `bandwidth_mbps` column
- `telemetry_measurements` — new `bandwidth_mbps DOUBLE PRECISION` column (NULL when not sampled)
- Grafana dashboards — bandwidth panels added to Latency Overview, Experiment, and Network Comparison
- `docs/experiment-plan.md` — Network Environment section added

**Baseline values observed:** ~1.5 Mbps from all 6 nodes (1 MB test file).

---

## Summary of paho-mqtt v2 Migration Pitfalls

All of Issues #3, #4, and #5 stem from the same migration gap. Here is a
compact reference for anyone moving from paho-mqtt v1 to v2 callbacks:

| Callback | v1 Signature | v2 Signature |
|----------|-------------|-------------|
| `on_connect` | `(client, userdata, flags, rc)` | `(client, userdata, flags, reason_code, properties)` |
| `on_disconnect` | `(client, userdata, rc)` | `(client, userdata, disconnect_flags, reason_code, properties)` |
| `on_message` | `(client, userdata, message)` | `(client, userdata, message)` *(unchanged)* |
| `on_subscribe` | `(client, userdata, mid, granted_qos)` | `(client, userdata, mid, reason_codes, properties)` |

Key differences:
- **`reason_code`** is a `ReasonCode` object, not an `int`. Use `rc == 0` or `rc.is_failure` — **never** `int(rc)`.
- **`disconnect_flags`** is a new parameter in `on_disconnect` (v2 only) inserted before `reason_code`.
- If you specify `CallbackAPIVersion.VERSION2`, **all** callbacks must use v2 signatures — paho will pass v2 arguments regardless of your function signature.
- `client.publish()` does **not** raise on a dead connection. Use `client.is_connected()` to guard against zombie publishing.

---

## Appendix: Quick Diagnostic Commands

```bash
# Check if data is flowing (run on EC2)
sudo -u postgres psql -d telemetry -c "
  SELECT device_id, MAX(ts) as last_seen,
    ROUND(EXTRACT(EPOCH FROM (now() - MAX(ts)))::numeric, 0) as secs_ago
  FROM telemetry_measurements
  GROUP BY device_id ORDER BY last_seen DESC;"

# Check latest bandwidth readings
sudo -u postgres psql -d telemetry -c "
  SELECT device_id, ts, bandwidth_mbps
  FROM telemetry_measurements
  WHERE bandwidth_mbps IS NOT NULL
  ORDER BY ts DESC LIMIT 6;"

# Check MQTT broker connections
sudo journalctl -u mosquitto -n 20 --no-pager

# Check agent on a Pi
ssh -i ~/.ssh/remote-key.pem kingnathanal@pi00-wifi \
  'sudo journalctl -u edge-probe -n 20 --no-pager --output=cat'

# Check ingestion service
sudo journalctl -u ingestion -n 20 --no-pager --output=cat

# Check detector scoring
sudo -u postgres psql -d telemetry -c "
  SELECT device_id, COUNT(*) as events,
    COUNT(*) FILTER (WHERE is_anomaly) as anomalies,
    MAX(event_ts) as last_event
  FROM anomaly_events
  WHERE event_ts > now() - INTERVAL '15 minutes'
  GROUP BY device_id ORDER BY device_id;"

# Check for stale Python bytecode
sudo find /opt/control-plane/ -name '*.pyc' -newer /opt/control-plane/ingestion/mqtt_client.py

# Subscribe to MQTT for live debugging (requires auth)
mosquitto_sub -h localhost -u <user> -P <pass> -t "telemetry/#" -C 1
```

---

## Decision #10 — Dedicated Failover EC2 Instead of Co-located Backup Port

| Field | Detail |
|-------|--------|
| **Date** | 2026-03-15 |
| **Type** | Architecture decision (not a bug) |
| **Component** | Backup / failover endpoint infrastructure |
| **Context** | Experiment 4+ requires a clean, measurable HTTP latency improvement after mitigation fires a `failover_endpoint` command. |

### Problem With Co-located Backup

Through Experiments 1–3, the backup endpoint was `http://54.198.26.122:8082/health` —
the **same EC2 instance** as the primary, running on a different port. This created two
compounding problems:

1. **netem scoping gap:** The `tc filter u32` rule in `netem_apply.sh -t <ip>` matches
   all traffic to the primary IP regardless of port. Traffic to port 8082 (backup) on the
   same IP was therefore **also degraded** during fault phases — making failover
   ineffective as a mitigation for HTTP latency.

2. **No measurable impact reduction:** Even with the port-based filter workaround (`-p 8080`)
   added later, using the same physical host means the backup shares CPU, memory, and
   upstream network with the degraded primary. The latency delta was not clean enough to
   publish as an "impact reduction" metric in the research paper.

   > Exp 3 post-failover HTTP latency was ~1052 ms — **worse** than the degraded primary —
   > because the old backup was `https://1.1.1.1` (Cloudflare, TLS overhead). Even after
   > switching to port 8082 on the same host, the improvement would be marginal and
   > confounded by shared resources.

### Decision

Deploy a **separate AWS EC2 instance** (`ubuntu@failover`, IP `34.226.196.133`) running
the same Flask health app on port 8080. The failover server is:

- On a **different physical host** — no shared resources with the primary
- At a **different IP** — `tc netem` scoped to `54.198.26.122` has zero effect on traffic
  to `34.226.196.133`; no port filtering needed
- Independently reachable — can survive a primary EC2 failure in production

### Configuration Changes

| Component | Before | After |
|-----------|--------|-------|
| Pi `.env` `HTTP_URL_BACKUP` | `http://54.198.26.122:8082/health` | `http://34.226.196.133:8080/health` |
| Mitigator `BACKUP_HTTP_URL` | `http://54.198.26.122:8082/health` | `http://34.226.196.133:8080/health` |
| `scenarios.sh` netem scope | `-t PRIMARY_IP -p 8080` | `-t PRIMARY_IP` (IP-only, port not needed) |
| `health-backup.service` on primary EC2 | Running on port 8082 | No longer needed (can be disabled) |

Failover server setup documented in `docs/runbook.md` → *Failover Server* section.
Systemd service committed at `control-plane/systemd/health-failover.service`.

### Expected Outcome for Exp 4+

| Phase | HTTP Latency |
|-------|-------------|
| Baseline (primary, no fault) | ~45 ms |
| During fault (primary, 100ms netem) | ~295 ms |
| Post-failover (backup, separate EC2, no netem) | ~45 ms |
| **Impact reduction** | **~85%** |

### Lesson

When designing a failover testbed, the backup endpoint **must be on a different network
path** than the primary. A same-host backup on a different port is convenient but
defeats the purpose: it shares the fault domain, inflates measurement noise, and makes
impact-reduction claims unpublishable. Always model the backup after your production
architecture from the start.

---

## Issue #10 — Per-Node Threshold Calibration: Why Each Node Has a Different Threshold

| Field | Detail |
|-------|--------|
| **Date** | 2026-03-15 |
| **Severity** | Research observation / design consideration |
| **Component** | Detector (`thresholds.py`, `detector.py`) |
| **Symptom** | During Exp 1, pi02-wifi scored 0.675–0.684 on the Isolation Forest throughout the delay fault window but never tripped `is_anomaly=true` (threshold: 0.6854). All other 5 nodes did detect and failover. pi02-wifi only fired once — during the loss phase, exactly at threshold (0.6854 = 0.6854), but `ANOMALY_PERSIST_WINDOWS=3` requires 3 consecutive anomaly windows, so no mitigation was issued. |

### Why Thresholds Differ Per Node

The detector trains one Isolation Forest model **per (device_id, target_id) pair** using that node's own 24-hour baseline telemetry. The threshold is then set at the **97.5th percentile** of that node's baseline anomaly scores (`calibrate_percentile()` in `thresholds.py`).

Observed thresholds during Exp 1 (iforest-v1):

| Node | IF Threshold | Threshold Explanation |
|------|--------------|-----------------------|
| pi00-wifi | 0.6437 | Low baseline variance → low 97.5th pct |
| pi01-wifi | 0.6636 | Moderate baseline variance |
| pi02-wifi | 0.6854 | **Higher baseline variance** → higher 97.5th pct |
| pi03-lan | 0.6847 | Moderate baseline variance |
| pi04-lan | 0.6847 | Moderate baseline variance |
| pi05-lan | 0.6784 | Low-moderate baseline variance |

Nodes with naturally noisier baselines (e.g., WiFi nodes experiencing ambient wireless jitter) produce higher anomaly scores during normal operation. Their 97.5th percentile is therefore higher, making the threshold harder to cross. A 100ms delay that clearly anomalises a LAN node or a stable WiFi node may only push a noisier node to a score just below its personal threshold.

### Production Design Question: Uniform vs. Per-Node Thresholds

**Option 1 — Uniform global threshold (e.g., 0.70 for all nodes)**
- ✅ Simple to configure and reason about
- ✅ Consistent detection sensitivity across fleet
- ❌ Generates more false positives on naturally noisy nodes (e.g., WiFi)
- ❌ May miss subtle faults on very stable nodes (threshold too high relative to their scores)
- ❌ Ignores the fact that "anomalous" is inherently relative to each node's normal

**Option 2 — Dynamic per-node threshold (current implementation)**
- ✅ Calibrated to each node's individual normal — the correct statistical approach
- ✅ LAN and WiFi nodes can coexist without one type drowning in false alerts
- ❌ A noisy baseline window (e.g., maintenance, transient interference) inflates the threshold permanently until the next service restart / retrain
- ❌ Thresholds can diverge enough that two identical nodes in the same environment behave differently (as seen: pi02-wifi vs pi00-wifi)

**Option 3 — Per-device-type threshold (recommended for production)**
- Group nodes by network type (LAN vs WiFi) or hardware class
- Set one threshold per group, calibrated from the **median 97.5th percentile** across all nodes in that group
- Prevents single-node baseline noise from inflating that node's threshold above the group norm
- Provides more consistent detection behaviour across the fleet while still respecting LAN/WiFi differences

**Option 4 — Online adaptive threshold (best long-term)**
- Maintain a rolling EMA of recent anomaly scores per node
- Threshold adjusts continuously as the node's "normal" drifts (e.g., seasonal traffic, firmware updates)
- Prevents the threshold-freeze problem when the Isolation Forest isn't retrained for weeks
- Currently out of scope — noted as future work in the paper

### Recommendation for This Study

The per-node threshold is statistically correct for this research context: we want the model to learn each node's individual normal. The pi02-wifi miss is a real finding — it demonstrates the **sensitivity limitation** of static per-node calibration when baseline noise is high. This should be reported honestly in the paper rather than papered over with a manually tuned threshold.

For production deployment, **Option 3 (per-device-type grouping)** is the pragmatic choice: it retains per-class calibration while smoothing out single-node baseline noise.

### Lesson

Per-node threshold calibration is the right default for heterogeneous edge fleets. However, it is only as good as the baseline it was trained on. A single noisy or atypical baseline window can permanently raise one node's detection floor. In production, either (a) use per-device-type group thresholds, or (b) implement online threshold adaptation. Never use a single global threshold across mixed LAN/WiFi fleets — the false-positive rate on wireless nodes will be unacceptably high.

---

## Issue #11 — Contaminated Baseline Inflates Thresholds After Detector Restart

| Field | Detail |
|-------|--------|
| **Date** | 2026-03-15 |
| **Severity** | Experiment confound (Exp 4 MTTD unmeasurable) |
| **Component** | `detector.py` threshold calibration + `.env` THRESHOLD_PERCENTILE |
| **Symptom** | During Exp 4 (100ms/2%, 30s scoring), IF scores reached 0.72–0.74 for LAN and 0.67–0.71 for WiFi but failed to cross the newly-calibrated thresholds (0.75–0.76 LAN, 0.71 WiFi). No detections fired for the entire 5-minute delay phase. |
| **Root Cause** | Two compounding factors: (1) The detector was restarted at 23:18Z to apply `SCORE_INTERVAL_S=30`, causing it to retrain on a 24-hour rolling baseline window that now included fault-injection data from Exp 1, 2, and 3. The fault-phase anomaly scores (~0.70–0.77) inflated the calibration distribution, raising the p99 threshold by ~+0.07 above the original clean-baseline thresholds. (2) `.env` was previously set to `THRESHOLD_PERCENTILE=99.0` (vs code default of 97.5), compounding the inflation. |
| **Fix Applied** | Lowered `THRESHOLD_PERCENTILE` to `95.0` in `.env` and restarted detector at 23:37:58Z. New thresholds dropped to ~0.48–0.61, and all 6 nodes detected on the next scoring cycle (23:38:36Z). |
| **Impact on Exp 4** | MTTD is not cleanly measurable. First 5 min of fault phase: no detection. Post-recalibration detection fired during recovery-1, not during the active fault window. Exp 4 results should be treated as confounded and the MTTD scoring-interval comparison should use Exp 5. |

### Root Cause Deep Dive

The 24-hour rolling baseline window is a double-edged sword:
- ✅ Automatically adapts to long-term drift in normal network behaviour
- ❌ When a fault-injection experiment runs and the detector is restarted shortly after, the fault windows (with high anomaly scores) are included in the baseline training set

With `THRESHOLD_PERCENTILE=99.0` and ~30 fault windows (out of ~680 total) in the baseline:
- The 99th percentile sits at roughly the 7th-highest baseline score
- Fault-phase scores are among the highest in the distribution, directly setting the threshold
- Result: threshold = "just above the fault scores we're trying to detect"

### Fix for Future Experiments

Before restarting the detector after fault-injection experiments, either:

1. **Use a fixed clean-baseline timestamp** — train only on data before the first experiment started (e.g., `WHERE ts < '2026-03-15 22:00:00'`)
2. **Lower THRESHOLD_PERCENTILE** — use p95 or p97.5 to leave headroom even when baseline is slightly contaminated
3. **Wait for a full clean baseline window** — restart at least 24 hours after the last experiment (not practical in time-constrained research)
4. **Exclude known fault windows** — tag fault periods in the DB and filter them from baseline training

### Lesson

Never restart the anomaly detector immediately after fault-injection experiments if using a rolling baseline window. The fault data contaminates the calibration distribution and can raise thresholds above the fault signal you're trying to detect. In production, use Option 1 or 4 (pinned clean baseline or fault-window exclusion). For this study, `THRESHOLD_PERCENTILE=95.0` provides sufficient headroom and is retained for all remaining experiments.
