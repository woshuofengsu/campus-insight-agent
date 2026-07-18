# 校园先知 CampusInsight Agent — 设计文档

> **比赛**："AI赋能·智创未来"首都大学生智能体OPC创新大赛
> **截止日期**：2026年8月15日
> **项目代号**：campus-insight-agent
> **状态**：待实现

---

## 1. 产品概述

### 1.1 一句话描述

"校园先知"是一个基于 OODA 认知循环的大学生 AI 校园管家——不是被动问答的聊天机器人，而是一个能主动感知环境变化、自主规划多步骤任务、持续记忆用户偏好的智能体。

### 1.2 核心价值

| 痛点 | 解决方案 |
|------|----------|
| 忘记上课/考试时间 | 自动倒计时 + 主动提醒 |
| 食堂排队半小时 | 实时拥挤度预测 + 错峰建议 |
| 图书馆去了没座 | 座位状态查询 + 替代推荐 |
| 恶劣天气不知道，出门遭殃 | 天气感知 + 出行建议自动推送 |
| 课表与社团活动冲突 | 冲突检测 + 自动提醒 |
| 复习没计划、执行靠自觉 | 一句话生成周计划 + 日程提醒 |

### 1.3 目标用户

在校大学生（以大三学生为核心种子用户）

---

## 2. 架构设计

### 2.1 设计哲学：OODA 认知循环

不按传统"前端/后端/数据库"分层，而是按智能体的认知循环设计：

```
Observe（感知） → Orient（理解） → Decide（决策） → Act（执行）
                                      ↑                    │
                                      └── 反思（内嵌）←─────┘
```

每一层都有明确职责和清晰边界，这是本项目区别于普通 Chatbot 的核心差异点。

### 2.2 完整架构图

