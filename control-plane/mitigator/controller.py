#!/usr/bin/env python3
"""
Mitigator Service
=================
Polls anomaly_events for persistent anomalies and issues mitigation commands
via MQTT.  Listens for status acks and updates mitigation_actions in Postgres.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import paho.mqtt.client as mqtt
import psycopg2
import psycopg2.pool

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
log = logging.getLogger("mitigator")

_shutdown = threading.Event()

# How many consecutive anomaly windows before issuing a command
ANOMALY_PERSIST_WINDOWS = int(os.environ.get("ANOMALY_PERSIST_WINDOWS", "3"))
POLL_INTERVAL_S = int(os.environ.get("POLL_INTERVAL_S", "60"))
COMMAND_TIMEOUT_S = int(os.environ.get("COMMAND_TIMEOUT_S", "120"))


# ── DB ───────────────────────────────────────────────────────────

def _dsn() -> str:
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "telemetry")
    user = os.environ.get("DB_USER", "telemetry_user")
    pw = os.environ.get("DB_PASS", "change_me_now")
    return f"host={host} port={port} dbname={name} user={user} password={pw}"


_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(2, 5, _dsn())


def get_conn():
    assert _pool
    return _pool.getconn()


def put_conn(conn: Any) -> None:
    assert _pool
    _pool.putconn(conn)


# ── Anomaly polling ─────────────────────────────────────────────

QUERY_RECENT_ANOMALIES = """
SELECT device_id, target_id, COUNT(*) as cnt
FROM anomaly_events
WHERE is_anomaly = true
  AND event_ts >= %(since)s
GROUP BY device_id, target_id
HAVING COUNT(*) >= %(threshold)s
"""

QUERY_PENDING_MITIGATION = """
SELECT command_id FROM mitigation_actions
WHERE device_id = %(device_id)s
  AND status = 'issued'
  AND issued_ts >= %(since)s
LIMIT 1
"""

INSERT_MITIGATION = """
INSERT INTO mitigation_actions (command_id, device_id, action, params, status)
VALUES (%(command_id)s, %(device_id)s, %(action)s, %(params)s, 'issued')
"""

UPDATE_MITIGATION_STATUS = """
UPDATE mitigation_actions
SET status = %(status)s,
    status_ts = %(status_ts)s,
    notes = %(notes)s
WHERE command_id = %(command_id)s
"""


def find_devices_needing_mitigation(conn: Any) -> list[tuple[str, str]]:
    """Return (device_id, target_id) pairs with persistent anomalies."""
    lookback = datetime.now(timezone.utc) - timedelta(
        seconds=ANOMALY_PERSIST_WINDOWS * 120  # window length
    )
    with conn.cursor() as cur:
        cur.execute(QUERY_RECENT_ANOMALIES, {
            "since": lookback,
            "threshold": ANOMALY_PERSIST_WINDOWS,
        })
        return cur.fetchall()


def has_pending_command(conn: Any, device_id: str) -> bool:
    """Check if there's already a pending (un-acked) command for this device."""
    since = datetime.now(timezone.utc) - timedelta(seconds=COMMAND_TIMEOUT_S)
    with conn.cursor() as cur:
        cur.execute(QUERY_PENDING_MITIGATION, {
            "device_id": device_id,
            "since": since,
        })
        return cur.fetchone() is not None


