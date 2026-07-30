#!/bin/bash
# CampusInsight Agent — 一键部署脚本
set -euo pipefail

APP_NAME="campus-insight"
APP_PORT="${PORT:-8501}"

banner() {
    echo ""
    echo "  🏛️  校园先知 CampusInsight Agent"
    echo "  AI 校园治理平台 · 知报议督"
    echo ""
}

# ── 本地启动 ──
start_local() {
    banner
    if [ ! -f .env ]; then
        echo "[!] .env 不存在，从 .env.example 创建..."
        cp .env.example .env
        echo "[!] 请编辑 .env 填入 DEEPSEEK_API_KEY 后重新运行"
        exit 0
    fi
    echo "[✓] 安装依赖..."
    pip install -q -r requirements.txt
    echo "[✓] 启动 Streamlit（端口 $APP_PORT）..."
    echo "    访问: http://localhost:$APP_PORT"
    streamlit run app.py --server.port="$APP_PORT" --server.address=0.0.0.0
}

# ── Docker 部署 ──
start_server() {
    banner
    if ! grep -q "DEEPSEEK_API_KEY=" .env 2>/dev/null || grep -q 'DEEPSEEK_API_KEY=""' .env 2>/dev/null; then
        echo "[✗] 请先在 .env 中设置 DEEPSEEK_API_KEY"
        exit 1
    fi
    echo "[✓] 构建镜像..."
    docker build -t "$APP_NAME" .
    docker stop "$APP_NAME" 2>/dev/null || true
    docker rm "$APP_NAME" 2>/dev/null || true
    echo "[✓] 启动容器..."
    docker run -d --name "$APP_NAME" --restart unless-stopped \
        -p "$APP_PORT:8501" --env-file .env \
        -v "$(pwd)/data:/app/data" "$APP_NAME"
    echo "[✓] 部署完成！访问 http://localhost:$APP_PORT"
}

case "${1:-}" in
    --server) start_server ;;
    --stop)   docker stop "$APP_NAME" 2>/dev/null && echo "已停止" ;;
    --update) docker build -t "$APP_NAME" . && docker stop "$APP_NAME" 2>/dev/null; docker rm "$APP_NAME" 2>/dev/null; start_server ;;
    *)        start_local ;;
esac
