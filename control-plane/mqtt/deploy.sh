#!/usr/bin/env bash
# deploy.sh - Install and configure Mosquitto MQTT broker on EC2 control plane
# Usage: sudo ./deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Mosquitto MQTT Broker Setup ==="

# ── Install Mosquitto ────────────────────────────────────────────
if ! command -v mosquitto &>/dev/null; then
    echo "Installing Mosquitto..."
    apt-get update -qq
    apt-get install -y mosquitto mosquitto-clients
else
    echo "Mosquitto already installed: $(mosquitto -h 2>&1 | head -1 || true)"
fi

# ── Load credentials ────────────────────────────────────────────
MQTT_USER=$(grep "^MQTT_USER=" "$SCRIPT_DIR/.env.example" | cut -d'=' -f2 || echo "telemetry_agent")
MQTT_PASS=$(grep "^MQTT_PASS=" "$SCRIPT_DIR/.env.example" | cut -d'=' -f2 || echo "change_me_now")

if [ "$MQTT_PASS" = "change_me_now" ]; then
    echo ""
    echo "⚠  WARNING: Using default password. Edit .env.example with a real password first!"
    echo ""
fi

# ── Deploy configuration ────────────────────────────────────────
echo "Deploying Mosquitto configuration..."

# Back up and replace the default config to avoid listener/setting conflicts.
# Ubuntu's default mosquitto.conf includes conf.d/ and may set per_listener_settings
# or bind_address which clashes with our config.
if [ -f /etc/mosquitto/mosquitto.conf ] && [ ! -f /etc/mosquitto/mosquitto.conf.bak ]; then
    cp /etc/mosquitto/mosquitto.conf /etc/mosquitto/mosquitto.conf.bak
    echo "Backed up original config to /etc/mosquitto/mosquitto.conf.bak"
fi

# Write a minimal main config that just includes our conf.d file
cat > /etc/mosquitto/mosquitto.conf <<MAINCONF
# Minimal config — all settings in conf.d/anomaly-detection.conf
pid_file /run/mosquitto/mosquitto.pid
persistence true
persistence_location /var/lib/mosquitto/
include_dir /etc/mosquitto/conf.d
MAINCONF

# Remove any other conf.d files that might conflict
find /etc/mosquitto/conf.d/ -type f ! -name 'anomaly-detection.conf' -delete 2>/dev/null || true

cp "$SCRIPT_DIR/mosquitto.conf" /etc/mosquitto/conf.d/anomaly-detection.conf
chown mosquitto:mosquitto /etc/mosquitto/conf.d/anomaly-detection.conf
chmod 644 /etc/mosquitto/conf.d/anomaly-detection.conf

# ── Ensure required directories exist with correct permissions ──
mkdir -p /var/lib/mosquitto /run/mosquitto /var/log/mosquitto
chown mosquitto:mosquitto /var/lib/mosquitto /run/mosquitto /var/log/mosquitto
chmod 750 /var/lib/mosquitto /run/mosquitto /var/log/mosquitto

# ── Validate config before restarting ───────────────────────────
echo "Validating Mosquitto configuration..."
# Mosquitto 2.x doesn't have a -t flag; run in foreground briefly to check config
CONFIG_CHECK=$(timeout 2 mosquitto -c /etc/mosquitto/mosquitto.conf -v 2>&1 || true)
if echo "$CONFIG_CHECK" | grep -qi "error"; then
    echo ""
    echo "✗ Configuration validation failed:"
    echo "$CONFIG_CHECK"
    exit 1
fi
echo "Configuration OK."

# ── Create password file ────────────────────────────────────────
echo "Creating MQTT user: ${MQTT_USER}"
# Create fresh password file
touch /etc/mosquitto/passwd
mosquitto_passwd -b /etc/mosquitto/passwd "$MQTT_USER" "$MQTT_PASS"
chown mosquitto:mosquitto /etc/mosquitto/passwd
chmod 600 /etc/mosquitto/passwd

# ── Enable and restart ──────────────────────────────────────────
echo "Enabling and restarting Mosquitto..."
systemctl enable mosquitto
systemctl restart mosquitto

sleep 2

# ── Verify ───────────────────────────────────────────────────────
if systemctl is-active --quiet mosquitto; then
    echo ""
    echo "✓ Mosquitto is running!"
    echo ""
    echo "Broker:    0.0.0.0:1883"
    echo "User:      ${MQTT_USER}"
    echo ""
    echo "Quick test (from this host):"
    echo "  mosquitto_sub -h localhost -t 'test/#' -u ${MQTT_USER} -P '${MQTT_PASS}' &"
    echo "  mosquitto_pub -h localhost -t 'test/hello' -m 'it works' -u ${MQTT_USER} -P '${MQTT_PASS}'"
    echo ""
    echo "From a Pi:"
    echo "  mosquitto_pub -h 54.198.26.122 -t 'test/hello' -m 'from pi' -u ${MQTT_USER} -P '${MQTT_PASS}'"
    echo ""
    echo "⚠  Make sure EC2 security group allows inbound TCP 1883 from your Pi IPs."
    echo ""
else
    echo ""
    echo "✗ Mosquitto failed to start. Check logs:"
    echo "  sudo journalctl -u mosquitto -n 30"
    echo ""
    exit 1
fi
