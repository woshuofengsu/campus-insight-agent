# 交接文档 · 社区先知 CommunityInsight Agent

> 生成时间：2026-08-13 深夜。目的：让接手的新 agent 无需看历史聊天记录，也能无缝继续开发。
> 配合 `CHANGELOG.md`（已完成的 P0-P2 + 审查修复）一起读。

---

## 0. TL;DR（30 秒了解现状）

这是一个**社区治理 AI Agent**（接诉即办 / 海淀小区），技术栈 = LangChain + DeepSeek + Streamlit 多页 + SQLite，双角色：**居民（resident）** + **网格员（grid）**。项目原名叫「校园先知 CampusInsight Agent」，正在做**全量去「换皮」重命名**（把残留的校园/campus/student/teacher 标识全部改成社区/community/resident/grid）。

当前处于**重命名做到一半**的中间态：

| 任务 | 状态 |
|---|---|
| ① campus → community（工具/类/路由/表/库） | ✅ 完成 + 表迁移 + 测试 318 passed |
| ② student/teacher → resident/grid（角色值 + 目录） | ✅ 完成 + 测试 318 passed（已收尾） |
| ③ student_id/school/grade/major → resident_id/community/building/unit（字段） | ⏸️ **未开始**（有 grade 双语义陷阱） |
| ④~⑧ 文档披露 / 战线二三 / 语义测试 / 全量回归 | ⏸️ 未开始 |

**接手第一件事**：直接从任务③开始。任务②已收尾干净（进程已杀、残留已删、role 迁移已在 `init_db` 里、测试全绿）。

---

## 1. 项目定位

- 面向 **Agent 比赛**（截止 2026-08-15），定位是「社区先知 CommunityInsight Agent」。
- 核心能力：接诉即办工单闭环、SLA 时效预警、邻里议事、健康防护、治理大屏、周报、邮件通知、匿名上报、满意度闭环。
- 已从「校园治理」迁移为「海淀小区社区治理」：居民上报诉求 → 网格员处理 → 满意度评价闭环。

---

## 2. 安全红线（绝对遵守，违反会出事故）

1. **`.env` 里有真实密钥，绝不提交/打包**：`DEEPSEEK_API_KEY`、`HEFENG_API_KEY`、QQ 邮箱 SMTP 授权码。`.env` 已在 `.gitignore` 里。
2. **QQ SMTP 凭据是敏感信息**（QQ 号 + 授权码），只存在于 `.env`，任何文档/代码/日志里都不得出现明文。
3. **「技术实现报告.html」和「创意说明书.html」不改**，`docs/competition/*.html` 一律不重新生成（不要跑 `docs/competition/build_html.py`）。这些是比赛已定稿文档。
4. **密码盐 `campus-insight-salt-2026` 不能改**（`data/db_core.py` 的 `_verify_password` 里）。改了会破坏所有旧密码哈希，导致老账号登录失败。

---

## 3. 当前状态（代码 / 数据 / 进程）

### 3.1 代码状态
- 任务①、② 的代码改动**已全部落盘**。
- 最后一次全量测试基线：**318 passed, 7 subtests passed**（`python -m pytest -q`），是在**任务①完成后**跑出来的。
- **任务②改完后还没跑过 pytest** —— 这是当前最需要补的一步。

### 3.2 数据状态（`data/` 目录）
| 文件 | 状态 | 说明 |
|---|---|---|
| `community_insight.db` | **主库** ✅ | `config.py:69` 指向它。内含 `demo_resident`(resident) + `demo_grid`(grid) 两个账号，39 条工单。**表已改名** `community_issues`，**角色值已迁** resident/grid。但**字段名还是旧的** school/grade/major/student_id（任务③没做） |
| `test_teacher.db` | 旧测试库 | 测试残留，可保留 |

> 已清理：旧进程 PID 33376 已杀；残留 `campus_insight.db`、`campus.db` 已删。`data/` 现在只剩 `community_insight.db`（主库）和 `test_teacher.db`（测试库）。

