# 社区先知 CommunityInsight — 技术亮点

> 面向评委的 5 分钟技术深度速览。建议配合演示视频阅读。

---

## 1. OODA 五阶段治理引擎

```
用户输入 → Observe（环境感知）→ Orient（意图定位）→ Decide（工具调用）
         → Act（LLM 执行）→ Reflect（反思纠错）→ 用户回复
```

不是简单的"用户问 → LLM 答"。每个 `run()` 调用执行完整五阶段：

| 阶段 | 做什么 | 为什么需要 |
|------|--------|-----------|
| **Observe** | 扫描 DB：待处理工单数、天气预警、热点类别 | 让 LLM 在回复前"知道社区正在发生什么" |
| **Orient** | Persona Router 关键词+语义匹配→选角色 | 同一句话"助餐点怎么样"对分析师和对观察员含义不同 |
| **Decide** | 触发词→工具映射表，强制调用 | 反幻觉：用户说"社区脉搏"不能自己编，必须调 `get_community_pulse` |
| **Act** | LangChain AgentExecutor + DeepSeek | 支持 14 个工具的函数调用 |
| **Reflect** | 7 项后处理检查：清理 thinking tag、闭环追踪、安全网 | LLM 的输出是草稿，Reflect 把它变成可靠回复 |

**代码位置**：[agent/engine.py](../agent/engine.py)（559 行，编排层。具体阶段分散在独立模块中）

---

## 2. 三层回退链（永不白屏）

```
CommunityAgent (LLM) → OfflineAgent (规则) → graceful_fallback (静态)
     ↓ 失败              ↓ 失败                  ↓ 永远可用
  DeepSeek API        规则引擎+真实 tool        DB 直查+硬编码回复
```

- **Layer 1 — CommunityAgent**：DeepSeek + LangChain AgentExecutor，3 次重试 + 指数退避
- **Layer 2 — OfflineAgent**：无 LLM 依赖。Persona Router（关键词匹配）→ 调用真实 `tool.invoke()` → 模板化为自然语言。90% 的体验接近 LLM
- **Layer 3 — graceful_fallback**：DB 直查。按意图分类（脉搏/天气/接诉/提案/统计）返回硬编码但数据驱动的回复

**代码位置**：[agent/engine.py](../agent/engine.py)（Layer 1 编排）、[agent/offline_agent.py](../agent/offline_agent.py)（Layer 2）、[agent/fallback.py](../agent/fallback.py)（Layer 3）

---

## 3. Anti-Hallucination 安全网

LLM 的典型幻觉：用户说"3号楼灯坏了"，LLM 回复"✅ 已为你生成工单 #42"——但实际上没有调用 `report_issue`，数据库中不存在 #42。

安全网机制（`enforce_tool_call`）：

1. 检查 `intermediate_steps`：`report_issue` 被调用了没？返回值是成功还是报错？
2. 如果没调用或调用失败 + 用户输入匹配 `detect_persona("接诉助手")`
3. → **强制调用** `report_issue.invoke()`，用关键词分类（不依赖 LLM）
4. 用真实 tool 返回值**替换** LLM 的幻觉回复

```
LLM 编造 "工单 #42 已创建" → 安全网检测到 report_issue 没被调用
→ 强制 tool.invoke() → 拿到真实工单号 #17 → 替换回复
```

**代码位置**：[agent/enforce.py](../agent/enforce.py)

---

## 4. Persona Router — 零 LLM 意图识别

不调 API，纯关键词 + 正则 + 优先级规则，毫秒级完成：

| Persona | 触发信号 | 置信度 |
|---------|---------|:--:|
| 🔧 接诉助手 | "坏了""漏水""故障""不亮"等 60+ 关键词 | high/medium/low |
| 🌊 社区观察员 | "社区脉搏""最近发生""动态" | high/medium/low |
| 📊 数据分析师 | "统计""数据""多少""占比" | high/medium/low |
| 🗳️ 议事顾问 | "提案""建议""我觉得应该""能不能" | high/medium/low |

**亮点规则**：
- **状态查询重定向**："修好了吗"+"我上报的" → 从接诉重定向到数据分析师（查工单，不创建）
- **语义回退**：关键词无匹配时，正则捕获 `<地点>+<问题描述>` 模式
- **多人格混合**：复合查询（如"统计设施维修 + 创建提案"）触发多人格 blending

**代码位置**：[agent/prompt.py](../agent/prompt.py)（`detect_persona` 函数）

---

## 5. 治理审计引擎

跨 4 张表（community_issues / proposals / discussion_topics / activity_log）的综合健康评分：

| 维度 | 权重 | 评分方法 |
|------|:--:|------|
| 工单管理 | 40% | 解决率基准 80%（ISO 37120），紧急工单扣 5 分/件（上限 25），积压扣 3 分/件（上限 20） |
| 提案参与 | 35% | 未回复提案扣 8 分/件（上限 40），采纳率 ≥50% 加分 |
| 公民参与 | 25% | 活跃上报者 <3 人扣 30 分，总参与 <10 人次扣 20 分 |
| 热点检测 | 附加 | ≥5 件同类问题自动标记为热点类别 |

