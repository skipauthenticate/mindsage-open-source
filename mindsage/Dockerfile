# MindSage Backend Dockerfile for Jetson Orin Nano (ARM64)
# Multi-stage build for smaller final image

# Stage 1: Build
FROM node:20-bookworm AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install all dependencies (including dev)
RUN npm install

# Copy source code
COPY . .

# Build server (TypeScript to JavaScript)
RUN npm run build

# Stage 2: Production
FROM node:20-bookworm-slim

# Install runtime dependencies
# - avahi-utils: for avahi-publish (mDNS advertisement)
# - dbus: required by avahi
# - curl: for healthcheck
# - chromium: browser for Browser Connector
# - VNC stack: xvfb, x11vnc, websockify for remote browser access
RUN apt-get update && apt-get install -y --no-install-recommends \
    avahi-utils \
    dbus \
    curl \
    chromium \
    xvfb \
    x11vnc \
    websockify \
    novnc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files and install production dependencies only
COPY package*.json ./
RUN npm install --omit=dev

# Copy built server from builder
COPY --from=builder /app/dist-server ./dist-server

# Copy server scripts (for export functionality)
COPY --from=builder /app/server/scripts ./dist-server/scripts

# Copy browser connector extension (required for capture functionality)
COPY --from=builder /app/server/browser-connector/extension ./server/browser-connector/extension

# Create data directories
RUN mkdir -p /app/data/connectors /app/data/exports /app/data/uploads /app/data/imports \
    /app/data/browser-connector/chromium-profile /app/data/browser-connector/captures

# Set environment
ENV NODE_ENV=production
ENV PORT=3003

# Expose ports
# 3003 - Main Express API
# 53317 - LocalSend HTTP API (standard port)
# 6080 - noVNC web interface for remote browser access
EXPOSE 3003 53317 6080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:3003/api/stats || exit 1

# Start the server
CMD ["node", "dist-server/index.js"]
