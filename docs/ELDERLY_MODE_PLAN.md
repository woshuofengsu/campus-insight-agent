# 老年关怀版（elderly 角色）设计方案

> 背景：三视角锐评指出「给王阿姨和张大爷用的系统，用了给玩家设计的激励」。现有 resident/grid 双角色对老年人门槛过高（多级菜单、小字号、文字输入）。
> 目标：新增**第三个角色 `elderly`（老年关怀版）**，提供大字极简、语音优先、一键呼叫、健康关怀的独立页面。
> 状态：**方案稿（v1）**，待评审后实施。

---

## 0. 方案速览

| 维度 | 设计 |
|---|---|
| 角色 | 新增 `elderly`，与 resident/grid 并列第三个角色 |
| 入口 | 登录页第三个入口（演示账号 `demo_elderly`）+ onboarding「为家中老人设置」向导 |
| 页面 | `ui/pages_elderly/` 独立页面组（大字极简，4-6 个大按钮） |
| 核心能力 | 大字语音上报 / 一键呼叫（含子女）/ TTS 朗读 / 健康档案 / 用药提醒 / 关怀提醒 |
| 数据 | 新增 `elderly_profile` 表（健康档案 + 用药提醒 + 紧急联系人，JSON 字段） |
| 复用 | 语义路由 `agent/router.py`、事件记忆 `data/db_memory.py`、健康风险 `data/db_health_alerts.py`、通知系统 |
| 迁移 | `schema_version` 升至 v9（新增表，走既有版本化迁移框架） |

---

## 1. 角色体系设计

### 1.1 三个角色的定位

| 角色 | 定位 | 面向 |
|---|---|---|
| resident | 标准居民端（知·报·议·督，9 页） | 普通居民 |
| grid | 网格员工作台（6 页） | 社区工作者 |
| **elderly** | **老年关怀版（大字极简，1 个入口页为主）** | 老年居民 / 家属代管 |

### 1.2 权限模型
- `elderly` 与 `resident` 同为"居民侧"角色：可上报、查工单、收通知、评价。
- **不可**进入 grid 页（`ui/guard.require_role` 扩展为白名单：`grid` 页只允许 `grid`）。
- `elderly` 无提案/议事复杂度，不暴露「邻里议事」「治理看板」「治理大屏」等重页面（极简导航天然隔离）。
- 数据层面 `reporter_id` 闭环与 resident 完全一致（通知/满意度/匿名照常）。

### 1.3 入口与引导
- `ui/login.py`：演示入口三栏 → 居民 / 网格员 / **老年关怀版**。
- `ui/onboarding.py`：elderly 角色引导改为「大字设置向导」——可选：是否由家属代管、填子女电话、选常用功能。全程大字号、少输入。
- 种子数据：`data/seed.py` 增加 `demo_elderly`（免密，王大爷，带一份示范档案）。

---

## 2. 页面与交互设计（ui/pages_elderly/）

> 核心思想：**一个主入口页 + 少量二级页**，全站大字（根字号 20px+）、大按钮、少文字、多语音。

### 2.1 主入口页 `home.py`（老年关怀版首页）

大字问候 + 4-6 个大卡片按钮（点击即用）：

| 大按钮 | 功能 | 说明 |
|---|---|---|
| 🗣️ **一句话上报** | 语音/文字上报诉求 | 点开即弹录音按钮，说出"3号楼电梯坏了" → 语义路由 → 工单 |
| 📞 **一键呼叫** | 紧急电话 | 网格员 / 物业 / 急救 120 / **子女**，tel: 拨号大按钮 |
| 📋 **我的工单** | 查进度 | 大字列表：待处理/处理中/已解决 + 谁在处理 |
| 🔊 **听通知** | TTS 朗读 | 点一下把新通知/工单进展朗读出来 |
| 💊 **吃药提醒** | 今日用药 | 大字显示"现在该吃：降压药 1 片"，到点提醒 |
| 🏥 **我的健康** | 健康档案 | 血压/慢病/最近体检（家属或网格员可协助录入） |

### 2.2 二级页
- `report.py`：**语音一键上报**（录音 → 文本 → 确认 → 生成工单，全程大字 + 结果朗读）。
- `progress.py`：我的工单大字版（复用 `get_my_issues`/`get_my_anonymous_issues`，卡片 1.4 倍字号）。
- `notify.py`：通知列表 + 「🔊 朗读」按钮（SpeechSynthesis）。
- `health.py`：健康档案查看/录入（家属代管时）。
- `meds.py`：用药提醒设置（时间表、药名、剂量、开关）。

### 2.3 全局样式
- 复用 `ui/theme.py` token，elderly 路由下注入全局 CSS：`font-size: 20px`、按钮 `min-height: 64px`、卡片更大留白。
- 页面禁用侧边栏复杂区块（elderly 只显示：大字 logo、紧急联系、退出），或直接全屏无侧边栏。

