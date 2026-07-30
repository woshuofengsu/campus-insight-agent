# 扣子 AI 集成指南

让扣子 Bot 能读取你的 CampusInsight Agent 网站，本质是：**你的 API 部署到公网 → 扣子插件导入 OpenAPI → Bot 调用。**

---

## 架构

```
用户 (微信/飞书/扣子APP)
    ↓ 发消息
扣子 Bot
    ↓ 调用插件 API
https://xxx.ngrok-free.app/api/chat   (或你的服务器)
    ↓ OODA Agent
DeepSeek / 离线规则引擎
    ↓ 返回回复
扣子 Bot → 返回给用户
```

---

## 第一步：安装依赖

```bash
pip install fastapi uvicorn
```

## 第二步：启动 API 服务

```bash
# 在项目根目录
cd c:\Users\wo'shuo'feng'su\Desktop\campus-insight-agent
python api.py --port 18800
```

确认本地可访问：http://localhost:18800/docs

## 第三步：暴露到公网

扣子必须能访问公网 URL。3 种方式：

### 方式 A：ngrok（最快，适合开发/比赛演示）

```bash
# 1. 下载 ngrok: https://ngrok.com/download
# 2. 注册免费账号，获取 authtoken
# 3. 启动隧道
ngrok http 18800

# 你会看到：
# Forwarding  https://xxxx-xxx.ngrok-free.app -> http://localhost:18800
```

复制那个 `https://xxxx-xxx.ngrok-free.app` URL，这就是扣子要用的。

### 方式 B：Cloudflare Tunnel（免费，稳定）

```bash
# 安装 cloudflared
winget install cloudflare.cloudflared

# 启动
cloudflared tunnel --url http://localhost:18800
```

### 方式 C：部署到云服务器

```bash
# 上传项目到服务器后
pip install -r requirements.txt
nohup python api.py --port 18800 &
# 配 Nginx 反向代理 + SSL
```

---

## 第四步：在扣子中创建插件

### 4.1 获取 OpenAPI Schema

确保 API 启动后，浏览器访问：
```
http://localhost:18800/openapi.json
```
或者公网：
```
https://你的域名/openapi.json
```

### 4.2 扣子操作步骤

1. 打开 [扣子官网](https://www.coze.cn) → 进入你的 Bot 编辑页
2. 左侧菜单 → **插件** → **新建插件**
3. 选择 **导入 OpenAPI** → 粘贴 `/openapi.json` 的 URL（公网可访问的那个）
4. 扣子会自动识别所有端点：
   - `POST /api/chat` — AI 对话（核心）
   - `GET /api/campus-pulse` — 校园脉搏
   - `GET /api/weather` — 天气
   - `GET/POST /api/issues` — 工单查询/上报
   - `GET/POST /api/proposals` — 提案
   - `GET /api/topics` — 议题
   - `GET /api/governance/health` — 治理健康度
5. 配置鉴权方式（选 **API Key** 或 **无鉴权**）
6. 保存插件

### 4.3 在 Bot 工作流中使用

**方式一：直接作为工具绑定**

扣子 Bot 的「人设与回复逻辑」中配置提示词，把插件工具加进去。例如：

```
你是「校园先知」，一个校园治理 AI 助手。

当学生问你工单/报修/提案/天气/校园脉搏等问题时，
必须调用 CampusInsight 插件获取真实数据，不得编造。

可用的插件工具：
- get_weather: 查天气
- list_issues: 查工单列表
- report_issue: 上报问题
- list_proposals: 查提案
- create_proposal: 创建提案
- get_campus_pulse: 校园脉搏
- agent_chat: AI 综合对话（兜底）
```

**方式二：用工作流编排**

扣子工作流中，添加 **插件节点** → 选择 CampusInsight → 配置输入参数 → 连接输出到回复。

推荐工作流：

```
开始
  ↓
意图识别节点（判断用户想做什么）
  ├─ "天气" → get_weather 插件 → 格式化回复
  ├─ "报修" → report_issue 插件 → 回复工单号
  ├─ "提案" → list_proposals 插件 → 展示列表
  └─ "其他" → agent_chat 插件 → AI 综合回复
```

---

## 第五步：测试

### 5.1 本地 curl 测试

```bash
# 测试健康检查
curl http://localhost:18800/api/health

# 测试天气
curl http://localhost:18800/api/weather

# 测试 AI 对话
curl -X POST http://localhost:18800/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "最近校园有什么新鲜事？"}'

# 测试离线 AI
curl -X POST http://localhost:18800/api/chat/offline \
  -H "Content-Type: application/json" \
  -d '{"message": "教三楼灯坏了"}'

# 测试工单上报
curl -X POST http://localhost:18800/api/issues \
  -H "Content-Type: application/json" \
  -d '{"title":"图书馆三楼空调漏水","location":"图书馆三楼","description":"持续滴水"}'
```

### 5.2 扣子 Bot 测试

在扣子中点击「发布」→ 在测试窗口对话：

- "今天天气怎么样？" → 应返回真实天气
- "教三楼灯坏了怎么办？" → 应自动上报工单
- "看看校园最近有什么提案" → 应返回提案列表
- "校园脉搏" → 应返回综合快照

---

## 架构要点

| 组件 | 说明 |
|------|------|
| `api.py` | FastAPI 后端，所有 REST 端点 |
| `/api/chat` | DeepSeek 驱动的 OODA 对话 |
| `/api/chat/offline` | 规则引擎对话（不依赖 DeepSeek） |
| `/openapi.json` | OpenAPI 3.0 Schema，扣子插件注册用 |
| `/docs` | Swagger UI，开发调试用 |

## 常见问题

**Q: 扣子报 "插件调用失败"？**
A: 检查公网 URL 是否可达（用浏览器打开 /api/health 验证），检查扣子插件配置中的 URL 是否正确。

**Q: AI 对话返回很慢？**
A: DeepSeek API 首包延迟 ~2-5 秒。扣子工作流有 30s 超时，足够。如想更快，用 `/api/chat/offline`。

**Q: 没有 DeepSeek API Key？**
A: 用离线模式 `/api/chat/offline`，纯规则引擎，<100ms 响应。离线模式覆盖 7 种场景：天气、报修、查询、提案、校园脉搏、治理数据、闲聊。

**Q: 数据库在哪里？**
A: API 和 Streamlit 共用同一个 `data/campus_insight.db`。种子数据自动生成。

**Q: 扣子能读取 Streamlit 网页吗？**
A: 扣子的「网页浏览」插件只能读静态 HTML。对 Streamlit 这种需要 JS 渲染的动态页面无效。REST API 是正确方式。
