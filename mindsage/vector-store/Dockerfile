# MindSage Vector Store Dockerfile
# Supports both Mac (development) and Jetson Orin Nano (production)
#
# Build for Mac/Linux (CPU-only, default):
#   docker build -t mindsage-vector-store .
#
# Build for Jetson (GPU):
#   docker build -f Dockerfile.jetson -t mindsage-vector-store .

FROM python:3.11-slim-bookworm

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    curl \
    git \
    # Image PII: Tesseract OCR (fallback for CPU-only)
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    # Audio PII: FFmpeg for pydub audio manipulation
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt ./

# Build settings for llama-cpp-python on different architectures
# Disable native CPU optimizations for cross-platform compatibility
ENV CMAKE_ARGS="-DGGML_BLAS=OFF -DGGML_METAL=OFF -DGGML_NATIVE=OFF"
ENV CFLAGS="-O2"
ENV CXXFLAGS="-O2"

# Install CPU-only PyTorch first, then other dependencies
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip3 install --no-cache-dir -r requirements.txt

# Download spaCy model for PII protection
RUN python3 -m spacy download en_core_web_sm

# Copy application code
COPY . .

# Download models during build (optional, can be mounted instead)
ARG DOWNLOAD_MODELS=false
RUN if [ "$DOWNLOAD_MODELS" = "true" ]; then \
    python3 download_models.py; \
    fi

# Create data directories
RUN mkdir -p /app/data/vectordb /app/models

# Default port
ENV PORT=8085

# Expose port
EXPOSE 8085

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8085/health || exit 1

# Start the server
CMD ["python3", "-m", "mcp_vector_store.mcp_server_http", "--port", "8085", "--db-path", "/app/data/vectordb"]
