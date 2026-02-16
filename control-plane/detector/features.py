"""Feature windowing — aggregate raw telemetry into per-window feature vectors."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import psycopg2

log = logging.getLogger("detector.features")

# Window length: 120 seconds (12 samples at 10s intervals)
WINDOW_LENGTH_S = 120

QUERY_WINDOW = """
SELECT
    ts,
    icmp_rtt_avg_ms, icmp_rtt_max_ms, icmp_loss_pct,
    dns_latency_ms, dns_ok,
    http_latency_ms, http_ok
FROM telemetry_measurements
WHERE device_id = %(device_id)s
  AND target_id = %(target_id)s
  AND ts >= %(window_start)s
  AND ts <  %(window_end)s
ORDER BY ts
"""


def compute_window_features(
    conn: Any,
    device_id: str,
    target_id: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, float] | None:
    """Query telemetry for the given window and return a feature dict.

    Returns None if not enough samples are available.
    """
    with conn.cursor() as cur:
        cur.execute(QUERY_WINDOW, {
            "device_id": device_id,
            "target_id": target_id,
            "window_start": window_start,
            "window_end": window_end,
        })
        rows = cur.fetchall()

    if len(rows) < 3:
        log.debug("insufficient samples device=%s window=%s count=%d",
                  device_id, window_start, len(rows))
        return None

    rtt_avgs = [r[1] for r in rows if r[1] is not None]
    rtt_maxs = [r[2] for r in rows if r[2] is not None]
    losses = [r[3] for r in rows if r[3] is not None]
    dns_lats = [r[4] for r in rows if r[4] is not None]
    dns_oks = [r[5] for r in rows]
    http_lats = [r[6] for r in rows if r[6] is not None]
    http_oks = [r[7] for r in rows]

    def _safe_mean(vals: list[float]) -> float:
        return float(np.mean(vals)) if vals else 0.0

    def _safe_std(vals: list[float]) -> float:
        return float(np.std(vals)) if vals else 0.0

    def _safe_max(vals: list[float]) -> float:
        return float(np.max(vals)) if vals else 0.0

    def _safe_p95(vals: list[float]) -> float:
        return float(np.percentile(vals, 95)) if vals else 0.0

    total = len(rows)
    dns_fail_rate = sum(1 for ok in dns_oks if ok is False) / total if total else 0.0
    http_err_rate = sum(1 for ok in http_oks if ok is False) / total if total else 0.0

    return {
        "rtt_mean": round(_safe_mean(rtt_avgs), 3),
        "rtt_std": round(_safe_std(rtt_avgs), 3),
        "rtt_max": round(_safe_max(rtt_maxs), 3),
        "loss_mean": round(_safe_mean(losses), 3),
        "dns_latency_mean": round(_safe_mean(dns_lats), 3),
        "dns_fail_rate": round(dns_fail_rate, 4),
        "http_latency_mean": round(_safe_mean(http_lats), 3),
        "http_latency_p95": round(_safe_p95(http_lats), 3),
        "http_error_rate": round(http_err_rate, 4),
    }


# Feature names in consistent order for the model
FEATURE_NAMES = [
    "rtt_mean", "rtt_std", "rtt_max", "loss_mean",
    "dns_latency_mean", "dns_fail_rate",
    "http_latency_mean", "http_latency_p95", "http_error_rate",
]


def features_to_vector(features: dict[str, float]) -> list[float]:
    """Convert a feature dict to an ordered list for the model."""
    return [features[k] for k in FEATURE_NAMES]
