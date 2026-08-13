# CommunityInsight Agent — Docker 部署镜像
# 社区先知 · AI 社区治理平台
#
# 构建: docker build -t community-insight .
# 运行: docker run -p 8501:8501 --env-file .env community-insight
# 或使用 docker-compose up

FROM python:3.11-slim

LABEL org.opencontainers.image.title="CommunityInsight Agent"
LABEL org.opencontainers.image.description="AI-powered community governance platform"
LABEL org.opencontainers.image.authors="CommunityInsight Team"

# ── System dependencies ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── App directory ──
WORKDIR /app

# ── Python dependencies (layer-cached) ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──
COPY . .

# ── Create data directory for SQLite ──
RUN mkdir -p /app/data

# ── Streamlit config for deployment ──
RUN mkdir -p /app/.streamlit && \
    echo '[server]\nheadless = true\nport = 8501\nenableCORS = false\nenableXsrfProtection = false\naddress = "0.0.0.0"\n\n[browser]\ngatherUsageStats = false\nserverAddress = "0.0.0.0"' > /app/.streamlit/config.toml

# ── Expose Streamlit port ──
EXPOSE 8501

# ── Health check ──
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# ── Entrypoint ──
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
