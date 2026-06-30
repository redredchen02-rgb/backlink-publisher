# backlink-publisher — 多階段生產構建
# =========================================
# 用法:
#   docker build -t backlink-publisher .
#   docker run -p 8888:8888 -v ~/.config/backlink-publisher:/config backlink-publisher
#
# 開發構建 (含測試工具):
#   docker build --target dev -t backlink-publisher:dev .
#
# 僅 CLI (無 WebUI/瀏覽器):
#   docker build --target cli -t backlink-publisher:cli .

# ── 基礎階段 (共享 Python + 系統基礎) ─────────────────
FROM python:3.11-slim AS base

WORKDIR /app

# Playwright (Chromium) 系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 libcups2 libxfixes3 \
    libxshmfence1 curl \
    && rm -rf /var/lib/apt/lists/*

# ── 前端構建階段 ──────────────────────────────────
FROM node:22-slim AS frontend-builder
WORKDIR /build
COPY frontend ./frontend
COPY webui_app/static/css ./webui_app/static/css
RUN cd frontend && npm ci && npm run build
# → /build/webui_app/spa_dist

# ── 生產依賴安裝階段 ─────────────────────────────
FROM base AS prod-deps

# 只安裝核心依賴 (無 [dev])
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# ── 開發依賴安裝階段 (獨立的，不進生產) ─────────
FROM prod-deps AS dev-deps

RUN pip install --no-cache-dir -e ".[dev]"

# 開發用，含測試/分析工具
FROM dev-deps AS dev
COPY . .
RUN python -m playwright install chromium 2>/dev/null || true
ENV BACKLINK_PUBLISHER_CONFIG_DIR=/config
ENV PORT=8888
ENV BIND_HOST=0.0.0.0
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8888/ce:health || exit 1
EXPOSE 8888
CMD ["python", "webui.py"]

# ── CLI 輕量階段 (無 WebUI/瀏覽器) ─────────────
FROM prod-deps AS cli
COPY src/ ./src/
COPY webui.py ./
ENV BACKLINK_PUBLISHER_CONFIG_DIR=/config
ENTRYPOINT ["python", "-m", "backlink_publisher.cli.bp"]

# ── 生產運行時階段 ─────────────────────────────
FROM base AS runtime

# 創建非 root 用戶
RUN groupadd -r bpuser && useradd -r -g bpuser -d /app -s /sbin/nologin bpuser

# 複製已安裝的套件 (僅生產依賴)
COPY --from=prod-deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=prod-deps /usr/local/bin /usr/local/bin

# 複製應用程式碼 (僅運行所需的)
COPY src/ ./src/
COPY webui_app/ ./webui_app/
COPY webui_store/ ./webui_store/
COPY webui.py ./

# 複製 SPA (Vue 前端)
COPY --from=frontend-builder /build/webui_app/spa_dist ./webui_app/spa_dist

# 安裝 Playwright 瀏覽器 (僅 Chromium)
RUN python -m playwright install chromium 2>/dev/null || true

# 設定
ENV BACKLINK_PUBLISHER_CONFIG_DIR=/config
ENV PORT=8888
ENV BIND_HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8888/ce:health || exit 1

EXPOSE 8888

USER bpuser

CMD ["python", "webui.py"]
