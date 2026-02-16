#!/usr/bin/env python3
"""
EMA / Z-Score Anomaly Detector
==============================
A lightweight, univariate time-series anomaly detector that maintains
per-(device, target, metric) Exponential Moving Averages and flags
anomalies when any metric's Z-score exceeds a threshold.

Writes to the same anomaly_events table as the Isolation Forest detector,
using model_version = "ema-zscore-v1" for comparison.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import psycopg2
import psycopg2.pool

import features as feat

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
log = logging.getLogger("ema_detector")

_shutdown = threading.Event()

MODEL_VERSION = "ema-zscore-v1"
SCORE_INTERVAL_S = int(os.environ.get("SCORE_INTERVAL_S", "120"))
EMA_ALPHA = float(os.environ.get("EMA_ALPHA", "0.1"))
ZSCORE_THRESHOLD = float(os.environ.get("ZSCORE_THRESHOLD", "3.0"))
WARMUP_SAMPLES = int(os.environ.get("EMA_WARMUP_SAMPLES", "60"))

# Metrics to track independently
TRACKED_METRICS = ["rtt_mean", "loss_mean", "dns_latency_mean", "http_latency_mean"]


# ── DB helpers ───────────────────────────────────────────────────

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
    _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, _dsn())


def get_conn():
    assert _pool
    return _pool.getconn()


def put_conn(conn: Any) -> None:
    assert _pool
    _pool.putconn(conn)


# ── Device / target discovery ────────────────────────────────────

QUERY_DEVICE_TARGETS = """
SELECT DISTINCT device_id, target_id
FROM telemetry_measurements
WHERE ts >= %(since)s
"""


def get_device_targets(conn: Any, since: datetime) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(QUERY_DEVICE_TARGETS, {"since": since})
        return cur.fetchall()


# ── EMA state per (device, target) ──────────────────────────────

@dataclass
class EMAState:
    """Maintains EMA and EMA-of-variance for each tracked metric."""
    ema: dict[str, float] = field(default_factory=dict)
    ema_var: dict[str, float] = field(default_factory=dict)
    samples_seen: int = 0

    @property
    def warmed_up(self) -> bool:
        return self.samples_seen >= WARMUP_SAMPLES

    def update(self, features: dict[str, float], alpha: float) -> dict[str, float]:
        """Update EMA/variance and return Z-scores for each tracked metric.

        Returns a dict of metric_name -> z_score.
        """
        zscores: dict[str, float] = {}

        for metric in TRACKED_METRICS:
            value = features.get(metric, 0.0)

            if metric not in self.ema:
                # First sample — initialise
                self.ema[metric] = value
                self.ema_var[metric] = 0.0
                zscores[metric] = 0.0
                continue

            prev_ema = self.ema[metric]
            diff = value - prev_ema

            # Update EMA
            self.ema[metric] = alpha * value + (1 - alpha) * prev_ema

            # Update EMA of variance (Welford-style with EMA)
            self.ema_var[metric] = (1 - alpha) * (self.ema_var[metric] + alpha * diff * diff)

            # Compute Z-score
            std = max(np.sqrt(self.ema_var[metric]), 1e-9)
            zscores[metric] = diff / std

        self.samples_seen += 1
        return zscores


# ── Scoring ──────────────────────────────────────────────────────

INSERT_ANOMALY = """
INSERT INTO anomaly_events
    (event_ts, device_id, target_id, model_version,
     anomaly_score, threshold, is_anomaly,
     window_start_ts, window_end_ts, features)
VALUES
    (%(event_ts)s, %(device_id)s, %(target_id)s, %(model_version)s,
     %(anomaly_score)s, %(threshold)s, %(is_anomaly)s,
     %(window_start_ts)s, %(window_end_ts)s, %(features)s)
