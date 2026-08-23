# HTTPS 部署方案（P1-G1-02 修复④：生产无 HTTPS）

> 社区先知 CommunityInsight — FastAPI Web 服务（`api_web.py`，端口 8000）HTTPS 落地说明。
> 覆盖三档场景：**本地演示**（ngrok 临时公网 HTTPS）、**单机生产**（Nginx + Let's Encrypt 证书自动续期）、**容器部署**（compose 挂证书 + Nginx 反代）。
> 对应《四个 P1 修复方案 v5.0》修复④；评审报告 P1-G1-02「无 HTTPS」。

## 0. 为什么必须 HTTPS

- 登录/改密携带口令与 JWT：明文 HTTP 下可被中间人截获（本服务 JWT 为 HMAC 签名，但 token 本身会泄露，可重放）。
- PIPL / 数据安全合规：敏感数据传输须加密（评审 G 项扣分点）。
- 小程序/微信 H5、浏览器混合内容策略（Mixed Content）会拦截 `http://` 接口请求——演示若用真机访问 8000 端口，多数浏览器默认阻止。

## 1. 快速演示：ngrok（零配置公网 HTTPS，答辩演示用）

```bash
# 1) 启动本地服务（已跑则跳过）
uvicorn api_web:app --host 0.0.0.0 --port 8000

# 2) 另开终端暴露公网 HTTPS 隧道
ngrok http 8000

# 3) 把 ngrok 给出的 https://xxxx.ngrok-free.app 发给评委 / 手机访问即可
```

- 注意：ngrok 免费版域名每次重启变化；答辩前一天固定一个域名演示更稳妥。
- Vue3 前端调用 `/api/web/*` 是**同源相对路径**，隧道后无需改前端代码。

## 2. 单机生产：Nginx 反代 + Let's Encrypt（certbot 自动续期）

### 2.1 前提
- 一台有公网 IP 的服务器，域名已解析到该 IP（如 `insight.example.com`）。
- 放行 80/443 端口。

### 2.2 安装与签发证书

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
```

首次签发（certbot 自动改 nginx 配置并启用 HTTPS）：

```bash
sudo certbot --nginx -d insight.example.com
```

续期（Let's Encrypt 证书 90 天，建议 cron 每月两次）：

```bash
echo "0 3 1,15 * * root certbot renew --quiet --deploy-hook 'systemctl reload nginx'" | sudo tee /etc/cron.d/certbot-renew
```

### 2.3 Nginx 站点配置（/etc/nginx/sites-available/community-insight）

```nginx
# HTTP → HTTPS 强制跳转（certbot 会自动生成，这里给出完整形态）
server {
    listen 80;
    server_name insight.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name insight.example.com;

    # certbot 管理的证书路径（续期自动更新，勿手改）
    ssl_certificate     /etc/letsencrypt/live/insight.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/insight.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # 上传文件体积上限（附件 ≤5MB，给一点余量）
    client_max_body_size 6m;

    location / {
        # 反代到 FastAPI（同机 8000）
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }

    # /uploads 静态附件（可省：由 FastAPI 托管时不需要）
    # location /uploads/ { alias /path/to/campus-insight-agent/uploads/; }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/community-insight /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 2.4 启动后端

```bash
# 方式 A：直接跑
nohup uvicorn api_web:app --host 127.0.0.1 --port 8000 >> /var/log/ci-web.log 2>&1 &

# 方式 B：systemd（推荐）
# [Unit] Description=CommunityInsight Web
# [Service] WorkingDirectory=/opt/campus-insight-agent
#           ExecStart=/opt/campus-insight-agent/.venv/bin/uvicorn api_web:app --host 127.0.0.1 --port 8000
#           Restart=always
# [Install] WantedBy=multi-user.target
```

验证：浏览器访问 `https://insight.example.com`（应显示 Vue3 界面），`https://insight.example.com/api/web/health` 返回 `{"success": true, ...}`。

## 3. 容器部署：docker-compose（web 服务 + Nginx 反代）

见仓库根目录 `docker-compose.yml` 中 `web` + `web-nginx` 两个服务：

```yaml
# 目录结构
# ./nginx/community-insight.conf   Nginx 配置（同 2.3，proxy_pass 指向 web:8000 容器名）
# ./nginx/certs/                   Let's Encrypt 证书挂载目录
web-nginx:
  image: nginx:1.27-alpine
  container_name: community-insight-nginx
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./nginx/community-insight.conf:/etc/nginx/conf.d/default.conf:ro
    - ./nginx/certs:/etc/letsencrypt/live/insight.example.com:ro
  depends_on:
    - web
  restart: unless-stopped
```

证书签发方式与 2.2 相同，签发后将 `/etc/letsencrypt/` 内容拷入 `./nginx/certs/` 即可（或容器内用 certbot 自行续期，进阶用法不再展开）。

## 4. 说明与取舍

- **本仓库不内置证书**：证书属于部署环境机密，不入库（已加入 `.gitignore` 建议：`nginx/certs/`）。
- **演示环境**：本机 `http://127.0.0.1:8000` 照常可用（本地回环无中间人风险）；对外演示用 §1 ngrok。
- **FastAPI 自身**：不直接启用 uvicorn 的 SSL（`--ssl-keyfile`），统一由 Nginx 终结 TLS——证书续期、性能、HTTP/2 都由 Nginx 负责，后端保持纯 HTTP 反代，最简单可靠。
- **HSTS（可选增强）**：确认全站 HTTPS 稳定后可在 Nginx 加 `add_header Strict-Transport-Security "max-age=31536000" always;`。

## 5. 验收清单

- [ ] `curl -sI https://<域名>/api/web/health` 返回 200 且证书有效
- [ ] 明文 `http://<域名>/` 301 跳转 HTTPS
- [ ] 手机浏览器（非 localhost）可正常访问并登录（混合内容无告警）
- [ ] `sudo certbot renew --dry-run` 通过（续期链路可用）
