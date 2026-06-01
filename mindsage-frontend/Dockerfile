# MindSage Frontend Dockerfile
# Multi-stage build for React app with nginx serving
#
# Build:
#   docker build -t mindsage-frontend .

# Stage 1: Build
FROM node:22-bookworm AS builder

WORKDIR /app

# Copy package files
COPY package.json ./

# Install dependencies (using npm install to resolve correct arch-specific packages)
RUN npm install

# Copy source code
COPY . .

# Build args for API URL configuration
# Empty string = relative URLs = go through nginx proxy
ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL

# Build the React app
RUN npm run build

# Stage 2: Production with nginx
FROM nginx:alpine

# Install curl for healthcheck
RUN apk add --no-cache curl

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