```
┌─────────────────────────────────────────────────────────────┐
│                 校园先知 · CampusInsight Agent               │
│                                                               │
│  ┌─────────────────────────┐  ┌────────────────────────────┐ │
│  │     💬 对话面板          │  │      📊 智能仪表盘          │ │
│  │                         │  │                            │ │
│  │  · 多轮自然语言对话      │  │  · 今日课表时间线           │ │
│  │  · Agent 思考步骤可见    │  │  · 考试倒计时卡片           │ │
│  │    （"正在查询课表…→     │  │  · 食堂拥挤度实时曲线       │ │
│  │      正在查考试时间…→    │  │  · 图书馆座位热力图         │ │
│  │      正在生成计划…"）    │  │  · 社团活动推荐列表         │ │
│  │                         │  │  · 天气 + 出行提示          │ │
│  │  ⚙️ 首次引导流程         │  │  · 📥 数据导入  ⚙️ 设置    │ │
│  │                         │  │  · 空闲30秒自动刷新         │ │
│  └───────────┬─────────────┘  └─────────────┬──────────────┘ │
│              │                              │                 │
│              └──────────┬───────────────────┘                 │
│                         ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              🧠 Agent 推理引擎                            │ │
│  │                                                           │ │
│  │  模型：DeepSeek（via LangChain OpenAI Functions Agent）   │ │
│  │  模式：Plan & Execute                                    │ │
│  │                                                           │ │
│  │  System Prompt 核心指令：                                  │ │
│  │  ┌───────────────────────────────────────────────────┐   │ │
│  │  │ "你是校园先知，一个大学生的AI校园管家。            │   │ │
│  │  │  你有三个核心行为准则：                            │   │ │
│  │  │  ① 主动感知——每次对话开始时检查环境变化，          │   │ │
│  │  │     发现异常立即提醒用户                           │   │ │
│  │  │  ② 深思熟虑——复杂任务先列出计划再执行，           │   │ │
│  │  │     让用户看到你的思考过程                         │   │ │
│  │  │  ③ 自我检查——完成每个任务后自查：遗漏了吗？       │   │ │
│  │  │     不合理吗？有更好的方案吗？                     │   │ │
│  │  │  你的语气：温和、简洁、像学长/学姐一样靠谱。      │   │ │
│  │  │  你绝对不能：编造数据、替用户做决定、             │   │ │
│  │  │     在不确定时给出确定语气。"                      │   │ │
│  │  └───────────────────────────────────────────────────┘   │ │
│  │                                                           │ │
│  │  记忆系统：                                               │ │
│  │  · 工作记忆：Streamlit session_state（对话上下文）        │ │
│  │  · 长期记忆：SQLite（用户画像、偏好、历史行为）            │ │
│  │  · 知识库：SQLite 关键词匹配（校历、校园攻略、FAQ）       │ │
│  └─────────────┬───────────────────────────────────────────┘ │
│                │                                              │
│                ▼                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │     👁️ 感知引擎（页面加载 / 用户操作 / 空闲30秒触发）    │ │
│  │                                                           │ │
│  │  巡检项：                                                 │ │
│  │  · 天气变化 → 影响出行 → 触发提醒                        │ │
│  │  · 考试 < 3天 + 无复习计划 → 警报                        │ │
│  │  · 课表冲突（新增活动 vs 已有日程）→ 通知               │ │
│  │  · 食堂/图书馆状态异常 → 提示替代方案                    │ │
│  │  · 已过期未处理的日程提醒 → 温和再次提醒                 │ │
│  └────────────────────────┬────────────────────────────────┘ │
│                           │                                   │
│                           ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │       🔧 插件式工具层（OPC 开放架构）                     │ │
│  │                                                           │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │ │
│  │  │  查询工具    │  │  行动工具    │  │  分析工具       │  │ │
│  │  │             │  │             │  │                 │  │ │
│  │  │ 📅 课表查询 │  │ 📝 创建日程 │  │ ⚠️ 冲突检测    │  │ │
│  │  │ 🍽️ 食堂人流 │  │ 🔔 设置提醒 │  │ 🎯 智能推荐    │  │ │
│  │  │ 📚 图书馆   │  │ 📥 数据导入 │  │                 │  │ │
│  │  │ ⏰ 考试查询 │  │             │  │                 │  │ │
│  │  │ 🎉 社团活动 │  │             │  │                 │  │ │
│  │  │ 🌤️ 天气查询 │  │             │  │                 │  │ │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │ │
│  │                                                           │ │
│  │  每个工具 = 一个独立 Python 文件                          │ │
│  │  命名规范: tools/query_schedule.py                        │ │
│  │  注册方式: @tool 装饰器 → 自动加入 tool_registry          │ │
│  │  扩展方式: 新增 py 文件 → Agent 启动时自动发现            │ │
│  │  ↑ OPC 设计意图：开放、可扩展、第三方可注册新工具         │ │
│  └────────────────────────┬────────────────────────────────┘ │
│                           │                                   │
│                           ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                  容错 & 基础设施                          │ │
│  │                                                           │ │
│  │  · API 调用：失败自动重试 2 次，超时 30s                 │ │
│  │  · 工具异常：返回友好提示，记录日志，不崩溃               │ │
│  │  · 状态持久化：Streamlit session_state 完整设计           │ │
│  │  · 配置管理：.env 文件管理 API Key，不上传 git            │ │
│  │  · 空闲刷新：30 秒无操作才自动刷新，输入中不打断         │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| **界面** | Streamlit | Python 原生，聊天+仪表盘双面板 |
| **Agent** | LangChain + OpenAI Functions Agent | Plan & Execute 模式 |
| **大模型** | DeepSeek (deepseek-chat) | 兼容 OpenAI API 格式 |
| **数据库** | SQLite | 轻量零配置 |
| **记忆** | LangChain ConversationBufferMemory + SQLite | 短期+长期双层 |
| **数据可视化** | Streamlit 内置 + Altair | 仪表盘图表 |
| **配置管理** | python-dotenv | API Key 管理 |

---

## 4. 核心模块详设

### 4.1 工具层（11 个 Tool）

每个工具是独立的 Python 文件，使用 `@tool` 装饰器注册：

| 文件 | 工具名 | 功能 | 数据来源 |
|------|--------|------|----------|
| `tools/query_schedule.py` | `get_schedule` | 查询指定日期/周的课表 | SQLite（用户导入或对话输入） |
| `tools/query_cafeteria.py` | `get_cafeteria_crowd` | 查询食堂当前拥挤度+趋势 | 模拟数据（按时段生成合理曲线） |
| `tools/query_library.py` | `get_library_seats` | 查询图书馆各楼层空座位 | 模拟数据（预留学校API接口） |
| `tools/query_exam.py` | `get_exam_countdown` | 查询考试倒计时+科目列表 | SQLite（用户导入或对话输入） |
| `tools/query_club.py` | `get_club_activities` | 查询近期的社团活动 | SQLite（预设数据+用户关注） |
| `tools/query_weather.py` | `get_weather` | 查询当日+未来天气 | 模拟数据（可切换和风天气等真实API） |
| `tools/action_create_event.py` | `create_event` | 创建日程事件 | SQLite |
| `tools/action_set_reminder.py` | `set_reminder` | 设置提醒（时间+内容） | SQLite |
| `tools/action_import_data.py` | `import_data` | 导入课表/考试数据（Excel/iCal/对话） | SQLite |
| `tools/analyze_conflict.py` | `detect_conflict` | 检测日程冲突 | 调用其他工具结果 |
| `tools/analyze_recommend.py` | `smart_recommend` | 基于用户画像的智能推荐 | SQLite + 规则引擎（Agent 综合结果） |

### 4.2 感知引擎

```
感知引擎执行流程：
  1. 触发条件：用户打开页面 / 发消息 / 空闲30秒未操作
  2. 运行巡检项（按优先级）：
     a. 天气检查 → 发现异常天气 → 通知 Agent
     b. 考试检查 → 临近考试无计划 → 通知 Agent
     c. 冲突检查 → 日程重叠 → 通知 Agent
     d. 过期提醒检查 → events 表中 reminder_time 已过但未处理 → 再次提醒
  3. 如果任何检查触发 → Agent 在对话中主动插播提醒卡片
  4. 更新 last_check 时间戳
