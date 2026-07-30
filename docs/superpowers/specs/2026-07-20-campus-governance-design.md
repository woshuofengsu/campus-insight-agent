# 校园先知 CampusInsight Agent — 基层治理方向设计文档 v2

> **比赛**："京彩AI·智汇全球"首都大学生智能体OPC创新大赛
> **赛道**：基层治理
> **截止日期**：2026年8月15日
> **状态**：重构中 — 替代 v1（2026-07-18 校园管家方案）

---

## 0. 版本说明

v1（2026-07-18）定位为"大学生 AI 校园管家"，覆盖课表、考试、食堂、图书馆、社团、天气六大个人场景。经讨论，赛道主题为**基层治理**，个人助手方向与赛道不匹配。

v2 重新定位为**校园微治理参与平台**，核心理念：让学生从"被管理者"变成"治理参与者"。

---

## 1. 产品概述

### 1.1 一句话描述

校园先知 —— 让每个学生都能"知校园事、报校园修、议校园政、督校园治"的 AI 治理伙伴。

### 1.2 四字架构

```
知 ─→ 报 ─→ 议 ─→ 督
│      │      │      │
知情    参与    建言    监督
```

| 环节 | 板块 | 一句话 | 治理价值 |
|------|------|--------|----------|
| **知** | 🌊 校园脉搏 | 这周发生了什么？下周有什么大事？ | 知情权——不被蒙在鼓里 |
| **报** | 🔧 随手报修 | 发现问题，自然语言上报 | 参与权——我的报修有人管 |
| **议** | 🗳️ 有话说 | 提建议、附议别人、参与AI发起的议题 | 表达权——我的声音被听见 |
| **督** | 📊 治理看板 | 工单进度、提案排行、治理健康度 | 监督权——我看到改变在发生 |

### 1.3 完整用户体验路径

```
周一早上，学生打开 CampusInsight：

🌊 校园脉搏 告诉他：
  "本周三停水检修，周五校运动会。上周全校上报了 8 个设施问题，已解决 6 个。"

他想起一件事 → 🔧 随手报修：
  "食堂二楼的灯坏了三个" → AI自动分类"设施维修"→ 生成工单 #043

下午他刷到一个话题 → 🗳️ 有话说：
  AI自动发起的议题："食堂菜品价格最近涨了，你怎么看？"
  → 他表达意见 → AI 汇总到民意报告

周末 → 📊 治理看板：
  他报修的那盏灯修好了，#043 显示"已解决"。
  本周他参与了 2 次讨论，1 次上报——看板记录了他的参与足迹。
```

---

## 2. 架构设计

### 2.1 OODA 循环 · 治理版本

v1 的 OODA 服务于"个人日程管理"，v2 重新定义每层含义：

| OODA 层 | v1（个人管家） | v2（基层治理） |
|---------|--------------|--------------|
| **Observe 感知** | 检查天气+考试+日程冲突 | 巡检工单变化、议题热度、校园重大事件 |
| **Orient 理解** | 理解用户当天的优先级 | 理解当前校园治理整体状况，判断哪些信息值得推送给用户 |
| **Decide 决策** | 选择合适的工具链 | 自动分类上报内容、匹配已有提案去重、决定是否发起 AI 议题 |
| **Act 执行** | 查询课表/创建日程 | 生成工单、发布提案、汇总民意、推送校园简报 |
| **Reflect 反思** | 检查是否遗漏提醒 | 检查工单是否过期未处理、提案是否获足够附议但未推进 |

### 2.2 架构图

