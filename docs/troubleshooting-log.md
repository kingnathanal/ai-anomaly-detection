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