---

## 3. 功能规格

### 3.1 大字 + 语音一键上报（核心）
- **语音输入**：`st.components.v1.html` 注入 Web Speech API 录音按钮（Chrome/Edge 原生支持），识别文本回填输入框；无麦克风权限/不支持时降级为手动文字输入（**渐进增强，绝不阻塞**）。
- **语义路由复用**：识别文本 → `agent.router.route_intent` → 命中 `report_issue` → 调 `report_issue`（自动分类/定级）→ 结果大字展示 + TTS 朗读"工单已生成，编号 #X"。
- 不命中上报意图时，提示"这是一句话上报页面，直接说您遇到的问题"。

### 3.2 一键呼叫（含子女紧急呼叫）
- `elderly_profile.emergency_contact`：子女/家属姓名 + 电话（可多个）。
- 大按钮组：`📞 网格员 62319876` / `🔧 物业 62310086` / `🚨 急救 120` / `👨👩👧 子女`（tel: 拨号）。
- 子女按钮优先展示（第一个大按钮），未设置时显示"家属未设置"并引导录入。

### 3.3 语音播报/朗读（TTS）
- 浏览器 `speechSynthesis`（Web Speech API）：朗读通知标题、工单进展、"现在该吃降压药了"。
- 入口：通知页「🔊 朗读」、主入口「听通知」、上报成功后自动朗读结果。
- 渐进增强：不支持 TTS 的浏览器回退为大字文本 + 闪烁强调。

### 3.4 健康档案（个人健康信息）
- `elderly_profile.health_info`（JSON）：慢病（高血压/糖尿病…）、过敏、血型、紧急注意事项、最近体检结果摘要。
- 查看：大字卡片展示；录入：家属/网格员协助（elderly 本人也可看只读）。
- **隐私**：健康信息仅对本人 + 网格员（grid）可见；API 不暴露给公开端点。

### 3.5 用药提醒（个性化设置）
- `elderly_profile.medication_reminders`（JSON 数组）：`[{name, dosage, times: ["08:00","20:00"]}]`。
- 触发：页面加载 + 感知周期内比对当前时间与 `times`（±30 分钟窗口）→ 未确认则：
  1. 站内通知 `create_notification`（"该吃：降压药 1 片"）。
  2. 主入口页大卡片置顶（大字 + 闪烁）。
  3. 可选 TTS 朗读。
  4. 「✓ 我已吃」确认按钮（记入 event_memory，供家属/网格员查看依从性）。
- 数据只读入口：`data/db_elderly.py` 提供 `due_reminders(user_id, now)`。

### 3.6 关怀提醒（体检/助餐/防诈骗）
- 复用 `data/db_health_alerts.py` 健康风险等级 + seed 知识库（助餐点、家庭医生电话）+ event_memory：
  - 高风险季 → 主入口页大字提醒"流感高发季，注意保暖/打疫苗"。
  - 助餐点 → 大字卡片"今天助餐点：中心花园东侧 11:00-13:00"。
  - 防诈骗 → 节前/定期推送知识库防诈条目（大字 + 朗读）。
- 实现为 `elderly_profile` 的关怀提醒聚合函数 `get_care_reminders(user_id)`，页面 + 通知双通道。

### 3.7 每日平安打卡（独居安全核心）
- **概念**：elderly 每天至少一次与系统互动（打开页面 / 点「我没事」/ 上报 / 查工单等任一操作），系统记录 `last_active_at`。
- **无人应答检测**：感知周期内对每个 elderly 用户检查——超过阈值（默认 24h）未互动且当日未打卡 → 站内通知子女 + grid 端「重点关注」标红，提醒网格员上门/电话。
- **呼应现有叙事**：seed 里"独居老人张大爷三天未出门，邻居敲门无人应"正是这一机制要接住的场景——系统主动发现，而不是等邻居上报。
- **实现**：`elderly_profile.last_active_at` + `touch_active(user_id)`；`get_inactive_elders(hours)`；感知 monitor 新增 `_check_elderly_safety()`。

### 3.8 SOS 紧急求助大按钮（区别于普通呼叫）
- 位置：主入口页顶部，红色大按钮「🆘 我出事了」（与"一键呼叫"的主动拨号不同，这是"我动不了，快来"）。
- 流程：按下 → **大字确认（防误触）** → 多路通知：子女 + 网格员 + 物业（站内；grid 工作台「⚠️ SOS」置顶；邮件 best-effort）→ **30 秒内可取消误报**。
- 记录：`sos_log` 表（时间/状态/处理人），grid 端可标记「已处理」。