---

## 4. 本次会话已完成的工作

### 任务①：campus → community 全量重命名 ✅
替换范围（完整词，安全）：
- 工具名 `get_campus_pulse` → `get_community_pulse`、`get_school_policy` → `get_community_policy`
- 类 `CampusAgent` → `CommunityAgent`
- 路由 `/api/campus-pulse` → `/api/community-pulse`
- 表 `campus_issues` → `community_issues`
- 库 `campus_insight.db` → `community_insight.db`
- 工具文件 `query_campus_issues.py` → `query_community_issues.py`、`query_campus_pulse.py` → `query_community_pulse.py`
- 函数 `get_campus_events` → `get_community_events`、`cached_campus_events` → `cached_community_events`、`campus_density` → `community_density`
- 主题 key `_campus_theme` / `campus_theme` → `_community_theme` / `community_theme`，Altair 主题 `"campus"` → `"community"`

数据迁移：在 `data/db_core.py` 的 `init_db()` 里加了 `ALTER TABLE campus_issues RENAME TO community_issues`（在 CREATE TABLE 之前执行，幂等）。

### 任务②：student/teacher → resident/grid 重命名（代码完成）
- 角色值 `student` → `resident`、`teacher` → `grid`（代码层，含 `.py` 全量替换 + 中文测试数据「学生/校园/教师」→「居民/社区/网格员」）
- 目录 `ui/pages_teacher/` → `ui/pages_grid/`（含 app.py 的 `st.Page` 路径 6 处 + 各页头注释 + `__init__.py`）
- demo 账号 `demo_student` → `demo_resident`、`demo_teacher` → `demo_grid`（`data/seed.py`）
- `student_id` 字段**刻意保留未动**（留给任务③）
- DB 里角色值已通过 seed 重跑生效为 resident/grid

**遗留隐患**：`init_db()` 里**还没有 role 值的 UPDATE 迁移**（`student`→`resident`）。当前本机 DB 碰巧已经是对的（因为 seed 重跑过），但**换一台有旧 DB 的机器，init_db 不会自动迁 role**。需要在任务③或收尾时补上。

---

## 5. 任务②收尾结果（已完成，无需再做）

收尾三步已在交接前完成：

1. ✅ 旧进程 PID 33376 已杀（`taskkill //F //PID 33376`）
2. ✅ 残留 DB `campus_insight.db`、`campus.db` 已删
3. ✅ role 值迁移**确认已存在**于 `data/db_core.py` 的 `init_db()`（`UPDATE user_profile SET role='resident' WHERE role='student'` 等，含 demo 账号用户名迁移），无需补写
4. ✅ 全量测试 **318 passed, 7 subtests passed**（`python -m pytest -q`）
5. ✅ demo 账号冒烟验证：`demo_resident`（无密码）/ `demo_grid`（`demo123`）均可正常登录

接手时如需自检，只需跑 `python -m pytest -q` 和 `streamlit run app.py` 即可。

---

## 6. 完整待办清单（任务③~⑧）

> 详细方案在聊天记录里（迁移 jsonl 后可查）；下面是标题 + 我掌握的方向。

- **③ 字段重命名**（见 §7，最复杂，含 grade 陷阱）
- **④ 诚实披露**：更新 `docs/TECHNICAL.md`，说明「本项目由校园治理演进为社区治理，命名同步迁移」的演进与命名对照表（旧→新）
- **⑤ 战线二**：主动发现 + 主动派单（Agent 从舆情/感知数据主动发现问题、自动派单给网格员）
- **⑥ 战线三**：匿名哈希 + 满意度透传原因（匿名上报身份哈希化；满意度评价透传「不满意原因」）
- **⑦ 兜底 4 个语义测试**：SLA 时区、分级边界、满意度闭环、匿名
- **⑧ 全量回归 + 写日志 + 最终审查**：跑全量测试 → 更新 `CHANGELOG.md` → 按日志自查一遍
- **⑨ 换皮遗漏：`data/db_academic.py` 校园教务死代码**：见 §10.9。这是前几轮换皮忽略的校园残留（模块名 `db_academic` + 表 `courses/exams/events/club_activities`），无 UI/Agent 调用者，需决策删除还是保留。