"""


def score_window(
    conn: Any,
    state: EMAState,
    device_id: str,
    target_id: str,
    window_start: datetime,
    window_end: datetime,
) -> bool | None:
    """Score one window using EMA/Z-score. Returns True/False/None."""
    f = feat.compute_window_features(conn, device_id, target_id, window_start, window_end)
    if f is None:
        return None

    zscores = state.update(f, EMA_ALPHA)

    if not state.warmed_up:
        log.debug("warming up device=%s samples=%d/%d",
                  device_id, state.samples_seen, WARMUP_SAMPLES)
        return None

    # Anomaly if any metric exceeds Z-score threshold
    max_z_metric = max(zscores, key=lambda k: abs(zscores[k]))
    max_z = abs(zscores[max_z_metric])
    is_anomaly = max_z > ZSCORE_THRESHOLD

    # Build features dict with Z-scores and EMA state for debugging
    scored_features = {
        **f,
        "zscores": {k: round(v, 4) for k, v in zscores.items()},
        "ema": {k: round(v, 4) for k, v in state.ema.items()},
        "trigger_metric": max_z_metric if is_anomaly else None,
        "max_zscore": round(max_z, 4),
    }

    row = {
        "event_ts": datetime.now(timezone.utc),
        "device_id": device_id,
        "target_id": target_id,
        "model_version": MODEL_VERSION,
        "anomaly_score": round(max_z, 6),
        "threshold": ZSCORE_THRESHOLD,
        "is_anomaly": is_anomaly,
        "window_start_ts": window_start,
        "window_end_ts": window_end,
        "features": json.dumps(scored_features),
    }
    with conn.cursor() as cur:
        cur.execute(INSERT_ANOMALY, row)
    conn.commit()

    level = logging.WARNING if is_anomaly else logging.DEBUG
    log.log(level,
            "scored device=%s target=%s max_z=%.4f metric=%s threshold=%.1f anomaly=%s",
            device_id, target_id, max_z, max_z_metric, ZSCORE_THRESHOLD, is_anomaly)
    return is_anomaly


# ── Main loop ────────────────────────────────────────────────────

def main() -> None:
    log.info("starting EMA/Z-score detector alpha=%.2f z_threshold=%.1f "
             "warmup=%d score_interval=%ds",
             EMA_ALPHA, ZSCORE_THRESHOLD, WARMUP_SAMPLES, SCORE_INTERVAL_S)

    def _sig(signum: int, _f: Any) -> None:
        log.info("signal=%d, shutting down", signum)
        _shutdown.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    init_pool()

    states: dict[tuple[str, str], EMAState] = {}
    window_len = timedelta(seconds=feat.WINDOW_LENGTH_S)

    # Warm up from historical data before live scoring
    log.info("warming up EMA from historical windows...")
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc)
        # Use the last 2 hours for warm-up (60 windows at 120s each)
        warmup_hours = max(2, (WARMUP_SAMPLES * feat.WINDOW_LENGTH_S) / 3600)
        warmup_start = now - timedelta(hours=warmup_hours)
        pairs = get_device_targets(conn, warmup_start)

        for device_id, target_id in pairs:
            key = (device_id, target_id)
            state = EMAState()

            t = warmup_start
            while t + window_len <= now:
                f = feat.compute_window_features(conn, device_id, target_id, t, t + window_len)
                if f is not None:
                    state.update(f, EMA_ALPHA)
                t += window_len

            states[key] = state
            log.info("warmed up device=%s target=%s samples=%d ready=%s",
                     device_id, target_id, state.samples_seen, state.warmed_up)
    except Exception as exc:
        log.error("warm-up error err=%s", exc)
    finally:
        put_conn(conn)

    # Live scoring loop
    log.info("entering live scoring loop")
    while not _shutdown.is_set():
        conn = get_conn()
        try:
            now = datetime.now(timezone.utc)
            pairs = get_device_targets(conn, now - timedelta(hours=1))

            scored = 0
            skipped = 0
            anomalies = 0
            for device_id, target_id in pairs:
                key = (device_id, target_id)

                if key not in states:
                    states[key] = EMAState()

                window_end = now
                window_start = now - window_len
                result = score_window(conn, states[key], device_id, target_id,
                                      window_start, window_end)
                if result is None:
                    skipped += 1
                elif result:
                    anomalies += 1
                    scored += 1
                else:
                    scored += 1

            log.info("scoring cycle complete scored=%d skipped=%d anomalies=%d",
                     scored, skipped, anomalies)

        except Exception as exc:
            log.error("ema detector loop error err=%s", exc)
        finally:
            put_conn(conn)

        for _ in range(SCORE_INTERVAL_S * 10):
            if _shutdown.is_set():
                break
            time.sleep(0.1)

    if _pool:
        _pool.closeall()
    log.info("EMA/Z-score detector stopped")


if __name__ == "__main__":
    main()
