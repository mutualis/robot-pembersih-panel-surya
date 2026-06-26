#!/bin/bash
# Uninstall Solar Panel Cleaner systemd service

echo "=========================================="
echo "Solar Panel Cleaner - Service Uninstaller"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: This script must be run as root (use sudo)"
    echo "Usage: sudo bash uninstall_service.sh"
    exit 1
fi

SERVICE_NAME="solar-panel-cleaner.service"

echo "[1/4] Stopping service..."
systemctl stop $SERVICE_NAME

echo "[2/4] Disabling service (remove auto-start)..."
systemctl disable $SERVICE_NAME

echo "[3/4] Removing service file..."
rm -f /etc/systemd/system/$SERVICE_NAME

echo "[4/4] Reloading systemd daemon..."
systemctl daemon-reload

echo ""
echo "=========================================="
echo "Uninstallation Complete!"
echo "=========================================="
echo ""
echo "The service has been removed."
echo "You can now run the program manually with:"
echo "  cd ~/wipevision/raspberry-pi"
echo "  source venv/bin/activate"
echo "  python3 main.py"
echo "=========================================="