---

## 7. 任务③详细方案（字段重命名，含 grade 双语义陷阱）

### 7.1 替换映射
| 旧字段 | 新字段 | 说明 |
|---|---|---|
| `student_id` | `resident_id` | 无歧义 |
| `school` | `community` | 无歧义（school 只作「小区」字段） |
| `grade` | `building` | ⚠️ **有双语义陷阱**，见下 |
| `major` | `unit` | 无歧义 |

### 7.2 `grade` 的双语义（最容易踩的坑）
`grade` 这个词在代码里**有两层含义**，只能改其中一层：

- ✅ **要改成 `building`**（用户字段「楼栋」）：`data/db_user.py`、`ui/components.py`、`data/db_governance.py`、`ui/sidebar.py`、`ui/pages/mine.py`、`agent/prompt.py`、`data/models.py`、`data/seed.py`、`ui/onboarding.py`、`ui/login.py`
- ❌ **绝不能改**（健康度等级「优/良/需改进」）：`data/db_health.py`、`api.py`、`agent/fallback.py`、`ui/pages_grid/dashboard.py`、`ui/pages/transparency.py`、`ui/pages/bigscreen.py`、`ui/prefetch.py`、`agent/weekly_report.py`、`agent/governance_audit.py`

**做法**：不要对 `grade` 做全局替换。要么逐个文件手动改「字段」上下文，要么用脚本但先保护健康度 `grade`（例如把 `grade` 作为 dict key 出现在 `h.get("grade")` / `health["grade"]` / 健康分上下文里的先占位保护）。

### 7.3 数据迁移（加到 `init_db()`，幂等，需检查旧列存在）
```python
# 字段重命名（SQLite 3.25+ 支持 RENAME COLUMN）
_col_renames = [
    ("student_id", "resident_id"),
    ("school", "community"),
    ("grade", "building"),
    ("major", "unit"),
]
for old, new in _col_renames:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(user_profile)")]
    if old in cols and new not in cols:
        conn.execute(f"ALTER TABLE user_profile RENAME COLUMN {old} TO {new}")
```
同时把 `data/db_core.py` 里 CREATE TABLE 的字段定义、ADD COLUMN 迁移列表、`_resolve_author`/`resolve_author` 里的字段名同步改掉。

### 7.4 完成后
- `seed.py` 的 INSERT 字段名同步改
- `db_user.py` 的 SELECT/INSERT 字段名同步改
- 跑 `python -m pytest -q`，预期 318 passed
- 删掉 `data/*.db` 旧库重跑 seed 验证一遍（或保留 `community_insight.db` 走迁移路径验证）

---

## 8. 关键文件地图

| 文件 | 作用 |
|---|---|
| `app.py` | Streamlit 入口 + 双角色 `st.navigation`（居民 9 页 + 网格员 6 页） |
| `config.py:69` | `DB_PATH = data/community_insight.db` |
| `data/db_core.py` | **schema + 迁移机制**（表改名迁移在这里，`init_db()` 是加迁移的唯一入口） |
| `data/db_sla.py` | **SLA 单一真相源**：`SLA_HOURS={"极急":6,"紧急":24,"普通":72}`，`get_sla_breaches()` / `get_sla_summary()` |
| `data/db_governance.py` | 工单/提案/满意度闭环：`report_issue` / `set_satisfaction` / `update_issue_status` / `_resolve_author` |
| `data/db_user.py` | 用户/角色：`create_user` / `authenticate` / `get_current_user` |
| `agent/engine.py` | `CommunityAgent`（LangChain Agent，16 个工具） |
| `ui/pages/` | 居民端 9 页（home/pulse/issues/voice/transparency/health/notifications/mine/bigscreen） |
| `ui/pages_grid/` | 网格员端 6 页（dashboard/issues_mgmt/proposals_mgmt/content_mgmt/insights/health_mgmt） |
| `ui/theme.py` / `ui/components.py` / `ui/css.py` | 设计系统（暖纸面 + 双品牌色 indigo/violet + 分类色点） |
| `CHANGELOG.md` | 已完成的 P0-P2 + 审查修复日志 |
| `docs/TECHNICAL.md` | 技术文档（任务④要更新） |
| `docs/competition/*.html` | **比赛定稿文档，不碰** |