输出：综合评分 (0-100) + A/B/C/D 等级 + 趋势箭头 + Top 3 优先行动建议。

**代码位置**：[agent/governance_audit.py](../agent/governance_audit.py)

---

## 6. 双主题 Token 设计系统

```python
# ui/theme.py
TOKEN_LIGHT = {"bg": "#ffffff", "text": "#1a1a1a", "accent": "#2563eb", ...}
TOKEN_DARK  = {"bg": "#0f0f14", "text": "#e8e8ed", "accent": "#3b82f6", ...}

TOKEN = _ThemeAwareToken(TOKEN_LIGHT, TOKEN_DARK)
# 所有组件用 TOKEN["bg"] 而非硬编码颜色
# 用户切换 → st.session_state → TOKEN 自动切换引用
```

40+ 语义化 token（`bg`, `text`, `accent`, `danger`, `warning`, `success`, `card_bg`, `border`, `radius_*` 等），全局 CSS 用 f-string 注入，所有页面和组件共享同一套设计语言。不需要 CSS 变量——Streamlit 不支持——用 Python 层代理实现等效效果。

**代码位置**：[ui/theme.py](../ui/theme.py)

---

## 7. 测试策略

```
        ┌──────┐
        │ E2E  │  7 场景（居民接诉/脉搏/提案/闭环/审计/降级/多轮）
       ┌┴──────┴┐
       │ 集成   │  21 用例（CRUD/通知/活动/并发）
      ┌┴────────┴┐
      │  单元    │  224 用例（tools/prompt/helpers/offline/audit）
     └───────────┘
      冒烟: 17 全模块编译+DB往返+路由验证
      关键路径: 40 用例 (persona/路由/安全网/感知)
```

**总计 328 测试，CI 自动化运行。** 覆盖每个 `@tool` 函数的边界输入、Persona Router 的全量路由规则、安全网的正确拦截/放行、空数据库的治理审计不崩溃。

**代码位置**：[tests/](../tests/)

---

## 8. 工程化实践

| 实践 | 实现 |
|------|------|
| **异常处理** | agent/data/tools 层所有 `except` 均有 `_log.debug(exc_info=True)` |
| **DB 连接** | SQLite WAL 模式 + context manager (`with get_db() as conn`) |
| **会话管理** | Streamlit session_state + 版本戳自动重建 agent |
| **工具发现** | `tools/__init__.py` 用 `pkgutil.iter_modules` 自动扫描，无需手动注册 |
| **配置** | `.env` 文件 + `config.py`，支持离线模式 |
| **幂等性** | `seed_all()` 检查已有数据量，不重复插入 |
| **代码组织** | engine.py(559行) → 4 个独立模块 + 1 个编排层 |

---

## 9. 演进说明与命名对照（诚实披露）

本项目最初定位为「校园治理」，后演进为「海淀小区社区治理」（接诉即办）。为保证数据链路与工具调用链不被破坏，演进过程中做了**全量命名迁移**，并在 `init_db()` 里内置了幂等的旧库迁移（表改名 `campus_issues → community_issues`、字段改名、角色值 `student/teacher → resident/grid`）。

| 层 | 旧命名（校园） | 新命名（社区） |
|----|--------------|--------------|
| 项目/类 | `CampusInsight` / `CampusAgent` | `CommunityInsight` / `CommunityAgent` |
| 数据库 | `campus_insight.db` | `community_insight.db` |
| 表 | `campus_issues` | `community_issues` |
| 角色值 | `student` / `teacher` | `resident` / `grid` |
| 用户字段 | `student_id` / `school` / `grade` / `major` | `resident_id` / `community` / `building` / `unit` |
| 工具 | `get_campus_pulse` / `get_school_policy` | `get_community_pulse` / `get_community_policy` |
| 路由 | `/api/campus-pulse` | `/api/community-pulse` |
| 主题 key | `_campus_theme` / `campus` | `_community_theme` / `community` |

> 兼容性保证：迁移在 `init_db()` 中幂等执行（`ALTER TABLE … RENAME` / `RENAME COLUMN` / `UPDATE role`），旧数据库无需删库重灌即可平滑升级，且 `data/seed.py` 只增不删，绝不破坏既有居民数据。密码盐、SLA 口径、满意度闭环等业务逻辑不随命名迁移而改变。

---

## 为什么这套架构适合社区治理

1. **LLM 不可靠** → 三层回退保证服务永远在线
2. **LLM 会幻觉** → 安全网在工具调用层面兜底
3. **社区问题有模式** → OODA 的 Observe 阶段让 Agent 在回复前就知道"最近3号楼接诉多"
4. **居民和网格员需求不同** → Persona Router 把同一句话导向不同工具
5. **治理需要量化** → 审计引擎把跨表数据变成可比较的分数和等级
