#!/bin/bash
# Restore Single WiFi Mode (Client Only)
# Disable Dual WiFi Mode and restore to WiFi client only

echo "=========================================="
echo "Restore Single WiFi Mode"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: This script must be run as root (use sudo)"
    echo "Usage: sudo bash restore_single_wifi.sh"
    exit 1
fi

echo "This will:"
echo "  - Disable WiFi AP (uap0)"
echo "  - Keep WiFi Client (wlan0)"
echo "  - Restore original configuration"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Restore cancelled."
    exit 1
fi

echo ""
echo "[1/6] Stopping services..."
systemctl stop [email protected] 2>/dev/null
systemctl stop dnsmasq 2>/dev/null
systemctl stop hostapd 2>/dev/null
echo "  ✓ Services stopped"

echo ""
echo "[2/6] Disabling services..."
systemctl disable [email protected] 2>/dev/null
systemctl disable dnsmasq 2>/dev/null
systemctl disable hostapd 2>/dev/null
echo "  ✓ Services disabled"

echo ""
echo "[3/6] Removing virtual interface..."
iw dev uap0 del 2>/dev/null
echo "  ✓ Virtual interface removed"

echo ""
echo "[4/6] Restoring configuration files..."
# Restore dhcpcd.conf
if [ -f /etc/dhcpcd.conf.backup ]; then
    cp /etc/dhcpcd.conf.backup /etc/dhcpcd.conf
    echo "  ✓ dhcpcd.conf restored"
else
    # Remove dual WiFi configuration
    sed -i '/# Dual WiFi Mode Configuration/,/# End Dual WiFi Mode/d' /etc/dhcpcd.conf
    echo "  ✓ dhcpcd.conf cleaned"
fi

# Restore dnsmasq.conf
if [ -f /etc/dnsmasq.conf.backup ]; then
    cp /etc/dnsmasq.conf.backup /etc/dnsmasq.conf
    echo "  ✓ dnsmasq.conf restored"
fi

# Restore wpa_supplicant.conf
if [ -f /etc/wpa_supplicant/wpa_supplicant.conf.backup ]; then
    cp /etc/wpa_supplicant/wpa_supplicant.conf.backup /etc/wpa_supplicant/wpa_supplicant.conf
    echo "  ✓ wpa_supplicant.conf restored"
fi

echo ""
echo "[5/6] Removing iptables rules..."
# Flush NAT and FORWARD rules
iptables -t nat -F
iptables -F FORWARD
netfilter-persistent save
echo "  ✓ iptables rules removed"

echo ""
echo "[6/6] Restarting network services..."
systemctl restart dhcpcd
systemctl restart wpa_supplicant
echo "  ✓ Network services restarted"

echo ""
echo "=========================================="
echo "Single WiFi Mode Restored!"
echo "=========================================="
echo ""
echo "Current Mode:"
echo "  ✓ WiFi Client (wlan0) - Active"
echo "  ✗ WiFi AP (uap0) - Disabled"
echo ""
echo "Next Steps:"
echo "  1. Reboot: sudo reboot"
echo "  2. After reboot, only WiFi client will be active"
echo "  3. Check connection: nmcli device status"
echo ""
echo "To re-enable dual WiFi mode:"
echo "  sudo bash setup.sh wifi"
echo "=========================================="
