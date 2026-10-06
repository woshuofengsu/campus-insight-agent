# 应用镜像：FastAPI + 已构建的 Vue 产物 + 备份/演练脚本
#
# 两条设计取舍：
#   ① **两阶段构建**：前端在镜像内构建（保证"镜像里的 dist 一定对应当前源码"，
#      不依赖"记得在本地 npm run build"——那个坑本项目踩过多次）；
#   ② **非 root 运行** + 数据目录挂卷：容器被攻破也不至于直接拿宿主权限。
#
# 本机没有 Docker，这份 Dockerfile **尚未真实构建过**；首次上服务器按部署手册执行。

# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS webbuild
WORKDIR /web
# 先只拷依赖清单，利用层缓存（改代码不必重装依赖）
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 阶段 2：运行 --------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# postgresql-client：DB_BACKEND=postgres 时 backup_db.py 需要 pg_dump；
#   curl：容器内自检用（健康检查用的是 python，不依赖它，但排障方便）
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client curl tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# 应用代码 + **镜像内构建好的前端产物**
COPY . .
COPY --from=webbuild /web/dist ./web/dist

# 数据/附件/备份三个目录：挂卷覆盖，但先建好并给非 root 用户权限
RUN useradd -m -u 10001 appuser \
 && mkdir -p /data /app/uploads /app/backups \
 && chown -R appuser:appuser /data /app/uploads /app/backups /app
USER appuser

EXPOSE 8000

# 生产姿态：DEMO_MODE=false（由 compose 注入），缺少密钥会**拒绝启动**（fail-closed，有意为之）
CMD ["python", "-m", "uvicorn", "api_web:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