```

### 4.3 记忆系统

| 记忆类型 | 存储位置 | 内容 | 生命周期 |
|----------|----------|------|----------|
| **工作记忆** | `st.session_state.messages` | 当前对话历史、Agent 推理中间步骤 | 单次会话 |
| **长期记忆** | SQLite `user_profile` 表 | 学校、学院、年级、偏好、历史行为 | 持久化 |
| **知识库** | SQLite `knowledge_base` 表 | 校历、校园攻略、FAQ（关键词匹配检索） | 持久化 |

### 4.4 Streamlit Session State 结构

```python
st.session_state.messages          # [{"role":"user"/"assistant","content":"...","timestamp":...}]
st.session_state.user_profile      # {"school":"","grade":"","major":"","preferences":[],"onboarding_done":false}
st.session_state.last_check_time   # 感知层上次巡检时间戳
st.session_state.last_interaction  # 用户最后一次操作时间（用于空闲检测）
st.session_state.tool_registry     # ["query_schedule","query_cafeteria",...] 已注册工具列表
```

### 4.5 首次引导流程

用户首次打开应用时（`onboarding_done == False`），Agent 主动发起对话：

1. "嗨！我是校园先知，你的AI校园管家 👋 先认识一下——你是哪个学校的？"
2. "什么专业？下学期大几？"
3. "你有课表文件可以导入吗？或者直接告诉我你哪几天有课也行~"
4. "你最关心什么？（上课不迟到 / 考试复习 / 找自习室 / 社团活动）"

引导完成后存入 `user_profile`，设置 `onboarding_done = True`。

---

## 5. Demo 演示脚本（3 场景 × 3 分钟）

### 场景 1：快速问答（30秒）

```
用户打开页面 → 仪表盘自动加载 → 右侧显示今日课表+天气
用户："我今天什么安排？"
Agent 自动调取课表+天气+食堂+图书馆信息 →
  回复："你今天上午 10:00-12:00 有数据结构课（教三楼 201），
  下午没课。今天多云 22°C，食堂 11:30 前人少，建议早点去。
  图书馆 3 楼还有 45 个空位。需要帮你规划下午自习吗？"
```

### 场景 2：复杂规划（1.5分钟）

```
用户："我还有两周考操作系统，帮我安排下周复习"

Agent 展示思考过程：
  🔍 查询下周课表...
  🔍 查询操作系统考试时间...
  🔍 分析空档时间...
  📋 生成复习计划...

Agent 回复：
  "下周你有 5 个可用自习时段。建议优先级：
  ① 周三下午（4h大块时间）→ 刷操作系统真题
  ② 周一/周五上午没课 → 知识点梳理
  ③ 周二/周四课后2h → 错题回顾
  已帮你创建 5 个日程提醒 ✅"
  
右侧仪表盘自动更新，显示新的日程卡片
```

### 场景 3：主动感知（1分钟）

```
（预置：明天早八 + 预报明天暴雨）

用户打开页面 → 感知引擎检测异常 →
Agent 主动插播：
  "⚠️ 提醒你：明天早上 8 点有操作系统课，而且明天暴雨。
  建议今晚早睡，提前 20 分钟出门，别忘了带伞！
  需要设一个 7:00 的提醒吗？"

用户："好的"
Agent → "已设置：明早 7:00 → 早起+带伞+提前出门 ✅"
```

---

## 6. 项目目录结构

```
campus-insight-agent/
├── app.py                    # Streamlit 主入口
├── config.py                 # 配置（API Key、模型参数）
├── agent/
│   ├── __init__.py
│   ├── engine.py             # Agent 推理引擎（LangChain 封装）
│   ├── prompt.py             # System Prompt 模板
│   └── memory.py             # 记忆管理
├── perception/
│   ├── __init__.py
│   └── monitor.py            # 感知引擎（巡检逻辑）
├── tools/
│   ├── __init__.py            # 工具自动发现 + 注册
│   ├── query_schedule.py
│   ├── query_cafeteria.py
│   ├── query_library.py
│   ├── query_exam.py
│   ├── query_club.py
│   ├── query_weather.py
│   ├── action_create_event.py
│   ├── action_set_reminder.py
│   ├── action_import_data.py
│   ├── analyze_conflict.py
│   └── analyze_recommend.py
├── data/
│   ├── __init__.py
│   ├── database.py           # SQLite 初始化 + CRUD
│   ├── models.py             # 数据模型
│   └── seed.py               # 模拟数据生成
├── ui/
│   ├── __init__.py
│   ├── chat.py               # 对话面板
│   ├── dashboard.py          # 仪表盘
│   ├── onboarding.py         # 首次引导
│   └── components.py         # 可复用 UI 组件
├── utils/
│   ├── __init__.py
│   ├── retry.py              # API 重试 + 容错
│   └── logger.py             # 日志
├── docs/
│   ├── superpowers/specs/    # 设计文档
│   └── competition/          # 比赛材料（创意说明书等）
├── tests/                    # 测试
├── .env.example              # 环境变量模板
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 7. 数据库 Schema

