#!/usr/bin/env python3
"""
Ingestion Service
=================
Subscribes to MQTT telemetry/# and writes every message to Postgres.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from typing import Any

import db
import mqtt_client

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
log = logging.getLogger("ingestion")

_shutdown = threading.Event()


def on_telemetry(payload: dict[str, Any]) -> None:
    """Callback: insert telemetry row into Postgres."""
    try:
        db.insert_telemetry(payload)
    except Exception as exc:
        log.error("db insert failed device=%s err=%s",
                  payload.get("device_id", "?"), exc)


def main() -> None:
    log.info("starting ingestion service")

    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("received signal=%d, shutting down", signum)
        _shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    db.init_pool()

    client = mqtt_client.create_client(on_telemetry)
    client.loop_start()

    log.info("ingestion service running")
    _shutdown.wait()

    log.info("stopping ingestion service")
    client.loop_stop()
    client.disconnect()
    db.close_pool()
    log.info("ingestion service stopped")


if __name__ == "__main__":
    main()