---

## 9. 运行 / 测试命令

```bash
# 跑测试
python -m pytest -q                      # 全量，约 42s，基线 318 passed
python -m pytest tests/unit/test_tools.py -q   # 单文件

# 跑 app（注意先杀旧进程，端口 8501）
streamlit run app.py

# 手动验证 DB 迁移
python -c "from config import DB_PATH; from data.db_core import init_db; init_db(DB_PATH)"
```

依赖：`pip install -r requirements.txt`（Streamlit + LangChain + openai + 等）。Windows 有 `install.bat` / `start.bat`。

---

## 10. 技术要点与陷阱（接手前必读）

1. **SQLite 连接**：`get_db()` 每次开新连接（可安全嵌套）；`with get_db() as conn:` 用法。
2. **时区**：时间戳用 `CURRENT_TIMESTAMP`（UTC）存储；比较用 `julianday('now')`（UTC 同源）。**不要用 `julianday('now','localtime')`**，否则和 UTC 存储列比较会系统性 +8 小时（曾导致极急工单 6h SLA 被立即误判超时）。
3. **SLA**：一切「逾期/超时」判定都走 `data/db_sla.py`，不要再写散落的 `-7 days` 硬编码。
4. **满意度闭环**：`set_satisfaction(issue_id, value, reopen_on_dissatisfied=True)`；`update_issue_status` 的「已解决」分支要 `satisfaction=''` 重置（否则重开后无法再评价）。
5. **匿名**：`_resolve_author` 优先级 `student_id → school+grade → name → login_id → "匿名"`（字段名任务③改后同步）。
6. **密码盐** `campus-insight-salt-2026` 保留不动（见 §2）。
7. **`data/database.py`** 是一个「聚合 re-export 层」，很多函数从 `db_governance`/`db_knowledge` 等转发，改字段时记得同步它。
8. **`ui/components.py` 的 `CAT_LABEL`** 里有一段「旧校园分类 → 新社区分类」的兼容映射（`教学设备→设施维修`、`校园管理→社区事务` 等），这是**故意保留的兼容 shim**，别当成校园词残留删掉。
9. **`data/db_academic.py` 是校园教务死代码**：提供 `get_courses` / `get_today_courses` / `get_exams` / `get_events` / `get_club_activities`（对应表 `courses` / `exams` / `events` / `club_activities`）。这些函数**没有任何 UI/Agent 层调用者**，只在 `data/database.py` re-export 和 `tests/test_verify_all.py` 模块编译测试里被引用。是前几轮换皮的遗漏（校园教务残留），不影响社区治理主功能。处理时注意：删除要同步删 `db_core.py` 里的 CREATE TABLE、`database.py` 的 re-export、`test_verify_all.py:45` 的模块名引用，否则测试会挂。**注意区分**：`get_community_events`（`db_knowledge.py`，查 `knowledge_base` 表）是活跃函数，别和 `db_academic.py` 的 `get_events`（查 `events` 表）混淆。

---

## 附：迁移聊天记录的方法（供参考）

- 当前会话原始文件：`~/.claude/projects/c--Users-wo-shuo-feng-su-Desktop---/20052d26-fb10-481a-87cf-5ee03cf9fcf0.jsonl`（308MB）
- 持久记忆：同目录 `memory/` + `MEMORY.md`
- 无缝续接：复制 `.jsonl` 到新机器对应 project slug 目录，跑 `claude --resume <session-id>`
- 干净交接：本文件 + `CHANGELOG.md` + 项目代码已足够，不依赖聊天记录