### 7.1 user_profile

```sql
CREATE TABLE user_profile (
    id INTEGER PRIMARY KEY,
    school TEXT,
    grade TEXT,
    major TEXT,
    preferences TEXT,         -- JSON array
    onboarding_done BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 courses（课表）

```sql
CREATE TABLE courses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    day_of_week INTEGER,      -- 0=周一, 6=周日
    start_time TEXT,          -- "08:00"
    end_time TEXT,            -- "10:00"
    location TEXT,
    week_range TEXT,          -- "1-16" 或 "1,3,5,7,9,11,13,15"
    semester TEXT              -- "2026-2027-1"（学年-学期：1=秋,2=春,3=暑期）
);
```

### 7.3 exams

```sql
CREATE TABLE exams (
    id INTEGER PRIMARY KEY,
    course_name TEXT NOT NULL,
    exam_date DATE NOT NULL,
    exam_time TEXT,
    location TEXT,
    notes TEXT
);
```

### 7.4 events（日程）

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    event_date DATE NOT NULL,
    start_time TEXT,
    end_time TEXT,
    location TEXT,
    reminder BOOLEAN DEFAULT 0,
    reminder_time TEXT,       -- "2026-07-19 07:00:00"
    created_by_agent BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.5 club_activities

```sql
CREATE TABLE club_activities (
    id INTEGER PRIMARY KEY,
    club_name TEXT NOT NULL,
    title TEXT NOT NULL,
    activity_date DATE NOT NULL,
    start_time TEXT,
    location TEXT,
    description TEXT,
    tags TEXT                 -- JSON array, e.g. ["体育","户外"]
);
```

### 7.6 knowledge_base

```sql
CREATE TABLE knowledge_base (
    id INTEGER PRIMARY KEY,
    category TEXT,            -- "calendar", "guide", "faq"
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    keywords TEXT             -- 逗号分隔的关键词，用于匹配检索
);
```

---

## 8. 已知限制 & 后续迭代方向

| 限制 | 当前方案 | 后续迭代 |
|------|----------|----------|
| 食堂/图书馆数据为模拟 | 按时段+历史模式生成合理曲线 | 接入学校官方API |
| 无法做真正的后台推送 | Streamlit 空闲刷新模拟 | 换 FastAPI + WebSocket |
| 天气 API 免费额度有限 | 缓存 + 合理轮询间隔 | 升级付费方案 |
| 单用户模式 | SQLite 单机 | 多用户 + PostgreSQL |
| DeepSeek 依赖 | 唯一模型 | 支持模型切换（config 里改一行） |

---

## 9. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| DeepSeek Function Calling 不兼容 LangChain | 中 | 高 | 项目第一步做兼容性验证；备选：手写 tool calling 循环 |
| 开发时间不足（8月15日截止） | 低 | 高 | MVP 优先：工具层+Agent+仪表盘 → 感知层 → 打磨 |
| Streamlit 性能瓶颈 | 低 | 低 | 数据量小，无影响 |

---

## 10. 开发阶段划分

| 阶段 | 内容 | 预计 |
|------|------|------|
| **Phase 0** | 环境搭建 + DeepSeek 兼容性验证 | 1天 |
| **Phase 1** | 数据库 + 模拟数据 + 工具层（11个Tool） | 3天 |
| **Phase 2** | Agent 引擎 + System Prompt + 记忆系统 | 2天 |
| **Phase 3** | Streamlit 界面（对话+仪表盘+引导） | 2天 |
| **Phase 4** | 感知引擎 + 主动提醒 | 1天 |
| **Phase 5** | 联调 + Demo 脚本打磨 + 容错 | 2天 |
| **Phase 6** | 比赛材料（创意说明书等） | 2天 |

> **MVP 定义**：Phase 0-4 完成即为可演示的最小可用产品。Phase 5 是打磨，Phase 6 是文档。
> **如时间紧张**：优先保证 Phase 0-4，Phase 5 压缩到 1 天（只打磨 Demo 脚本），Phase 6 的创意说明书用 AI 辅助快速生成。

---

## 11. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-07-18 | 初始设计文档 |
