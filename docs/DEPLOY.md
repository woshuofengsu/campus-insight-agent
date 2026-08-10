# CampusInsight Agent 部署指南

让评委/同学在手机和电脑上访问你的校园治理智能平台。

---

## 方案一：Docker 部署（推荐）

### 前置条件
- 一台云服务器（阿里云/腾讯云学生机 ~10元/月，或任何有公网 IP 的机器）
- 服务器安装 Docker 和 Docker Compose

### 步骤

**1. 上传项目到服务器**
```bash
# 在本地打包（排除不必要文件）
tar --exclude='.git' --exclude='__pycache__' --exclude='*.db' \
    -czf campus-insight.tar.gz campus-insight-agent/

# 上传到服务器
scp campus-insight.tar.gz root@你的服务器IP:/opt/
```

**2. 服务器上解压并配置**
```bash
ssh root@你的服务器IP
cd /opt && tar -xzf campus-insight.tar.gz && cd campus-insight-agent

# 配置 API Key
cp .env.example .env
nano .env  # 填入 DEEPSEEK_API_KEY
```

**3. 启动**
```bash
docker-compose up -d
# 访问 http://你的服务器IP:8501
```

**4. （可选）配置域名 + HTTPS**
```bash
# 用 Nginx 反向代理 + Let's Encrypt 免费证书
apt install nginx certbot python3-certbot-nginx
# 配置参考下方的 Nginx 配置
```

---

## 方案二：Streamlit Community Cloud（免费）

### 步骤

**1. 推送代码到 GitHub 公开仓库**
```bash
cd campus-insight-agent
git init && git add . && git commit -m "Initial"
gh repo create campus-insight-agent --public --push
```

**2. 在 [share.streamlit.io](https://share.streamlit.io) 用 GitHub 登录**

**3. 点击 "New app" → 选择仓库 → 主文件 `app.py`**

**4. 在 Advanced Settings 中添加 Secrets：**
```
DEEPSEEK_API_KEY = "sk-xxx"
CAMPUS_CITY = "北京"
```

**5. Deploy！获得 `https://你的用户名.streamlit.app` 链接**

> ⚠️ Streamlit Cloud 免费版：公共可见，休眠后首次访问需 ~30s 唤醒

---

## 方案三：HuggingFace Spaces（⭐ 免费备选）

### 步骤

**1. 在 [huggingface.co/spaces](https://huggingface.co/spaces) 创建 Space**
- SDK: Streamlit
- 选择 Public 或 Private

**2. 在 Settings → Secrets 添加：**
```
DEEPSEEK_API_KEY=sk-xxx
```

**3. 克隆 Space 仓库，推送代码**

**4. 自动部署！获得 `https://huggingface.co/spaces/你的用户名/space名`**

---

## 方案四：手机热点 + 内网穿透（演示用）

适合比赛现场演示，不需要服务器。

### Ngrok（免费 1 条隧道）
```bash
# 下载 ngrok → 注册免费账号 → 获取 authtoken
ngrok config add-authtoken 你的token

# 本地先启动
streamlit run app.py

# 另开终端，暴露到公网
ngrok http 8501

# 获得 https://xxxx.ngrok-free.app 链接，评委手机扫码即可访问
```

---

## Nginx 反向代理配置（可选，生产环境）

```nginx
server {
    listen 80;
    server_name campus.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;  # WebSocket 长连接
    }

    location /_stcore/stream {
        proxy_pass http://127.0.0.1:8501/_stcore/stream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

---

## 手机端访问优化

### 已内置的移动端适配
- ✅ 响应式布局（自动适配手机/平板/电脑）
- ✅ 触控友好的按钮尺寸（44px+）
- ✅ 移动端列堆叠（横向列自动变纵向）
- ✅ 全宽聊天气泡
- ✅ 侧边栏小屏折叠

### 添加到手机主屏幕（PWA 体验）
在手机浏览器打开后 → 分享 → 添加到主屏幕 → 像原生 App 一样使用。

### URL 参数
| 参数 | 说明 |
|------|------|
| `?theme=dark` | 强制暗色模式 |
| `?offline=1` | 离线演示模式（不调用 API） |
| `?demo=1` | 治理大屏演示模式（模拟数据） |
| `?refresh=30` | 治理大屏自动刷新间隔（秒） |

---

## 环境变量参考

见 `.env.example`：

```bash
# 必填
DEEPSEEK_API_KEY=sk-your-key-here

# 可选
CAMPUS_CITY=北京
CAMPUS_DISTRICT=海淀区
CAMPUS_API_KEY=your-api-auth-key    # FastAPI 鉴权
HEFENG_API_KEY=your-hefeng-key      # 和风天气（不填则用模拟数据）
OFFLINE_MODE=false                  # 离线模式
```
