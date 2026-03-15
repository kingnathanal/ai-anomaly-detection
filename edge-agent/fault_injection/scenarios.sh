#!/usr/bin/env bash
set -euo pipefail

# ── scenarios.sh ─────────────────────────────────────────────────
# Run a scripted sequence of netem fault-injection experiments.
# Outputs JSON lines with ground-truth timestamps for each phase.
#
# Usage:
#   sudo bash scenarios.sh [-i <iface>]
#
# Default interface: eth0
# Fault injection is scoped to the primary endpoint IP (PRIMARY_IP) so
# backup endpoint traffic is unaffected — enabling clean before/after
# latency comparison after failover mitigation.
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IFACE="${1:-eth0}"

# Primary EC2 endpoint IP — netem faults are scoped to this destination only
PRIMARY_IP="54.198.26.122"

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
echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"event\":\"scenario_start\",\"iface\":\"${IFACE}\"}"

# Phase 1: Baseline (clean) — 2 minutes
run_phase "baseline"       120

# Phase 2: Delay 100ms ± 20ms — 5 minutes (scoped to primary IP)
run_phase "delay_100ms"    300  -d 100 -j 20 -t "$PRIMARY_IP"

# Phase 3: Recovery — 2 minutes
run_phase "recover_1"      120

# Phase 4: Packet loss 2% — 3 minutes (scoped to primary IP)
run_phase "loss_2pct"      180  -l 2 -t "$PRIMARY_IP"

# Phase 5: Recovery — 2 minutes
run_phase "recover_2"      120

# Clean up
bash "${SCRIPT_DIR}/netem_clear.sh" -i "$IFACE" >/dev/null

echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"event\":\"scenario_end\",\"iface\":\"${IFACE}\"}"
echo "# ── Scenario run complete ──────────────────────────────"