### 3.9 紧急信息卡
- 主入口页一键展开：**血型 / 过敏 / 慢病 / 正在服用的药 / 紧急联系人 / 医保卡号（可选）**。
- 目的：急救人员或网格员上门时 3 秒看到关键信息；数据来自 `health_info`（结构化存储）。

### 3.10 防误触与可用性增强
- 上报 / SOS 前**大字二次确认**（"确定要上报吗？"）。
- elderly 全局**高对比度**（不依赖颜色传达信息，深色文字+浅底或纯黑白）+ 大图标（emoji+文字，点击区域 ≥64px）。
- 避免下拉框、滑动条等精确控件（手抖不易操作）。
- TTS 语速放缓（rate 0.9，页面可调）。

### 3.11 血压/血糖测量记录
- 大字录入最近一次数值（收缩压/舒张压/血糖），展示近 7 次趋势；家属/网格员可看；录入记入 event_memory。

### 3.12 恶劣天气出行提醒
- 复用感知天气：雨雪 / 大风 / 高温日，主入口页置顶大字"今天有雨，尽量别出门；买菜/取药可联系网格员"。防滑倒（老人最怕跌倒）。

### 3.13 网格员端「重点关注老人」
- grid 工作台新区块：独居（`is_living_alone=1`）/ 高龄 / 有慢病的 elderly 列表，显示：最近活跃时间、今日用药确认、待办（SOS 未处理 / 未打卡），一键电话/上门。
- 数据：`elderly_profile.is_living_alone` + 安全检测聚合。

---

## 4. 数据模型（迁移 v9/v10）

```sql
-- 新增表1：老年档案（健康 + 用药 + 联系人 + 平安状态，JSON 字段；迁移 _m9）
CREATE TABLE IF NOT EXISTS elderly_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,          -- 关联 user_profile.id
    health_info TEXT DEFAULT '{}',            -- 慢病/过敏/血型/体检摘要/紧急信息卡
    medication_reminders TEXT DEFAULT '[]',   -- [{name, dosage, times:[...]}]
    emergency_contact TEXT DEFAULT '[]',      -- [{name, relation, phone}] 子女/家属
    is_living_alone INTEGER DEFAULT 0,        -- 独居标记（网格员重点关注）
    is_managed_by_family INTEGER DEFAULT 0,   -- 是否家属代管
    last_active_at TIMESTAMP,                 -- 平安打卡：最近一次互动时间
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_profile(id)
);

-- 新增表2：SOS 紧急求助记录（迁移 _m10）
CREATE TABLE IF NOT EXISTS sos_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',            -- pending / done / cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    handled_at TIMESTAMP
);
```

- 走既有版本化迁移：`db_core._SCHEMA_CURRENT_VERSION = 10`，`_m9_create_elderly_profile` + `_m10_create_sos_log`，post 迁移列表追加。
- 新模块 `data/db_elderly.py`：`get_profile` / `upsert_profile` / `set_health_info` / `set_medication_reminders` / `set_emergency_contact` / `due_reminders` / `get_care_reminders` / `touch_active` / `get_inactive_elders` / `sos_request` / `get_pending_sos` / `mark_sos_done`。


---

## 5. 技术实现清单（文件级）

| 类别 | 文件 | 改动 |
|---|---|---|
| 迁移 | `data/db_core.py` | `_m9_create_elderly_profile`，版本 → 9 |
| 数据 | `data/db_elderly.py`（新） | 档案/健康/用药/联系人/提醒 聚合函数 |
| 数据 | `data/database.py` | re-export `db_elderly` 函数 |
| 角色 | `app.py` | `st.navigation` 加 elderly 页面组分支 |
| 角色 | `ui/guard.py` | `require_role` 支持 elderly（grid 页白名单不变） |
| 登录 | `ui/login.py` | 第三个演示入口 `demo_elderly` |
| 引导 | `ui/onboarding.py` | elderly 大字设置向导（家属代管/子女电话） |
| 种子 | `data/seed.py` | `demo_elderly` + 示范档案 |
| 页面 | `ui/pages_elderly/home.py`（新） | 主入口大字页 + 大按钮 |
| 页面 | `ui/pages_elderly/report.py`（新） | 语音一键上报 |
| 页面 | `ui/pages_elderly/progress.py`（新） | 我的工单大字版 |
| 页面 | `ui/pages_elderly/notify.py`（新） | 通知 + TTS 朗读 |
| 页面 | `ui/pages_elderly/health.py`（新） | 健康档案 |
| 页面 | `ui/pages_elderly/meds.py`（新） | 用药提醒设置（含"我已吃"确认） |
| 页面 | `ui/pages_elderly/sos.py`（新） | SOS 求助大字确认/取消 |
| 组件 | `ui/elderly_components.py`（新） | 大字卡片、大按钮、二次确认、TTS/ASR JS 工具 |
| 感知 | `perception/monitor.py` | 新增 `_check_elderly_safety()`：平安打卡检测 + SOS 置顶 |
| grid | `ui/pages_grid/dashboard.py` | 「⚠️ SOS 求助」+「👴 重点关注老人」区块 |
| 复用 | `agent/router.py` / `data/db_memory.py` / `data/db_health_alerts.py` / 通知系统 | 无改动，直接调用 |
| 测试 | `tests/test_elderly.py`（新） | 档案 CRUD + 用药触发 + 平安打卡 + SOS + 角色守卫 |

