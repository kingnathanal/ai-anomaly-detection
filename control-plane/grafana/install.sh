#!/usr/bin/env bash
# install.sh - Install and configure Grafana on Ubuntu EC2

set -euo pipefail

echo "Installing Grafana on Ubuntu..."

# Add Grafana GPG key and repository
sudo apt-get install -y apt-transport-https software-properties-common wget
sudo mkdir -p /etc/apt/keyrings/
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null

# Add stable repository
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list

# Update and install Grafana
sudo apt-get update
sudo apt-get install -y grafana

# Enable and start Grafana service
sudo systemctl daemon-reload
sudo systemctl enable grafana-server
sudo systemctl start grafana-server

echo "Grafana installed successfully!"
echo "Default URL: http://localhost:3000"
echo "Default credentials: admin / admin (you'll be prompted to change on first login)"

# Create provisioning directories if they don't exist
sudo mkdir -p /etc/grafana/provisioning/datasources
sudo mkdir -p /etc/grafana/provisioning/dashboards

# Copy datasource configuration
echo "Setting up Postgres datasource..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "$SCRIPT_DIR/provisioning/datasources/postgres.yml" /etc/grafana/provisioning/datasources/

# Copy dashboard provisioning
echo "Setting up dashboard provisioning..."
sudo cp "$SCRIPT_DIR/provisioning/dashboards/dashboards.yml" /etc/grafana/provisioning/dashboards/
sudo mkdir -p /var/lib/grafana/dashboards
sudo cp "$SCRIPT_DIR/dashboards/"*.json /var/lib/grafana/dashboards/ 2>/dev/null || echo "No dashboard files found yet"

# Restart Grafana to load configurations
sudo systemctl restart grafana-server

echo ""
echo "✓ Grafana setup complete!"
echo ""
echo "Next steps:"
echo "1. Access Grafana at http://<ec2-public-ip>:3000"
echo "2. Login with admin/admin (change password on first login)"
echo "3. Verify Postgres datasource connection"
echo "4. View pre-configured dashboards"
echo ""
echo "Note: Ensure port 3000 is open in your EC2 security group"
