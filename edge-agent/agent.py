#!/usr/bin/env python3
"""
Edge Probe Agent
================
Periodically probes ICMP / DNS / HTTP targets and publishes telemetry to an
MQTT broker.  Subscribes to mitigation commands (failover_endpoint,
set_interval) and acknowledges them.

Designed to run as a long-lived systemd service on a Raspberry Pi.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
import requests

import config

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
log = logging.getLogger("edge-agent")

# ── Mutable runtime state ──────────────────────────────────────
_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "interval_s": config.PROBE_INTERVAL_S,
    "active_target_id": config.ACTIVE_TARGET_ID,
    "http_targets": dict(config.HTTP_TARGETS),  # copy
}

_shutdown = threading.Event()


# ────────────────────────────────────────────────────────────────
#  Probe helpers
# ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def probe_icmp(target: str, count: int, timeout_s: int) -> dict[str, Any]:
    """Run ping and parse min/avg/max RTT + packet loss."""
    try:
        # Detect OS for ping flag differences
        flag = "-c"
        timeout_flag = "-W"
        timeout_val = str(timeout_s)
        if platform.system() == "Darwin":
            timeout_val = str(timeout_s * 1000)  # macOS uses ms

        result = subprocess.run(
            ["ping", flag, str(count), timeout_flag, timeout_val, target],
            capture_output=True,
            text=True,
            timeout=timeout_s + 5,
        )

        output = result.stdout + result.stderr

        # Parse packet loss
        loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
        loss_pct = float(loss_match.group(1)) if loss_match else 100.0

        # Parse rtt stats: min/avg/max(/mdev)
        rtt_match = re.search(
            r"(?:rtt|round-trip)\s+min/avg/max(?:/\w+)?\s*=\s*"
            r"([\d.]+)/([\d.]+)/([\d.]+)",
            output,
        )
        if rtt_match:
            return {
                "ok": True,
                "rtt_min_ms": round(float(rtt_match.group(1)), 2),
                "rtt_avg_ms": round(float(rtt_match.group(2)), 2),
                "rtt_max_ms": round(float(rtt_match.group(3)), 2),
                "loss_pct": loss_pct,
            }
        # All packets lost but ping didn't error out
        return {"ok": False, "rtt_min_ms": 0, "rtt_avg_ms": 0,
                "rtt_max_ms": 0, "loss_pct": loss_pct}

    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("icmp probe failed target=%s err=%s", target, exc)
        return {"ok": False, "rtt_min_ms": 0, "rtt_avg_ms": 0,
                "rtt_max_ms": 0, "loss_pct": 100.0}


def probe_dns(query: str, timeout_s: int) -> dict[str, Any]:
    """Resolve *query* via dig and return latency."""
    try:
        result = subprocess.run(
            ["dig", "+noall", "+stats", "+tries=1", query],
            capture_output=True,
            text=True,
            timeout=timeout_s + 2,
        )
        # dig outputs: ;; Query time: 12 msec
        match = re.search(r"Query time:\s*(\d+)\s*msec", result.stdout)
        if match:
            return {
                "ok": True,
                "query": query,
                "latency_ms": float(match.group(1)),
            }
        return {"ok": False, "query": query, "latency_ms": 0}

    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("dns probe failed query=%s err=%s", query, exc)
        return {"ok": False, "query": query, "latency_ms": 0}


def probe_http(url: str, timeout_s: int) -> dict[str, Any]:
    """HTTP GET and return status + latency."""
    try:
        start = time.monotonic()
        resp = requests.get(url, timeout=timeout_s, allow_redirects=True)
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            "ok": 200 <= resp.status_code < 400,
            "url": url,
            "status": resp.status_code,
            "latency_ms": elapsed_ms,
        }
    except requests.RequestException as exc:
        log.warning("http probe failed url=%s err=%s", url, exc)
        return {"ok": False, "url": url, "status": 0, "latency_ms": 0}


# ────────────────────────────────────────────────────────────────
#  Telemetry assembly
# ────────────────────────────────────────────────────────────────

def build_telemetry() -> dict[str, Any]:
    """Run all probes and assemble the telemetry payload."""
    with _state_lock:
        target_id = _state["active_target_id"]
        http_targets = dict(_state["http_targets"])
        interval_s = _state["interval_s"]

    http_url = http_targets.get(target_id, "")

    icmp = probe_icmp(config.ICMP_TARGET, config.ICMP_COUNT, config.ICMP_TIMEOUT_S)
    dns = probe_dns(config.DNS_QUERY, config.DNS_TIMEOUT_S)
    http = probe_http(http_url, config.HTTP_TIMEOUT_S) if http_url else {
        "ok": False, "url": "", "status": 0, "latency_ms": 0,
    }

    return {
        "ts": _now_iso(),
        "device_id": config.DEVICE_ID,
        "network_type": config.NETWORK_TYPE,
        "target_id": target_id,
        "interval_s": interval_s,
        "metrics": {
            "icmp": icmp,
            "dns": dns,
            "http": http,
        },
    }


# ────────────────────────────────────────────────────────────────
#  Mitigation command handler
# ────────────────────────────────────────────────────────────────

def handle_mitigation(client: mqtt.Client, payload: dict[str, Any]) -> None:
    """Apply a mitigation command and publish an ack."""
    action = payload.get("action", "")
    command_id = payload.get("command_id", str(uuid.uuid4()))
    params = payload.get("params", {})
    details = ""

    try:
        if action == "failover_endpoint":
            new_target = params.get("target_id", "")
            new_url = params.get("http_url", "")
            with _state_lock:
                if new_url:
                    _state["http_targets"][new_target] = new_url
                _state["active_target_id"] = new_target
            details = f"Switched to {new_target} endpoint"
            log.info("mitigation applied action=%s target=%s url=%s",
                     action, new_target, new_url)

        elif action == "set_interval":
            new_interval = int(params.get("interval_s", config.PROBE_INTERVAL_S))
            with _state_lock:
                _state["interval_s"] = new_interval
            details = f"Interval changed to {new_interval}s"
            log.info("mitigation applied action=%s interval_s=%d",
                     action, new_interval)

        else:
            details = f"Unknown action: {action}"
            log.warning("unknown mitigation action=%s", action)
            _publish_mitigation_status(client, command_id, "failed", details)
            return

        _publish_mitigation_status(client, command_id, "applied", details)

    except Exception as exc:
        details = f"Error applying {action}: {exc}"
        log.error("mitigation error action=%s err=%s", action, exc)
        _publish_mitigation_status(client, command_id, "failed", details)


def _publish_mitigation_status(
    client: mqtt.Client,
    command_id: str,
    status: str,
    details: str,
) -> None:
    """Publish a mitigation status/ack message."""
    topic = f"mitigation/{config.DEVICE_ID}/status"
    payload = {
        "ts": _now_iso(),
        "command_id": command_id,
        "device_id": config.DEVICE_ID,
        "status": status,
        "details": details,
    }
    client.publish(topic, json.dumps(payload), qos=1)
    log.info("mitigation status published topic=%s status=%s command_id=%s",
             topic, status, command_id)


# ────────────────────────────────────────────────────────────────
#  MQTT callbacks
# ────────────────────────────────────────────────────────────────

def on_connect(client: mqtt.Client, _userdata: Any, _flags: Any,
               reason_code: Any, _properties: Any = None) -> None:
    # CallbackAPIVersion.VERSION2: reason_code is a ReasonCode object
    if reason_code == 0 or (hasattr(reason_code, 'is_failure') and not reason_code.is_failure):
        log.info("mqtt connected broker=%s:%d", config.MQTT_HOST, config.MQTT_PORT)
        # Subscribe to mitigation commands for this device
        topic = f"mitigation/{config.DEVICE_ID}/command"
        client.subscribe(topic, qos=1)
        log.info("subscribed topic=%s", topic)
    else:
        log.error("mqtt connect failed rc=%s", reason_code)


def on_disconnect(client: mqtt.Client, _userdata: Any,
                  _flags: Any = None, reason_code: Any = None,
                  _properties: Any = None) -> None:
    # CallbackAPIVersion.VERSION2: reason_code is a ReasonCode object
    is_failure = False
    if reason_code is not None:
        if hasattr(reason_code, 'is_failure'):
            is_failure = reason_code.is_failure
        elif reason_code != 0:
            is_failure = True
    if is_failure:
        log.warning("mqtt unexpected disconnect rc=%s, will reconnect", reason_code)


def on_message(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
    log.info("mqtt message received topic=%s", msg.topic)
    try:
        payload = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.error("bad payload on topic=%s err=%s", msg.topic, exc)
        return

    # Mitigation command?
    if msg.topic == f"mitigation/{config.DEVICE_ID}/command":
        handle_mitigation(_client, payload)


# ────────────────────────────────────────────────────────────────
#  Main loop
# ────────────────────────────────────────────────────────────────

def create_mqtt_client() -> mqtt.Client:
    client_id = f"{config.DEVICE_ID}-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(
        client_id=client_id,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    if config.MQTT_USER and config.MQTT_PASS:
        client.username_pw_set(config.MQTT_USER, config.MQTT_PASS)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Automatic reconnect with back-off (1–120 s)
    client.reconnect_delay_set(min_delay=1, max_delay=120)

    return client


def telemetry_loop(client: mqtt.Client) -> None:
    """Publish telemetry at the configured interval until shutdown."""
    while not _shutdown.is_set():
        try:
            if not client.is_connected():
                log.warning("mqtt not connected, skipping publish (will auto-reconnect)")
            else:
                payload = build_telemetry()
                topic = f"telemetry/{config.DEVICE_ID}/{payload['target_id']}"
                info = client.publish(topic, json.dumps(payload), qos=1)
                log.info(
                    "telemetry published topic=%s mid=%s rtt_avg=%.1f loss=%.1f",
                    topic,
                    info.mid,
                    payload["metrics"]["icmp"]["rtt_avg_ms"],
                    payload["metrics"]["icmp"]["loss_pct"],
                )
        except Exception as exc:
            log.error("telemetry publish error err=%s", exc)

        # Sleep in small increments so we respond to shutdown quickly
        with _state_lock:
            interval = _state["interval_s"]
        for _ in range(interval * 10):
            if _shutdown.is_set():
                return
            time.sleep(0.1)


def main() -> None:
    log.info("starting edge-agent device_id=%s network=%s",
             config.DEVICE_ID, config.NETWORK_TYPE)

    client = create_mqtt_client()

    # Graceful shutdown on SIGINT / SIGTERM
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("received signal=%d, shutting down", signum)
        _shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Connect (blocking with retry)
    while not _shutdown.is_set():
        try:
            client.connect(config.MQTT_HOST, config.MQTT_PORT,
                           keepalive=config.MQTT_KEEPALIVE)
            break
        except OSError as exc:
            log.error("mqtt connect failed err=%s, retrying in 5s", exc)
            _shutdown.wait(5)

    # Start the MQTT network loop in a background thread
    client.loop_start()

    try:
        telemetry_loop(client)
    finally:
        log.info("stopping mqtt loop")
        client.loop_stop()
        client.disconnect()
        log.info("edge-agent stopped")


if __name__ == "__main__":
    main()
