#!/usr/bin/env bash
# deploy.sh - Deploy Grafana configuration and dashboards to existing Grafana installation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Deploying Grafana configuration..."

# Create provisioning directories if they don't exist
sudo mkdir -p /etc/grafana/provisioning/datasources
sudo mkdir -p /etc/grafana/provisioning/dashboards
sudo mkdir -p /var/lib/grafana/dashboards

# Copy datasource configuration
echo "Setting up Postgres datasource..."
sudo cp "$SCRIPT_DIR/provisioning/datasources/postgres.yml" /etc/grafana/provisioning/datasources/

# Copy dashboard provisioning configuration
echo "Setting up dashboard provisioning..."
sudo cp "$SCRIPT_DIR/provisioning/dashboards/dashboards.yml" /etc/grafana/provisioning/dashboards/

# Copy dashboard JSON files
echo "Copying dashboard files..."
sudo cp "$SCRIPT_DIR/dashboards/"*.json /var/lib/grafana/dashboards/

# Set proper permissions
sudo chown -R grafana:grafana /var/lib/grafana/dashboards
sudo chmod 644 /var/lib/grafana/dashboards/*.json

# Configure environment variables for datasource
echo "Configuring database credentials..."
sudo mkdir -p /etc/systemd/system/grafana-server.service.d

# Read credentials from .env.example (which has been updated with real values)
DB_NAME=$(grep "^DB_NAME=" "$SCRIPT_DIR/.env.example" | cut -d'=' -f2 || echo "telemetry")
DB_USER=$(grep "^DB_USER=" "$SCRIPT_DIR/.env.example" | cut -d'=' -f2 || echo "telemetry_user")
DB_PASS=$(grep "^DB_PASS=" "$SCRIPT_DIR/.env.example" | cut -d'=' -f2 || echo "change_me_now")
GF_ROOT_URL=$(grep "^GF_SERVER_ROOT_URL=" "$SCRIPT_DIR/.env.example" | cut -d'=' -f2 || echo "http://localhost:3000")
GF_ADMIN_PASS=$(grep "^GF_SECURITY_ADMIN_PASSWORD=" "$SCRIPT_DIR/.env.example" | cut -d'=' -f2 || echo "admin")

# Create systemd override for environment variables
sudo tee /etc/systemd/system/grafana-server.service.d/override.conf > /dev/null <<EOF
[Service]
Environment="DB_NAME=${DB_NAME}"
Environment="DB_USER=${DB_USER}"
Environment="DB_PASS=${DB_PASS}"
Environment="GF_SERVER_ROOT_URL=${GF_ROOT_URL}"
Environment="GF_SECURITY_ADMIN_PASSWORD=${GF_ADMIN_PASS}"
EOF

echo "Reloading systemd and restarting Grafana..."
sudo systemctl daemon-reload
sudo systemctl restart grafana-server

# Wait a moment for Grafana to start
sleep 3

# Check Grafana status
if sudo systemctl is-active --quiet grafana-server; then
    echo ""
    echo "✓ Grafana deployment complete!"
    echo ""
    echo "Grafana is running at: ${GF_ROOT_URL}"
    echo ""
    echo "Default credentials:"
    echo "  Username: admin"
    echo "  Password: ${GF_ADMIN_PASS}"
    echo ""
    echo "Available dashboards:"
    echo "  - Latency Overview"
    echo "  - Anomaly Detection"
    echo "  - LAN vs WiFi Comparison"
    echo ""
    echo "To verify datasource connection:"
    echo "  Go to Configuration → Data Sources → Telemetry Postgres → Test"
    echo ""
else
    echo ""
    echo "⚠ Grafana failed to start. Check logs:"
    echo "  sudo journalctl -u grafana-server -n 50"
    exit 1
fi
