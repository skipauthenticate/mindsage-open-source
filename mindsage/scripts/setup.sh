#!/bin/bash

# MindSage Setup Script
# This script helps you get started with MindSage

set -e

echo "=================================="
echo "  MindSage Setup"
echo "=================================="
echo ""

# Check Node.js version
echo "Checking Node.js version..."
NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js 18+ required. You have: $(node -v)"
    echo "Please upgrade Node.js: https://nodejs.org/"
    exit 1
fi
echo "✅ Node.js $(node -v)"
echo ""

# Install dependencies
echo "Installing dependencies..."
if command -v bun &> /dev/null; then
    echo "Using bun..."
    bun install
else
    echo "Using npm..."
    npm install
fi
echo "✅ Dependencies installed"
echo ""

# Check for Chrome/Chromium (required for Browser Connector)
echo "Checking for Chrome/Chromium..."
CHROME_FOUND=false
for CHROME_PATH in /usr/bin/chromium-browser /usr/bin/chromium /usr/bin/google-chrome /usr/bin/google-chrome-stable /snap/bin/chromium; do
    if [ -x "$CHROME_PATH" ]; then
        echo "✅ Found: $CHROME_PATH"
        CHROME_FOUND=true
        break
    fi
done

if [ "$CHROME_FOUND" = false ]; then
    echo "⚠️  Chrome/Chromium not found. Installing chromium-browser..."
    sudo apt install -y chromium-browser || sudo apt install -y chromium || echo "❌ Could not install Chromium. Please install manually."
fi
echo ""

# Create data directory
echo "Creating data directory..."
mkdir -p data/exports data/browser-connector/chromium-profile data/browser-connector/captures
echo "✅ Data directory created"
echo ""

# Optional: Install VNC dependencies for remote browser access
echo "Would you like to install VNC dependencies for remote browser access? (y/n)"
echo "(Required for headless deployments like Jetson Orin Nano)"
read -r INSTALL_VNC

if [ "$INSTALL_VNC" = "y" ] || [ "$INSTALL_VNC" = "Y" ]; then
    echo "Installing VNC dependencies..."
    sudo apt install -y xvfb x11vnc novnc websockify
    echo "✅ VNC dependencies installed"
    echo ""
    echo "VNC mode allows you to access the browser remotely via:"
    echo "  http://<device-ip>:6080/vnc.html"
    echo ""
else
    echo "Skipping VNC installation (can be installed later with: sudo apt install xvfb x11vnc novnc websockify)"
fi
echo ""

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "✅ .env file created"
else
    echo "ℹ️  .env file already exists"
fi
echo ""

# Optional: Install Caddy for easy URL access
echo "Would you like to install Caddy for easy URL access? (y/n)"
read -r INSTALL_CADDY

if [ "$INSTALL_CADDY" = "y" ] || [ "$INSTALL_CADDY" = "Y" ]; then
    echo "Installing Caddy..."
    
    # Check if Caddy is already installed
    if command -v caddy &> /dev/null; then
        echo "ℹ️  Caddy already installed"
    else
        sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
        sudo apt update
        sudo apt install -y caddy
        echo "✅ Caddy installed"
    fi
    
    # Configure Caddy
    echo "Configuring Caddy..."
    sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
:80 {
    # Auto-detect dev (8080) or production (3000)
    reverse_proxy localhost:8080 localhost:3000 {
        lb_policy first
        fail_duration 2s
        unhealthy_status 502 503 504
    }
}
EOF
    
    sudo systemctl restart caddy
    sudo systemctl enable caddy
    echo "✅ Caddy configured and started"
    echo ""
    
    HOSTNAME=$(hostname)
    echo "Access MindSage from any device on your network:"
    echo "  http://${HOSTNAME}.local"
    echo "  or http://$(hostname -I | awk '{print $1}')"
    echo ""
else
    echo "Skipping Caddy installation"
fi
echo ""

echo "=================================="
echo "  Setup Complete! 🎉"
echo "=================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start development servers:"
echo "   npm run dev:all"
echo ""
echo "2. Open your browser:"
if [ "$INSTALL_CADDY" = "y" ] || [ "$INSTALL_CADDY" = "Y" ]; then
    HOSTNAME=$(hostname)
    echo "   http://${HOSTNAME}.local (via Caddy)"
    echo "   or http://localhost:8080 (direct)"
else
    echo "   http://localhost:8080"
fi
echo ""
echo "3. Add a ChatGPT connector:"
echo "   - Click 'Add Connector'"
echo "   - Select 'ChatGPT Export'"
echo "   - Enter your credentials"
echo "   - Click 'Sync' to export"
echo ""
echo "For more info, see README.md"
echo ""
