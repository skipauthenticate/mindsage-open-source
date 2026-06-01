#!/bin/bash
# Session start hook - provides context without loading full docs
# Saves tokens by giving Claude hints about current state

echo "=== MindSage Development Context ==="

# Detect environment
if [[ -f /.dockerenv ]]; then
    echo "Environment: Docker container"
elif [[ -f /etc/nv_tegra_release ]]; then
    echo "Environment: Jetson ($(cat /etc/nv_tegra_release | head -1 | cut -d',' -f1))"
    # Show GPU memory on Jetson
    if command -v tegrastats &>/dev/null; then
        echo "GPU Memory: $(tegrastats --interval 100 | head -1 | grep -oP 'GR3D_FREQ \d+%' || echo 'check tegrastats')"
    fi
else
    echo "Environment: $(uname -s) $(uname -m)"
fi

# Git info
if git rev-parse --is-inside-work-tree &>/dev/null; then
    echo ""
    echo "Branch: $(git branch --show-current)"
    echo "Last commit: $(git log -1 --oneline 2>/dev/null || echo 'none')"
    if [[ -n $(git status --porcelain 2>/dev/null) ]]; then
        echo "Status: uncommitted changes"
    fi
fi

# Check running services (quick checks only)
echo ""
echo "=== Services ==="

# Backend
if curl -s --connect-timeout 1 http://localhost:3003/api/stats &>/dev/null; then
    echo "Backend (3003): running"
else
    echo "Backend (3003): not running"
fi

# Frontend
if curl -s --connect-timeout 1 http://localhost:8080 &>/dev/null; then
    echo "Frontend (8080): running"
else
    echo "Frontend (8080): not running"
fi

# Vector Store
if curl -s --connect-timeout 1 http://localhost:8085/health &>/dev/null; then
    VS_STATUS=$(curl -s http://localhost:8085/health 2>/dev/null | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    echo "Vector Store (8085): ${VS_STATUS:-running}"
else
    echo "Vector Store (8085): not running"
fi

# Docker-specific checks
if command -v docker &>/dev/null && [[ ! -f /.dockerenv ]]; then
    RUNNING=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E 'mindsage|vector' | tr '\n' ', ' | sed 's/,$//')
    if [[ -n "$RUNNING" ]]; then
        echo "Docker: $RUNNING"
    fi
fi

echo ""
