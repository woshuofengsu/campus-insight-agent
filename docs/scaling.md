# 多租户与 PostgreSQL 演进路径（scaling）

> 现状：单社区演示部署，SQLite（`data/community_insight.db`）。本文档说明如何演进到
> **多社区（多租户）** 与 **PostgreSQL**，作为「规模化阶段」的可执行路线图。
> 改动点落到文件/函数/迁移编号，供新成员照做。

---

## 1. 当前架构约束（为什么需要演进）

| 组件 | 现状 | 规模化瓶颈 |
|---|---|---|
| 存储 | SQLite 单文件（`db_core.get_connection`，line 855） | 单写锁；并发写上限；多实例无法共享 |
| 会话（业务） | `db_agent.agent_sessions`（v31，落库） | 已落库，多实例安全 |
| 会话（黑板） | `agent/blackboard.py` 内存 dict（`shared_data`/`messages`/`locks`） | **单进程**，README 已标注；多实例需换 Redis |
| 会话缓存 | `api_routes/agent.py::_agent_orchs` 内存 dict（已有 LRU 上限 P1-1） | 单进程内存态 |
| 租户隔离 | `user_profile.community`（db_core line 649）字段已存在，但**未作为过滤键** | 多社区数据会串 |

---

## 2. 演进路线（分三步，可独立落地）

### 2.1 第一步：租户过滤打全（低风险，先行）

目标：所有业务查询带 `community` 条件，避免多社区数据串。

涉及文件：`data/db_repair.py`、`data/db_proposal.py`、`data/db_notice.py`、`data/db_health_content.py`、
`data/db_policy.py`、`data/db_elderly_care.py`。

做法：在每个 `get_*`/`list_*` 查询的 `WHERE` 加入 `community = ?`，社区号从登录用户 `user_profile.community`
带出，注入到路由层 `_user(request)` 上下文中。

关键函数（以报修为例）：
```python
# data/db_repair.py::get_issues 增加参数 community: str = ""
def get_issues(..., community: str = ""):
    q = "SELECT * FROM community_issues WHERE 1=1"
    if community:
        q += " AND community = ?"
        args.append(community)
    ...
```

**注意**：`community_issues` 表目前**无 `community` 列**（`community_issues` 与 `user_profile.community` 不同——
只 `user_profile` 有）。需在迁移中给业务表补 `community` 列（见 2.3 的 `_m39`）。

### 2.2 第二步：黑板与会话缓存去内存化（中风险）

目标：支持多进程/多实例（Web 也上多 worker）。

涉及：`agent/blackboard.py`（`shared_data`/`messages`/`locks` 换 Redis）、`api_routes/agent.py::_agent_orchs`（换共享会话）。

做法：给 `Blackboard` 加一个后端抽象：
```python
# agent/blackboard.py —— 新增存储后端（策略模式）
class BlackboardStore:
    """内存/Redis 可切换的键值 + 消息 + 锁后端。默认内存。"""
    def get(self, key): ...
    def set(self, key, value, lock=False): ...
    def lock(self, key): / def unlock(self, key): ...
    def post_message(self, target, msg): / def get_messages(self, target): ...
```

`Blackboard.__init__(session_id, store=None)`，`store` 缺省 `MemoryStore()`；生产传 `RedisStore()`。
`Orchestrator` 无需改动。

### 2.3 第三步：SQLite → PostgreSQL（规模化）

目标：多写并发、多实例共享、非 SQLite 的 `INTEGER PRIMARY KEY AUTOINCREMENT` 等友好。

涉及：`data/db_core.py::get_connection`（line 855）/`get_db`（line 868）是**唯一 SQLite 入口**，
只需替换这两处为 psycopg2/SQLAlchemy 连接即可，`data/` 各模块仍用 `get_db()`。

关键改动：
```python
# data/db_core.py 增加一个连接抽象（保持 get_db 签名不变）
def get_connection():
    if os.getenv("DB_BACKEND", "sqlite") == "postgres":
        import psycopg2  # 或 sqlalchemy
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.row_factory = psycopg2.extras.RealDictCursor
        return conn
    # ... 现有 sqlite 逻辑
```

**SQLite 特有语法需替换**（逐处）：
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`（PostgreSQL）
- `PRAGMA journal_mode=WAL` → 删除（PG 自带）
- `datetime('now', ...)` → `now() - interval '...'`
- `LIMIT ?` 参数化在 PG 用 `%s` 占位符

---

## 3. 配套 schema 迁移（v39 起）

在 `data/db_core.py` 的 `post` 迁移列表追加（沿用 `_add_column` 幂等机制）：

```python
def _m39_multitenant_community(conn):
    """v39：业务表补 community 列（多租户过滤用）。
    community_issues/proposals/notices/health_consults/policy_questions 等统一加 community 列。"""
    for table in ["community_issues", "proposals", "notices", "health_consults",
                  "policy_questions", "medication_reminders", "emergency_contacts"]:
        _add_column(conn, table, "community", "community TEXT DEFAULT ''")
```

在 `post` 列表末尾追加 `(39, "multitenant_community", _m39_multitenant_community)`。

---

## 4. 迁移顺序与验证

1. **备份**：`Copy-Item data\community_insight.db data\community_insight.db.bak`。
2. **改 `db_core.py`** 加 `_m39` 并注册。
3. **跑全量**：`python -m pytest -q`（应全绿，新增 `community` 列为空串不影响旧逻辑）。
4. **验证无明文手机号**：`python scripts/migrate_issue_phone_encryption.py`（幂等，确认仍 0 明文）。
5. **多租户验证**：
   ```sql
   -- 造两个社区数据后，按 community 过滤应互不可见
   SELECT COUNT(*) FROM community_issues WHERE community='A社区';
   SELECT COUNT(*) FROM community_issues WHERE community='B社区';
   ```

---

## 5. 结论

- **短期（答辩前）**：不必做多租户/PG。**单社区 SQLite 已足够演示**，重点是把「演进路径」讲清楚。
- **中期（试点）**：先做 2.1 租户过滤 + `_m39`，保证多社区不串。
- **长期（商用）**：2.2 换 Redis + 2.3 换 PG，配合 `docs/deploy-https.md` 的 HTTPS 部署。

> 一切集群化/多租户改造都以「会话已落库（v31/v35）+ 黑板可换后端」为前提，这已在架构上预留，
> 是支撑「可落地」说法的关键证据。