---

## 6. 实施路线图

| 阶段 | 内容 | 验收标准 | 估时 |
|---|---|---|---|
| P0 | elderly 角色 + 路由 + 登录/seed + 大字主入口页 + 一键呼叫 + SOS（含防误触确认） | elderly 登录进大字页；大按钮可用；tel: 拨号；SOS 确认→通知链；grid 页不可达 | 2 天 |
| P1 | 语音一键上报 + TTS 朗读 + 我的工单大字版 + 通知朗读 | 录音→工单生成；"工单已生成 #X"被朗读；不支持时降级文字 | 1.5 天 |
| P2 | 健康档案（含紧急信息卡）+ 用药提醒（含"我已吃"确认）+ 关怀提醒 + 子女呼叫 | 档案/紧急卡展示；到点用药通知+确认+依从可见；关怀提醒聚合显示 | 2 天 |
| P3 | **安全闭环**：平安打卡 + 无人应答检测 + SOS 通知链 + grid 重点关注老人 | 24h 未互动→通知子女/网格员；SOS 置顶+可处理；grid 关注列表含活跃/用药/待办 | 1.5 天 |
| P4 | 血压/血糖记录 + 恶劣天气出行提醒 + 高对比度微调 | 录入与趋势展示；雨雪天主页置顶大字提醒；对比度达标 | 1 天 |
| P5 | 测试 + 全量回归 + CHANGELOG | `pytest` 全绿（含 `tests/test_elderly.py`）；日志更新 | 0.5 天 |

---

## 7. 风险与取舍

1. **语音依赖浏览器能力**：Web Speech API 的 ASR（Chrome/Edge 支持较好）与 TTS 均需现代浏览器；方案按**渐进增强**设计，不支持时自动降级文字输入/大字展示，绝不阻塞核心上报。
2. **老年人登录门槛**：elderly 默认**免密**（与 resident 一致）+ onboarding 支持"家属代管"（子女扫码/代设），降低首登门槛。
3. **健康数据隐私**：健康档案仅本人 + grid 可见，页面守卫 + 不暴露到公开 API；方案评审时需明确"网格员可看健康档案"的边界（建议：网格员仅看"需要照顾的注意事项"，不看完整病历）。
4. **提醒可能打扰**：用药/关怀提醒默认关闭（`is_managed_by_family=0` 时仅页面展示，不推送通知），家属开启后才推送，避免骚扰。
5. **与 resident 的职责重叠**：elderly 本质是"居民侧的无障碍视图"，后续若想合并，可改为 resident 的 `ui_mode=elderly` 开关；当前按独立角色做，语义更清晰、改动隔离。
6. **安全机制的误判风险**：平安打卡存在"假阴性"（老人天天在家但不用系统=被误判为失联）。因此「未打卡」只定义为**提醒级**（通知子女/网格员留意，非警报），且阈值可配置；SOS 支持取消误报。绝不能让系统因误判制造恐慌。
7. **安全机制的真实覆盖**：平安打卡/SOS 依赖老人**主动使用系统**——对完全不用手机的老人无效。此类老人靠「网格员重点关注 + 邻里探访」兜底（对应现有 seed 的独居探访叙事），系统负责把信息送到网格员手上。

---

## 8. 待评审确认点

**已确认（按推荐）：**
1. ✅ 健康档案对网格员仅暴露「照顾注意事项」，不暴露完整病历。
2. ✅ 用药提醒只做站内通知 + TTS，不做短信/电话。
3. ✅ `demo_elderly` 沿用 seed「独居老人张大爷」（11号楼3单元301，高血压，子女电话）。

**新增待确认：**
4. 平安打卡阈值（默认 **24h**）与通知对象（子女站内 + 网格员）是否合适？是否需要"每 12h 温和提醒一次"？
5. SOS 通知链当前为站内 + 邮件 best-effort，**不发短信**（成本），是否可接受？
6. 「家属关怀端」独立子女页面本期不做（通过通知 + 网格员关怀块覆盖），是否 OK？
7. 血压/血糖记录是否只做**大字手录 + 近 7 次趋势**即可，不做设备对接？