```
┌─────────────────────────────────────────────────────────────┐
│              校园先知 · CampusInsight Agent                  │
│              基层治理赛道 · 四板块架构                        │
│                                                               │
│  ┌─────────────────────────┐  ┌────────────────────────────┐ │
│  │     💬 对话面板          │  │      📊 治理看板            │ │
│  │                         │  │                            │ │
│  │  · 自然语言上报问题      │  │  🌊 校园脉搏              │ │
│  │  · AI 自动分类+定级      │  │     · 本周热点简报         │ │
│  │  · 提建议+附议          │  │     · 即将发生的大事        │ │
│  │  · 参与AI议题讨论       │  │                            │ │
│  │  · 追踪工单进度         │  │  🔧 随手报修              │ │
│  │                         │  │     · 工单状态实时追踪      │ │
│  │  ⚙️ 首次引导流程         │  │     · 热点类别分布         │ │
│  │                         │  │                            │ │
│  │                         │  │  🗳️ 有话说                │ │
│  │                         │  │     · 热门提案排行         │ │
│  │                         │  │     · 活跃议题一览          │ │
│  │                         │  │                            │ │
│  │                         │  │  📊 治理透明窗            │ │
│  │                         │  │     · 治理健康度KPI        │ │
│  │                         │  │     · 学生参与足迹         │ │
│  └───────────┬─────────────┘  └─────────────┬──────────────┘ │
│              │                              │                 │
│              └──────────┬───────────────────┘                 │
│                         ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              🧠 Agent 推理引擎（OODA 循环）               │ │
│  │                                                           │ │
│  │  Observe  →  Orient   →  Decide    →  Act     → Reflect  │ │
│  │  巡检工单   理解治理     自动分类       生成工单   过期追踪 │ │
│  │  热点发现   判断优先级   匹配去重       汇总民意   闭环反馈 │ │
│  │  事件感知   个性推荐     议题生成       推送简报   质量检查 │ │
│  └─────────────┬───────────────────────────────────────────┘ │
│                │                                              │
│                ▼                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │       🔧 插件式工具层（7 个治理工具）                      │ │
│  │                                                           │ │
│  │  查询工具          行动工具          分析工具             │ │
│  │  🌊 校园脉搏       🔧 上报问题      📊 治理统计          │ │
│  │  🗳️ 查询提案      🗳️ 创建提案      🎯 议题汇总          │ │
│  │  🔧 查询工单      🗳️ 附议提案                          │ │
│  │  🌤️ 天气查询（感知触发用）                                │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 数据库设计

在现有 8 张表基础上，新增 2 张表：

### 3.1 proposals（校园提案）

```sql
CREATE TABLE proposals (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT DEFAULT '其他',      -- 同 campus_issues 的 7 个分类
    supporter_count INTEGER DEFAULT 1, -- 含提案人自己
    status TEXT DEFAULT '讨论中',      -- 讨论中/已回应/已采纳/已实施
    response_text TEXT DEFAULT '',     -- 校方/管理方回应
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.2 discussion_topics（民意议题）

```sql
CREATE TABLE discussion_topics (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT DEFAULT '',
    created_by_agent INTEGER DEFAULT 1, -- 1=AI自动发起, 0=人工
    is_active INTEGER DEFAULT 1,
    participant_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP
);
```

### 3.3 topic_opinions（议题下的意见）

```sql
CREATE TABLE topic_opinions (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    participant_label TEXT DEFAULT '匿名学生',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topic_id) REFERENCES discussion_topics(id)
);
```

### 3.4 保留的原有表

| 表 | 保留/删除 | 理由 |
|----|----------|------|
| user_profile | ✅ 保留 | 用户画像对个性化推荐有价值 |
| campus_issues | ✅ 保留 + 强化 | 随手报修核心表 |
| feedback_items | ✅ 保留 | 有话说板块使用 |
| knowledge_base | ✅ 保留 + 扩展 | 校园脉搏的数据源（校历、政策、攻略） |
| courses | ❌ 删除 | 与治理无关 |
| exams | ❌ 删除 | 与治理无关 |
| events | ❌ 删除 | 与治理无关 |
| club_activities | ❌ 删除 | 与治理无关 |

---

## 4. 工具层（7 个工具）

| 文件 | 工具名 | 板块 | 功能 | 数据来源 |
|------|--------|------|------|----------|
| `tools/query_campus_pulse.py` | `get_campus_pulse` | 🌊 校园脉搏 | 本周热点+下周大事 | SQLite knowledge_base + AI 分析 |
| `tools/action_report_issue.py` | `report_issue` | 🔧 随手报修 | 上报校园问题 | SQLite campus_issues |
| `tools/query_campus_issues.py` | `query_issues` | 🔧 随手报修 | 查询工单状态 | SQLite campus_issues |
| `tools/query_campus_issues.py` | `get_governance_stats` | 📊 治理看板 | 治理统计数据 | SQLite campus_issues |
| `tools/query_proposals.py` | `get_proposals` | 🗳️ 有话说 | 查询提案列表 | SQLite proposals |
| `tools/action_create_proposal.py` | `create_proposal` | 🗳️ 有话说 | 创建提案 | SQLite proposals |
| `tools/action_support_proposal.py` | `support_proposal` | 🗳️ 有话说 | 附议提案 | SQLite proposals |
| `tools/query_topics.py` | `get_topics` | 🗳️ 有话说 | 查询AI议题 | SQLite discussion_topics |
| `tools/action_express_opinion.py` | `express_opinion` | 🗳️ 有话说 | 发表意见 | SQLite topic_opinions |
| `tools/query_weather.py` | `get_weather` | (感知触发) | 天气查询 | 和风天气API |

---

## 5. Demo 演示脚本（3 场景 × 3 分钟）

### 场景 1：知 + 报（30 秒）

用户打开页面 → 🌊 校园脉搏展示本周简报 → 用户看到一个设施问题 → 自然语言上报 → AI自动分类定级 → 生成工单

### 场景 2：议（1.5 分钟）

用户浏览 🗳️ 有话说 → 看到 AI 自动发起的议题 → 表达意见 → 又看到别人的提案 → 附议 + 自己创建提案

### 场景 3：督（1 分钟）

感知引擎检测变化 → 用户昨天报修的工单变成"已解决" → 主动推送反馈卡片 → 用户打开 📊 治理看板 → 看到本周参与足迹和数据变化

---

## 6. 开发阶段（剩余 26 天）

| 阶段 | 内容 | 时间 |
|------|------|------|
| **Day 1-2** | 代码重构：删除旧工具 + 新建 governance 工具 + 数据库更新 | 2 天 |
| **Day 3-4** | UI 重构：治理看板 + 对话面板适配 + System Prompt 重写 | 2 天 |
| **Day 5** | 种子数据 + Demo 脚本打磨 | 1 天 |
| **Day 6-10** | 比赛材料：创意说明书、技术报告、演示脚本、PPT | 5 天 |
| **Buffer** | 联调 + 录屏 + 意外处理 | 5 天 |

---

## 7. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-07-20 | v2 重构：从"校园生活管家"转向"基层微治理参与平台" |
