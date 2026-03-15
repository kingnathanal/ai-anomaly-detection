#!/usr/bin/env bash
set -euo pipefail

# ── scenarios.sh ─────────────────────────────────────────────────
# Run a scripted sequence of netem fault-injection experiments.
# Outputs JSON lines with ground-truth timestamps for each phase.
#
# Usage:
#   sudo bash scenarios.sh [-i <iface>] [-d <delay_ms>] [-j <jitter_ms>] [-l <loss_pct>]
#
# Options:
#   -i  Network interface (default: auto-detected from hostname)
#         Hosts containing "wifi" → wlan0, all others → eth0
#   -d  Delay in ms for the delay phase     (default: 100)
#   -j  Jitter in ms for the delay phase    (default: 20)
#   -l  Packet loss % for the loss phase    (default: 2)
#
# Examples:
#   sudo bash scenarios.sh                          # Exp 1 standard (100ms/2%)
#   sudo bash scenarios.sh -d 200 -j 40 -l 5       # Exp 2 severe   (200ms/5%)
#   sudo bash scenarios.sh -d 50  -j 10 -l 1       # Exp 3 subtle   (50ms/1%)
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-detect interface from hostname
_HOSTNAME="$(hostname)"
if [[ "$_HOSTNAME" == *wifi* ]]; then
  DEFAULT_IFACE="wlan0"
else
  DEFAULT_IFACE="eth0"
fi

# Defaults
IFACE="$DEFAULT_IFACE"
DELAY_MS=100
JITTER_MS=20
LOSS_PCT=2

while getopts "i:d:j:l:" opt; do
  case "$opt" in
    i) IFACE="$OPTARG" ;;
    d) DELAY_MS="$OPTARG" ;;
    j) JITTER_MS="$OPTARG" ;;
    l) LOSS_PCT="$OPTARG" ;;
    *) echo "Usage: $0 [-i iface] [-d delay_ms] [-j jitter_ms] [-l loss_pct]" >&2; exit 1 ;;
  esac
done

# Primary EC2 endpoint IP — netem faults are scoped to this IP only.
# Backup (failover) is on a separate IP (34.226.196.133), so IP-only scoping
# is sufficient; traffic to the failover server is naturally unaffected.
PRIMARY_IP="54.198.26.122"
FAILOVER_IP="34.226.196.133"  # backup EC2, http://34.226.196.133:8080/health

log_phase() {
  local phase="$1" params="$2" duration_s="$3"
  echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"phase\":\"${phase}\",\"params\":\"${params}\",\"duration_s\":${duration_s},\"iface\":\"${IFACE}\"}"
}

run_phase() {
  local phase="$1" duration_s="$2"
  shift 2
  # remaining args are netem_apply flags (or empty for baseline/recover)
  if [[ $# -gt 0 ]]; then
    bash "${SCRIPT_DIR}/netem_apply.sh" -i "$IFACE" "$@" >/dev/null
    log_phase "$phase" "$*" "$duration_s"
  else
    bash "${SCRIPT_DIR}/netem_clear.sh" -i "$IFACE" >/dev/null
    log_phase "$phase" "none" "$duration_s"
  fi
  sleep "$duration_s"
}

echo "# ── Scenario run starting ──────────────────────────────"
echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"event\":\"scenario_start\",\"iface\":\"${IFACE}\",\"delay_ms\":${DELAY_MS},\"jitter_ms\":${JITTER_MS},\"loss_pct\":${LOSS_PCT}}"

# Phase 1: Baseline (clean) — 2 minutes
run_phase "baseline"       120

# Phase 2: Delay (scoped to primary IP only)
run_phase "delay_${DELAY_MS}ms"  300  -d "$DELAY_MS" -j "$JITTER_MS" -t "$PRIMARY_IP"

# Phase 3: Recovery — 2 minutes
run_phase "recover_1"      120

# Phase 4: Packet loss (scoped to primary IP only)
run_phase "loss_${LOSS_PCT}pct"  180  -l "$LOSS_PCT" -t "$PRIMARY_IP"

# Phase 5: Recovery — 2 minutes
run_phase "recover_2"      120

# Clean up
bash "${SCRIPT_DIR}/netem_clear.sh" -i "$IFACE" >/dev/null

echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"event\":\"scenario_end\",\"iface\":\"${IFACE}\"}"
echo "# ── Scenario run complete ──────────────────────────────"
