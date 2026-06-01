#!/bin/bash
# Quick resource check for Jetson Orin Nano / Docker
# Run with: ! ~/.claude/scripts/check-resources.sh

echo "=== System Resources ==="

# Memory
echo ""
echo "Memory:"
free -h | grep -E "^Mem|^Swap" | awk '{printf "  %-6s Total: %-8s Used: %-8s Free: %s\n", $1, $2, $3, $4}'

# Disk
echo ""
echo "Disk:"
df -h / | tail -1 | awk '{printf "  Root: %s used of %s (%s)\n", $3, $2, $5}'

# Jetson-specific
if [[ -f /etc/nv_tegra_release ]]; then
    echo ""
    echo "Jetson GPU:"
    if command -v tegrastats &>/dev/null; then
        # Single sample
        timeout 1 tegrastats --interval 500 2>/dev/null | head -1 | \
            sed 's/.*RAM \([^ ]*\).*/  RAM: \1/' || echo "  Run 'tegrastats' for live stats"
    fi

    # Check if models could fit
    AVAIL_MB=$(free -m | awk '/^Mem:/{print $7}')
    echo "  Available: ${AVAIL_MB}MB"
    if [[ $AVAIL_MB -lt 2000 ]]; then
        echo "  Warning: Low memory for TinyLlama (~2GB needed)"
    fi
fi

# Docker stats
if command -v docker &>/dev/null && [[ ! -f /.dockerenv ]]; then
    CONTAINERS=$(docker ps -q 2>/dev/null | wc -l)
    if [[ $CONTAINERS -gt 0 ]]; then
        echo ""
        echo "Docker Containers: $CONTAINERS running"
        docker stats --no-stream --format "  {{.Name}}: {{.MemUsage}} ({{.MemPerc}})" 2>/dev/null | head -5
    fi
fi

# Process memory (top consumers)
echo ""
echo "Top Memory Users:"
ps aux --sort=-%mem | head -6 | tail -5 | awk '{printf "  %-20s %s%%\n", $11, $4}'
