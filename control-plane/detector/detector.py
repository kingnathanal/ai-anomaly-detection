#!/usr/bin/env python3
"""
Anomaly Detector Service
========================
Trains an Isolation Forest on baseline telemetry (first 24 h) and then
continuously scores new windows, writing anomaly_events to Postgres.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import psycopg2
import psycopg2.pool
from sklearn.ensemble import IsolationForest

import features as feat
from thresholds import calibrate_percentile

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
log = logging.getLogger("detector")

_shutdown = threading.Event()

MODEL_VERSION = "iforest-v1"
BASELINE_HOURS = int(os.environ.get("BASELINE_HOURS", "24"))
# SCORE_INTERVAL_S: how often (in seconds) the detector scores the most recent window.
# Must be <= WINDOW_LENGTH_S (features.py, default 120s) so each cycle has a full
# window of samples to score. Setting this equal to WINDOW_LENGTH_S (120s) means
# non-overlapping windows and median MTTD of ~60s. Reducing it (e.g. 30s) causes
# overlapping windows but scores 4x more often, reducing median MTTD to ~15s at
# the cost of more DB reads and more anomaly_events rows.
# Chosen default of 120s: conservative, matches window length, low DB load for a
# 6-node testbed on a t3.micro EC2. For production with tighter SLAs, reduce to 30s.
SCORE_INTERVAL_S = int(os.environ.get("SCORE_INTERVAL_S", "120"))
CONTAMINATION = float(os.environ.get("CONTAMINATION", "0.01"))
THRESHOLD_PERCENTILE = float(os.environ.get("THRESHOLD_PERCENTILE", "97.5"))


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


# ── Baseline training ───────────────────────────────────────────

def train_baseline(
    conn: Any,
    device_id: str,
    target_id: str,
    baseline_end: datetime,
) -> tuple[IsolationForest, float] | None:
    """Train Isolation Forest on baseline windows and return (model, threshold)."""
    baseline_start = baseline_end - timedelta(hours=BASELINE_HOURS)
    window_len = timedelta(seconds=feat.WINDOW_LENGTH_S)

    vectors: list[list[float]] = []
    t = baseline_start
    while t + window_len <= baseline_end:
        f = feat.compute_window_features(conn, device_id, target_id, t, t + window_len)
        if f is not None:
            vectors.append(feat.features_to_vector(f))
        t += window_len

    if len(vectors) < 10:
        log.warning("not enough baseline windows device=%s target=%s count=%d",
                    device_id, target_id, len(vectors))
        return None

    X = np.array(vectors)
    model = IsolationForest(
        contamination=CONTAMINATION,
        n_estimators=100,
        random_state=42,
    )
    model.fit(X)

    scores = (-model.score_samples(X)).tolist()
    threshold = calibrate_percentile(scores, THRESHOLD_PERCENTILE)

    log.info("trained model device=%s target=%s windows=%d threshold=%.4f",
             device_id, target_id, len(vectors), threshold)
    return model, threshold


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
    model: IsolationForest,
    threshold: float,
    device_id: str,
    target_id: str,
    window_start: datetime,
    window_end: datetime,
) -> bool | None:
    """Score one window. Returns True if anomaly, False if normal, None if skip."""
    f = feat.compute_window_features(conn, device_id, target_id, window_start, window_end)
    if f is None:
        return None

    vec = np.array([feat.features_to_vector(f)])
    score = float(-model.score_samples(vec)[0])
    is_anomaly = score > threshold

    row = {
        "event_ts": datetime.now(timezone.utc),
        "device_id": device_id,
        "target_id": target_id,
        "model_version": MODEL_VERSION,
        "anomaly_score": round(score, 6),
        "threshold": round(threshold, 6),
        "is_anomaly": is_anomaly,
        "window_start_ts": window_start,
        "window_end_ts": window_end,
        "features": json.dumps(f),
    }
    with conn.cursor() as cur:
        cur.execute(INSERT_ANOMALY, row)
    conn.commit()

    level = logging.WARNING if is_anomaly else logging.DEBUG
    log.log(level,
            "scored device=%s target=%s score=%.4f threshold=%.4f anomaly=%s",
            device_id, target_id, score, threshold, is_anomaly)
    return is_anomaly


# ── Main loop ────────────────────────────────────────────────────

def main() -> None:
    log.info("starting detector service baseline_hours=%d score_interval=%ds",
             BASELINE_HOURS, SCORE_INTERVAL_S)

    def _sig(signum: int, _f: Any) -> None:
        log.info("signal=%d, shutting down", signum)
        _shutdown.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    init_pool()

    # Wait for baseline period to elapse
    log.info("waiting for baseline data (%d hours)...", BASELINE_HOURS)
    # In practice the service starts after data has been collecting.
    # Here we just check if enough data exists and train.

    models: dict[tuple[str, str], tuple[IsolationForest, float]] = {}
    window_len = timedelta(seconds=feat.WINDOW_LENGTH_S)

    while not _shutdown.is_set():
        conn = get_conn()
        try:
            now = datetime.now(timezone.utc)

            # Discover device/target pairs
            pairs = get_device_targets(conn, now - timedelta(hours=BASELINE_HOURS + 1))

            for device_id, target_id in pairs:
                key = (device_id, target_id)

                # Train if not yet trained
                if key not in models:
                    result = train_baseline(conn, device_id, target_id, now)
                    if result:
                        models[key] = result
                    continue

                model, threshold = models[key]

                # Score the most recent window
                window_end = now
                window_start = now - window_len
                score_window(conn, model, threshold, device_id, target_id,
                             window_start, window_end)

        except Exception as exc:
            log.error("detector loop error err=%s", exc)
        finally:
            put_conn(conn)

        # Wait for next scoring cycle
        for _ in range(SCORE_INTERVAL_S * 10):
            if _shutdown.is_set():
                break
            time.sleep(0.1)

    if _pool:
        _pool.closeall()
    log.info("detector service stopped")


if __name__ == "__main__":
    main()
