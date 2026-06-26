#!/bin/bash
# Setup Cloudflare Tunnel for Remote Access
# Allows secure access from anywhere without port forwarding

echo "=========================================="
echo "Cloudflare Tunnel Setup"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: This script must be run as root (use sudo)"
    echo "Usage: sudo bash setup_cloudflare_tunnel.sh"
    exit 1
fi

echo "Prerequisites:"
echo "  1. Cloudflare account (free)"
echo "  2. Domain name (can use free subdomain from Cloudflare)"
echo ""
echo "Benefits:"
echo "  ✓ No port forwarding needed"
echo "  ✓ No static IP needed"
echo "  ✓ HTTPS automatic (SSL/TLS)"
echo "  ✓ Secure (not exposed to internet)"
echo "  ✓ Free (Cloudflare Zero Trust)"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Setup cancelled."
    exit 1
fi

echo ""
echo "[1/5] Installing cloudflared..."

# Detect architecture
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ]; then
    # ARM64 (Raspberry Pi 4/5 64-bit)
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
elif [ "$ARCH" = "armv7l" ]; then
    # ARM32 (Raspberry Pi 3/4 32-bit)
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
else
    echo "Error: Unsupported architecture: $ARCH"
    exit 1
fi

# Download cloudflared
wget -O /usr/local/bin/cloudflared "$CLOUDFLARED_URL"
chmod +x /usr/local/bin/cloudflared

# Verify installation
if ! command -v cloudflared &> /dev/null; then
    echo "Error: cloudflared installation failed"
    exit 1
fi

echo "  ✓ cloudflared installed: $(cloudflared --version)"

echo ""
echo "[2/5] Authenticating with Cloudflare..."
echo ""
echo "A browser window will open for authentication."
echo "If you're using SSH, copy the URL and open it in your browser."
echo ""
read -p "Press Enter to continue..."

# Run as actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
sudo -u $ACTUAL_USER cloudflared tunnel login

if [ $? -ne 0 ]; then
    echo "Error: Authentication failed"
    exit 1
fi

echo "  ✓ Authentication successful"

echo ""
echo "[3/5] Creating tunnel..."
echo ""
read -p "Enter tunnel name (e.g., solar-panel-cleaner): " TUNNEL_NAME

if [ -z "$TUNNEL_NAME" ]; then
    TUNNEL_NAME="solar-panel-cleaner"
    echo "Using default: $TUNNEL_NAME"
fi

# Create tunnel
sudo -u $ACTUAL_USER cloudflared tunnel create $TUNNEL_NAME

if [ $? -ne 0 ]; then
    echo "Error: Tunnel creation failed"
    exit 1
fi

# Get tunnel ID
TUNNEL_ID=$(sudo -u $ACTUAL_USER cloudflared tunnel list | grep $TUNNEL_NAME | awk '{print $1}')

if [ -z "$TUNNEL_ID" ]; then
    echo "Error: Could not get tunnel ID"
    exit 1
fi

echo "  ✓ Tunnel created: $TUNNEL_NAME (ID: $TUNNEL_ID)"

echo ""
echo "[4/5] Configuring tunnel..."
echo ""
read -p "Enter your domain (e.g., solarpanel.example.com): " DOMAIN

if [ -z "$DOMAIN" ]; then
    echo "Error: Domain is required"
    exit 1
fi

# Create config directory
mkdir -p /home/$ACTUAL_USER/.cloudflared

# Create tunnel config
cat > /home/$ACTUAL_USER/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: /home/$ACTUAL_USER/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $DOMAIN
    service: http://localhost:5000
  - service: http_status:404
EOF

chown -R $ACTUAL_USER:$ACTUAL_USER /home/$ACTUAL_USER/.cloudflared

echo "  ✓ Tunnel configured"

echo ""
echo "[5/5] Setting up DNS and service..."

# Create DNS record
sudo -u $ACTUAL_USER cloudflared tunnel route dns $TUNNEL_NAME $DOMAIN

if [ $? -ne 0 ]; then
    echo "Warning: DNS setup failed. You may need to add DNS record manually."
fi

# Create systemd service
cat > /etc/systemd/system/cloudflared.service << EOF
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=$ACTUAL_USER
ExecStart=/usr/local/bin/cloudflared tunnel --config /home/$ACTUAL_USER/.cloudflared/config.yml run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
systemctl daemon-reload
systemctl enable cloudflared
systemctl start cloudflared

echo "  ✓ Service installed and started"

echo ""
echo "=========================================="
echo "Cloudflare Tunnel Setup Complete!"
echo "=========================================="
echo ""
echo "Tunnel Details:"
echo "  Name:   $TUNNEL_NAME"
echo "  ID:     $TUNNEL_ID"
echo "  Domain: $DOMAIN"
echo ""
echo "Access Your Application:"
echo "  URL: https://$DOMAIN"
echo ""
echo "Service Status:"
systemctl status cloudflared --no-pager -l | head -10
echo ""
echo "Useful Commands:"
echo "  Check status:  sudo systemctl status cloudflared"
echo "  View logs:     sudo journalctl -u cloudflared -f"
echo "  Restart:       sudo systemctl restart cloudflared"
echo "  Stop:          sudo systemctl stop cloudflared"
echo "  List tunnels:  cloudflared tunnel list"
echo ""
echo "To remove tunnel:"
echo "  sudo bash remove_cloudflare_tunnel.sh"
echo "=========================================="
