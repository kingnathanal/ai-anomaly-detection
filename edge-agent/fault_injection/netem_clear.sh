#!/usr/bin/env bash
set -euo pipefail

# ── netem_clear.sh ───────────────────────────────────────────────
# Remove all tc netem rules from an interface.
#
# Usage:
#   sudo bash netem_clear.sh -i <iface>
# ─────────────────────────────────────────────────────────────────

IFACE=""

while getopts "i:" opt; do
  case "$opt" in
    i) IFACE="$OPTARG" ;;
    *) echo "Usage: sudo $0 -i <iface>"; exit 1 ;;
  esac
done

[[ -z "$IFACE" ]] && { echo "ERROR: -i <iface> is required"; exit 1; }
[[ $EUID -ne 0 ]] && { echo "ERROR: run as root (sudo)"; exit 1; }

tc qdisc del dev "$IFACE" root 2>/dev/null || true

echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\",\"action\":\"netem_clear\",\"iface\":\"$IFACE\"}"
