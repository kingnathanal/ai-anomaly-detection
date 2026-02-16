"""
Health-check HTTP endpoint for edge-agent probes.

Runs on the EC2 control plane so probes measure the real
edge → cloud network path.  Includes an optional /degrade
endpoint that lets experimenters simulate server-side
latency for controlled tests.
"""

from __future__ import annotations

import logging
import os
import platform
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HOST = os.getenv("HEALTH_HOST", "0.0.0.0")
PORT = int(os.getenv("HEALTH_PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("health")

# Shared degradation state (thread-safe via lock)
_degrade_lock = threading.Lock()
_degrade: dict = {"enabled": False, "delay_ms": 0}

# Start time for uptime calculation
_start_ts = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    """Primary health endpoint that edge agents probe.

    Returns 200 with a small JSON body.  If degradation is
    enabled, sleeps for the configured delay before responding.
    """
    with _degrade_lock:
        delay_ms = _degrade["delay_ms"] if _degrade["enabled"] else 0

    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    now = datetime.now(timezone.utc)
    uptime_s = (now - _start_ts).total_seconds()

    return jsonify({
        "status": "ok",
        "ts": now.isoformat(),
        "uptime_s": round(uptime_s, 1),
        "degraded": delay_ms > 0,
        "delay_ms": delay_ms,
        "hostname": platform.node(),
    }), 200


@app.route("/", methods=["GET"])
def index():
    """Basic info page."""
    return jsonify({
        "service": "edge-health-endpoint",
        "version": "1.0.0",
        "endpoints": ["/", "/health", "/degrade"],
    }), 200


@app.route("/degrade", methods=["GET", "POST", "DELETE"])
def degrade():
    """Toggle artificial server-side latency for experiments.

    GET    → show current degradation state
    POST   → enable degradation.  Body JSON: {"delay_ms": 500}
    DELETE → disable degradation
    """
    if request.method == "GET":
        with _degrade_lock:
            state = dict(_degrade)
        return jsonify(state), 200

    if request.method == "DELETE":
        with _degrade_lock:
            _degrade["enabled"] = False
            _degrade["delay_ms"] = 0
        log.info("degradation_disabled")
        return jsonify({"enabled": False, "delay_ms": 0}), 200

    # POST
    body = request.get_json(silent=True) or {}
    delay_ms = int(body.get("delay_ms", 200))
    if delay_ms < 0 or delay_ms > 30_000:
        return jsonify({"error": "delay_ms must be 0-30000"}), 400

    with _degrade_lock:
        _degrade["enabled"] = True
        _degrade["delay_ms"] = delay_ms

    log.info("degradation_enabled delay_ms=%d", delay_ms)
    return jsonify({"enabled": True, "delay_ms": delay_ms}), 200


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("starting health endpoint on %s:%d", HOST, PORT)
    app.run(host=HOST, port=PORT, threaded=True)
