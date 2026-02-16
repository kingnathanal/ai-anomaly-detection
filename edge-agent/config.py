"""Edge-agent configuration — loaded from environment variables."""

from __future__ import annotations

import os


def _env(key: str, default: str | None = None) -> str:
    """Return an env var or *default*; raise if neither exists."""
    val = os.environ.get(key, default)
    if val is None:
        raise RuntimeError(f"Required environment variable {key} is not set")
    return val


# ── Identity ────────────────────────────────────────────────────
# Actual node names: pi00-wifi, pi01-wifi, pi02-wifi, pi03-lan, pi04-lan, pi05-lan
DEVICE_ID: str = _env("DEVICE_ID", "pi03-lan")
NETWORK_TYPE: str = _env("NETWORK_TYPE", "lan")  # "lan" | "wifi"

# ── MQTT broker ─────────────────────────────────────────────────
MQTT_HOST: str = _env("MQTT_HOST", "localhost")
MQTT_PORT: int = int(_env("MQTT_PORT", "1883"))
MQTT_USER: str | None = os.environ.get("MQTT_USER")
MQTT_PASS: str | None = os.environ.get("MQTT_PASS")
MQTT_KEEPALIVE: int = int(_env("MQTT_KEEPALIVE", "60"))

# ── Probe targets ───────────────────────────────────────────────
# Defaults — overridden at runtime by mitigation commands.
PROBE_INTERVAL_S: int = int(_env("PROBE_INTERVAL_S", "10"))

# Default ICMP target = EC2 control plane (same host as MQTT broker)
ICMP_TARGET: str = _env("ICMP_TARGET", "ec2")
ICMP_COUNT: int = int(_env("ICMP_COUNT", "3"))
ICMP_TIMEOUT_S: int = int(_env("ICMP_TIMEOUT_S", "5"))

DNS_QUERY: str = _env("DNS_QUERY", "example.com")
DNS_TIMEOUT_S: int = int(_env("DNS_TIMEOUT_S", "5"))

# Targets dict: target_id -> http_url
# Primary = health endpoint on EC2 control plane (measures real edge→cloud path)
# Backup  = reliable public endpoint (failover during mitigation)
HTTP_TARGETS: dict[str, str] = {
    "primary": _env("HTTP_URL_PRIMARY", "http://ec2:8080/health"),
    "backup": _env("HTTP_URL_BACKUP", "https://1.1.1.1"),
}

ACTIVE_TARGET_ID: str = _env("ACTIVE_TARGET_ID", "primary")
HTTP_TIMEOUT_S: int = int(_env("HTTP_TIMEOUT_S", "10"))

# ── Logging ─────────────────────────────────────────────────────
LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")
