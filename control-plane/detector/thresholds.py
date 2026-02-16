"""Threshold calibration helpers for anomaly scoring."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("detector.thresholds")


def calibrate_percentile(
    baseline_scores: list[float],
    percentile: float = 97.5,
) -> float:
    """Return the score threshold at the given percentile of baseline scores.

    Scores above this value are flagged as anomalies.
    """
    if not baseline_scores:
        log.warning("empty baseline scores; using default threshold=0.0")
        return 0.0
    threshold = float(np.percentile(baseline_scores, percentile))
    log.info("calibrated threshold=%.4f at p%.1f from %d baseline scores",
             threshold, percentile, len(baseline_scores))
    return threshold
