"""Database helper — connection pool and insert operations for Postgres."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

import psycopg2
import psycopg2.pool

log = logging.getLogger("ingestion.db")

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _dsn() -> str:
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "telemetry")
    user = os.environ.get("DB_USER", "telemetry_user")
    pw = os.environ.get("DB_PASS", "change_me_now")
    return f"host={host} port={port} dbname={name} user={user} password={pw}"


def init_pool(min_conn: int = 2, max_conn: int = 10) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = psycopg2.pool.ThreadedConnectionPool(min_conn, max_conn, _dsn())
    log.info("db pool created min=%d max=%d", min_conn, max_conn)


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        log.info("db pool closed")


@contextmanager
def get_conn() -> Generator:
    assert _pool is not None, "Call init_pool() first"
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


INSERT_TELEMETRY = """
INSERT INTO telemetry_measurements (
    ts, device_id, network_type, target_id, interval_s,
    icmp_ok, icmp_rtt_min_ms, icmp_rtt_avg_ms, icmp_rtt_max_ms, icmp_loss_pct,
    dns_ok, dns_latency_ms,
    http_ok, http_latency_ms, http_status, http_url
) VALUES (
    %(ts)s, %(device_id)s, %(network_type)s, %(target_id)s, %(interval_s)s,
    %(icmp_ok)s, %(icmp_rtt_min_ms)s, %(icmp_rtt_avg_ms)s, %(icmp_rtt_max_ms)s, %(icmp_loss_pct)s,
    %(dns_ok)s, %(dns_latency_ms)s,
    %(http_ok)s, %(http_latency_ms)s, %(http_status)s, %(http_url)s
)
"""


def insert_telemetry(payload: dict[str, Any]) -> None:
    """Insert a single telemetry message into Postgres."""
    metrics = payload.get("metrics", {})
    icmp = metrics.get("icmp", {})
    dns = metrics.get("dns", {})
    http = metrics.get("http", {})

    row = {
        "ts": payload["ts"],
        "device_id": payload["device_id"],
        "network_type": payload["network_type"],
        "target_id": payload["target_id"],
        "interval_s": payload["interval_s"],
        "icmp_ok": icmp.get("ok"),
        "icmp_rtt_min_ms": icmp.get("rtt_min_ms"),
        "icmp_rtt_avg_ms": icmp.get("rtt_avg_ms"),
        "icmp_rtt_max_ms": icmp.get("rtt_max_ms"),
        "icmp_loss_pct": icmp.get("loss_pct"),
        "dns_ok": dns.get("ok"),
        "dns_latency_ms": dns.get("latency_ms"),
        "http_ok": http.get("ok"),
        "http_latency_ms": http.get("latency_ms"),
        "http_status": http.get("status"),
        "http_url": http.get("url"),
    }

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(INSERT_TELEMETRY, row)
    log.debug("inserted telemetry device=%s ts=%s", row["device_id"], row["ts"])
