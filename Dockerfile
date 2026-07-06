# backlink-publisher — Multi-stage production build
# =========================================
# Usage:
#   docker build -t backlink-publisher .
#   docker run -p 8888:8888 -v ~/.config/backlink-publisher:/config backlink-publisher
#
# Dev build (with test tools):
#   docker build --target dev -t backlink-publisher:dev .
#
# CLI only (no WebUI/browser):
#   docker build --target cli -t backlink-publisher:cli .

# ── Base stage (shared Python + system deps) ─────────────────
FROM python:3.11-slim AS base

WORKDIR /app

# Playwright (Chromium) system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 libcups2 libxfixes3 \
    libxshmfence1 curl \
    && rm -rf /var/lib/apt/lists/*

# ── Frontend build stage (optimized layer cache) ──────────────
FROM node:22-slim AS frontend-builder
WORKDIR /build

# Step 1: Copy only dependency manifests first (cache npm ci)
COPY frontend/package.json frontend/package-lock.json* ./frontend/
COPY webui_app/static/css ./webui_app/static/css
RUN cd frontend && npm ci --prefer-offline || npm install

# Step 2: Copy source code (invalidates cache only when src changes)
COPY frontend ./frontend
RUN cd frontend && npm run build
# → /build/webui_app/spa_dist

# ── Production deps stage ─────────────────────────────
FROM base AS prod-deps

# Install core deps only (no [dev])
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# ── Dev deps stage (isolated, not in production) ─────────
FROM prod-deps AS dev-deps

RUN pip install --no-cache-dir -e ".[dev]"

# Dev target: includes test/analysis tools
FROM dev-deps AS dev
COPY . .
RUN python -m playwright install chromium 2>/dev/null || true
ENV BACKLINK_PUBLISHER_CONFIG_DIR=/config
ENV PORT=8888
ENV BIND_HOST=0.0.0.0
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8888/api/v1/health || exit 1
EXPOSE 8888
CMD ["python", "serve.py"]

# ── CLI lightweight stage (no WebUI/browser) ─────────────
FROM prod-deps AS cli
COPY src/ ./src/
COPY webui.py ./
ENV BACKLINK_PUBLISHER_CONFIG_DIR=/config
ENTRYPOINT ["python", "-m", "backlink_publisher.cli.bp"]

# ── Playwright browser cache stage ─────────────────────────────
FROM base AS playwright-cache
RUN python -m playwright install --with-deps chromium 2>/dev/null || true

# ── Production runtime stage ─────────────────────────────
FROM base AS runtime

# Create non-root user
RUN groupadd -r bpuser && useradd -r -g bpuser -d /app -s /sbin/nologin bpuser

# Copy installed packages (production deps only)
COPY --from=prod-deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=prod-deps /usr/local/bin /usr/local/bin

# Copy application code (only what's needed)
COPY src/ ./src/
COPY webui_app/ ./webui_app/
COPY webui_store/ ./webui_store/
COPY webui.py ./

# Copy SPA (Vue frontend)
COPY --from=frontend-builder /build/webui_app/spa_dist ./webui_app/spa_dist

# Copy Playwright browsers from cache stage (avoids reinstall)
COPY --from=playwright-cache /root/.cache/ms-playwright /root/.cache/ms-playwright

# Settings
ENV BACKLINK_PUBLISHER_CONFIG_DIR=/config
ENV PORT=8888
ENV BIND_HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8888/api/v1/health || exit 1

EXPOSE 8888

USER bpuser

CMD ["python", "serve.py"]
