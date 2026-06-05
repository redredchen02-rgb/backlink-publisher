# backlink-publisher — multi-stage Docker build
# ======================================================
# Prerequisites: none (build pulls python:3.11-slim)
# Usage:
#   docker build -t backlink-publisher .
#   docker run -p 8888:8888 -v ~/.config/backlink-publisher:/config backlink-publisher

# ── Builder stage ──────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

# ── Runtime stage ──────────────────────────────────────
FROM python:3.11-slim

# Create non-root user
RUN groupadd -r bpuser && useradd -r -g bpuser -d /app -s /sbin/nologin bpuser

WORKDIR /app

# System deps for Playwright (Chromium browser)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libcups2 \
    libxfixes3 \
    libxshmfence1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed package from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Install playwright browsers (Chromium only)
RUN python -m playwright install chromium 2>/dev/null || true

# Configuration directory
ENV BACKLINK_PUBLISHER_CONFIG_DIR=/config
ENV PORT=8888
ENV BIND_HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8888/ce:health || exit 1

EXPOSE 8888

USER bpuser

CMD ["python", "webui.py"]
