#!/bin/bash
# MindSage Docker Start Script
# Automatically detects platform and uses appropriate configuration
#
# Usage:
#   ./docker-start.sh          # Start services
#   ./docker-start.sh build    # Build and start
#   ./docker-start.sh down     # Stop services
#   ./docker-start.sh logs     # View logs

set -e

# Detect if running on Jetson (check for NVIDIA Tegra)
is_jetson() {
    if [ -f /etc/nv_tegra_release ]; then
        return 0
    fi
    if [ -d /sys/devices/soc0 ] && grep -q "NVIDIA" /sys/devices/soc0/family 2>/dev/null; then
        return 0
    fi
    return 1
}

# Detect if NVIDIA GPU is available (for non-Jetson Linux with GPU)
has_nvidia_gpu() {
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi &> /dev/null && return 0
    fi
    return 1
}

# Determine which compose files to use
get_compose_files() {
    if is_jetson; then
        echo "-f docker-compose.yml -f docker-compose.jetson.yml"
    else
        echo "-f docker-compose.yml"
    fi
}

# Get compose command (docker-compose vs docker compose)
get_compose_cmd() {
    if command -v docker-compose &> /dev/null; then
        echo "docker-compose"
    else
        echo "docker compose"
    fi
}

COMPOSE_CMD=$(get_compose_cmd)
COMPOSE_FILES=$(get_compose_files)
ACTION="${1:-up}"

# Print detected configuration
echo "=========================================="
echo "MindSage Docker Launcher"
echo "=========================================="
if is_jetson; then
    echo "Platform: Jetson (GPU enabled)"
    echo "Config:   docker-compose.yml + docker-compose.jetson.yml"
else
    echo "Platform: Mac/Linux (CPU only)"
    echo "Config:   docker-compose.yml"
fi
echo "Command:  $COMPOSE_CMD $COMPOSE_FILES"
echo "=========================================="
echo ""

case "$ACTION" in
    up)
        echo "Starting services..."
        $COMPOSE_CMD $COMPOSE_FILES up -d
        echo ""
        echo "Services started. View logs with: ./docker-start.sh logs"
        ;;
    build)
        echo "Building and starting services..."
        $COMPOSE_CMD $COMPOSE_FILES up --build -d
        echo ""
        echo "Services started. View logs with: ./docker-start.sh logs"
        ;;
    down)
        echo "Stopping services..."
        $COMPOSE_CMD $COMPOSE_FILES down
        ;;
    logs)
        $COMPOSE_CMD $COMPOSE_FILES logs -f
        ;;
    ps)
        $COMPOSE_CMD $COMPOSE_FILES ps
        ;;
    restart)
        echo "Restarting services..."
        $COMPOSE_CMD $COMPOSE_FILES restart
        ;;
    *)
        # Pass through any other docker-compose commands
        $COMPOSE_CMD $COMPOSE_FILES "$@"
        ;;
esac
