#!/bin/bash
# Remove Cloudflare Tunnel

echo "=========================================="
echo "Cloudflare Tunnel Removal"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: This script must be run as root (use sudo)"
    echo "Usage: sudo bash remove_cloudflare_tunnel.sh"
    exit 1
fi

ACTUAL_USER=${SUDO_USER:-$USER}

echo "This will remove Cloudflare Tunnel and stop remote access."
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Removal cancelled."
    exit 1
fi

echo ""
echo "[1/4] Stopping service..."
systemctl stop cloudflared

echo ""
echo "[2/4] Disabling service..."
systemctl disable cloudflared

echo ""
echo "[3/4] Removing service file..."
rm -f /etc/systemd/system/cloudflared.service
systemctl daemon-reload

echo ""
echo "[4/4] Listing tunnels..."
echo ""
echo "Available tunnels:"
sudo -u $ACTUAL_USER cloudflared tunnel list
echo ""
read -p "Enter tunnel name to delete (or press Enter to skip): " TUNNEL_NAME

if [ ! -z "$TUNNEL_NAME" ]; then
    echo "Deleting tunnel: $TUNNEL_NAME"
    sudo -u $ACTUAL_USER cloudflared tunnel delete $TUNNEL_NAME
    echo "  ✓ Tunnel deleted"
fi

echo ""
echo "=========================================="
echo "Cloudflare Tunnel Removed!"
echo "=========================================="
echo ""
echo "Note:"
echo "  - cloudflared binary still installed at /usr/local/bin/cloudflared"
echo "  - Config files still in ~/.cloudflared/"
echo "  - To completely remove, run:"
echo "    sudo rm /usr/local/bin/cloudflared"
echo "    rm -rf ~/.cloudflared"
echo "=========================================="
