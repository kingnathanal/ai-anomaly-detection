#!/usr/bin/env bash
set -euo pipefail

# ── netem_apply.sh ───────────────────────────────────────────────
# Apply tc netem rules to inject delay, jitter, and/or packet loss.
#
# Usage:
#   sudo bash netem_apply.sh -i <iface> [-d <delay_ms>] [-j <jitter_ms>] [-l <loss_pct>] [-t <target_ip>]
#
# Examples:
#   sudo bash netem_apply.sh -i eth0 -d 100 -j 20
#   sudo bash netem_apply.sh -i wlan0 -l 2
#   sudo bash netem_apply.sh -i eth0 -d 50 -l 1 -t 8.8.8.8
# ─────────────────────────────────────────────────────────────────

IFACE=""
DELAY_MS=""
JITTER_MS=""
LOSS_PCT=""
TARGET_IP=""

usage() {
  echo "Usage: sudo $0 -i <iface> [-d <delay_ms>] [-j <jitter_ms>] [-l <loss_pct>] [-t <target_ip>]"
  exit 1
}

while getopts "i:d:j:l:t:" opt; do
  case "$opt" in
    i) IFACE="$OPTARG" ;;
    d) DELAY_MS="$OPTARG" ;;
    j) JITTER_MS="$OPTARG" ;;
    l) LOSS_PCT="$OPTARG" ;;
    t) TARGET_IP="$OPTARG" ;;
    *) usage ;;
  esac
done

[[ -z "$IFACE" ]] && { echo "ERROR: -i <iface> is required"; usage; }
[[ -z "$DELAY_MS" && -z "$LOSS_PCT" ]] && { echo "ERROR: specify at least -d or -l"; usage; }
[[ $EUID -ne 0 ]] && { echo "ERROR: run as root (sudo)"; exit 1; }

# Build the netem parameters string
NETEM_PARAMS=""
if [[ -n "$DELAY_MS" ]]; then
  NETEM_PARAMS+="delay ${DELAY_MS}ms"
  if [[ -n "$JITTER_MS" ]]; then
    NETEM_PARAMS+=" ${JITTER_MS}ms distribution normal"
  fi
fi
if [[ -n "$LOSS_PCT" ]]; then
  [[ -n "$NETEM_PARAMS" ]] && NETEM_PARAMS+=" "
  NETEM_PARAMS+="loss ${LOSS_PCT}%"
fi

# Clear any existing qdisc first (ignore errors if none exists)
tc qdisc del dev "$IFACE" root 2>/dev/null || true

if [[ -n "$TARGET_IP" ]]; then
  # Scoped to a specific destination IP using a prio qdisc + filter
  tc qdisc add dev "$IFACE" root handle 1: prio
  tc qdisc add dev "$IFACE" parent 1:3 handle 30: netem $NETEM_PARAMS
  tc filter add dev "$IFACE" protocol ip parent 1:0 prio 3 u32 \
    match ip dst "$TARGET_IP"/32 flowid 1:3
  echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"action\":\"netem_apply\",\"iface\":\"$IFACE\",\"params\":\"$NETEM_PARAMS\",\"target_ip\":\"$TARGET_IP\"}"
else
  # Apply to all traffic on the interface
  tc qdisc add dev "$IFACE" root netem $NETEM_PARAMS
  echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"action\":\"netem_apply\",\"iface\":\"$IFACE\",\"params\":\"$NETEM_PARAMS\",\"target_ip\":\"all\"}"
fi