def record_command(conn: Any, command_id: str, device_id: str,
                   action: str, params: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(INSERT_MITIGATION, {
            "command_id": command_id,
            "device_id": device_id,
            "action": action,
            "params": json.dumps(params),
        })
    conn.commit()


def update_command_status(conn: Any, command_id: str,
                          status: str, notes: str) -> None:
    with conn.cursor() as cur:
        cur.execute(UPDATE_MITIGATION_STATUS, {
            "command_id": command_id,
            "status": status,
            "status_ts": datetime.now(timezone.utc),
            "notes": notes,
        })
    conn.commit()


# ── MQTT ─────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def create_mqtt_client() -> mqtt.Client:
    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    user = os.environ.get("MQTT_USER")
    pw = os.environ.get("MQTT_PASS")

    client_id = f"mitigator-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(
        client_id=client_id,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    if user and pw:
        client.username_pw_set(user, pw)

    def _on_connect(c: mqtt.Client, _ud: Any, _flags: Any,
                    rc: int, _props: Any = None) -> None:
        if rc == 0:
            log.info("mqtt connected")
            # Subscribe to all mitigation status acks
            c.subscribe("mitigation/+/status", qos=1)
            log.info("subscribed topic=mitigation/+/status")
        else:
            log.error("mqtt connect failed rc=%d", rc)

    def _on_message(_c: mqtt.Client, _ud: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("bad status payload topic=%s err=%s", msg.topic, exc)
            return
        handle_status_ack(payload)

    client.on_connect = _on_connect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    client.connect(host, port, keepalive=60)
    return client


def handle_status_ack(payload: dict[str, Any]) -> None:
    """Process a mitigation status ack from an edge agent."""
    command_id = payload.get("command_id", "")
    status = payload.get("status", "unknown")
    details = payload.get("details", "")
    device_id = payload.get("device_id", "?")

    log.info("mitigation ack device=%s command=%s status=%s details=%s",
             device_id, command_id, status, details)

    if not command_id:
        return

    conn = get_conn()
    try:
        update_command_status(conn, command_id, status, details)
    except Exception as exc:
        log.error("failed to update mitigation status err=%s", exc)
        conn.rollback()
    finally:
        put_conn(conn)


def issue_failover(client: mqtt.Client, device_id: str, target_id: str) -> None:
    """Issue a failover_endpoint command to a device."""
    command_id = str(uuid.uuid4())
    backup_url = os.environ.get("BACKUP_HTTP_URL", "https://backup.example.com/health")

    params = {"target_id": "backup", "http_url": backup_url}
    payload = {
        "ts": _now_iso(),
        "command_id": command_id,
        "action": "failover_endpoint",
        "params": params,
    }

    topic = f"mitigation/{device_id}/command"
    client.publish(topic, json.dumps(payload), qos=1)
    log.info("issued failover device=%s command=%s", device_id, command_id)

    conn = get_conn()
    try:
        record_command(conn, command_id, device_id, "failover_endpoint", params)
    except Exception as exc:
        log.error("failed to record mitigation command err=%s", exc)
        conn.rollback()
    finally:
        put_conn(conn)


def issue_set_interval(client: mqtt.Client, device_id: str,
                       interval_s: int = 2) -> None:
    """Issue a set_interval command to increase sampling rate."""
    command_id = str(uuid.uuid4())
    params = {"interval_s": interval_s}
    payload = {
        "ts": _now_iso(),
        "command_id": command_id,
        "action": "set_interval",
        "params": params,
    }

    topic = f"mitigation/{device_id}/command"
    client.publish(topic, json.dumps(payload), qos=1)
    log.info("issued set_interval device=%s interval=%ds command=%s",
             device_id, interval_s, command_id)

    conn = get_conn()
    try:
        record_command(conn, command_id, device_id, "set_interval", params)
    except Exception as exc:
        log.error("failed to record mitigation command err=%s", exc)
        conn.rollback()
    finally:
        put_conn(conn)


# ── Main loop ────────────────────────────────────────────────────

def main() -> None:
    log.info("starting mitigator service poll_interval=%ds persist_windows=%d",
             POLL_INTERVAL_S, ANOMALY_PERSIST_WINDOWS)

    def _sig(signum: int, _f: Any) -> None:
        log.info("signal=%d, shutting down", signum)
        _shutdown.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    init_pool()
    client = create_mqtt_client()
    client.loop_start()

    while not _shutdown.is_set():
        conn = get_conn()
        try:
            pairs = find_devices_needing_mitigation(conn)
            for device_id, target_id in pairs:
                if has_pending_command(conn, device_id):
                    log.debug("skipping device=%s, pending command exists", device_id)
                    continue
                # Primary strategy: failover endpoint
                issue_failover(client, device_id, target_id)
                # Also increase sampling rate during anomaly
                issue_set_interval(client, device_id, interval_s=2)

        except Exception as exc:
            log.error("mitigator loop error err=%s", exc)
        finally:
            put_conn(conn)

        for _ in range(POLL_INTERVAL_S * 10):
            if _shutdown.is_set():
                break
            time.sleep(0.1)

    client.loop_stop()
    client.disconnect()
    if _pool:
        _pool.closeall()
    log.info("mitigator service stopped")


if __name__ == "__main__":
    main()
