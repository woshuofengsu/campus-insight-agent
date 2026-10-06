# PostgreSQL 迁移盘点与计划（阶段 1 的前置）

> 这份文件回答一个问题：**"可演进 PostgreSQL"到底要改多少？**
> 结论先写：**不是"改个连接串"**。本机实测（`python scripts/audit_sql_dialect.py`）：

| 项 | 数值 |
|---|---|
| **高置信度命中**（字符串里出现就一定得改） | **141 处** |
| 低置信度命中（静态判断可能误报，需人工确认） | 211 处 |
| 涉及文件 | **42 个** |

> 本机环境事实（2026-09-29 探测）：**没有 Docker、没有 psql、没有 psycopg**。
> 所以"真实迁移演练"目前**跑不了**——按项目纪律，这只能写成
> 「**已编写脚本与计划，真实演练尚未执行**」，**不能写"具备可靠迁移/回滚能力"**。

---

## 1. 141 处高置信度命中，按模式分组

| # | 模式 | 处数 | Postgres 写法 |
|---|---|---:|---|
| 1 | `datetime('now', '-N days')` | 65 | `NOW() - INTERVAL 'N days'` |
| 2 | `date('now'[, 'localtime', '+N days'])` | 33 | `CURRENT_DATE` / `(NOW() AT TIME ZONE 'Asia/Shanghai')::date` |
| 3 | `julianday(a) - julianday(b)` | 21 | `EXTRACT(EPOCH FROM (a - b))` |
| 4 | `PRAGMA ...`（多数在迁移链里查列是否存在） | 14 | 查 `information_schema.columns` |
| 5 | `INSERT OR IGNORE` / `INSERT OR REPLACE` | 8 | `ON CONFLICT DO NOTHING` / `ON CONFLICT (...) DO UPDATE` |

低置信度两组（需人工看）：`?` 占位符 188 处（→ `%s`）、`date(列)` 23 处（→ `CAST(col AS date)`）。

> **好消息**：141 处其实只有 **5 种改写**，且高度集中在时间函数上。
> 这意味着"收敛到少数辅助函数"是可行的，不需要逐处硬改。

## 2. 迁移计划（四步，每步都可独立验证）

### 第 1 步：把方言**收敛到一处**（不改行为，先改结构）

新增 `data/_sql_dialect.py`，提供纯函数生成 SQL 片段，例如：

```python
def now_minus_days(days: int) -> str        # SQLite: datetime('now','-3 days') ｜ PG: NOW() - INTERVAL '3 days'
def today() -> str                          # SQLite: date('now','localtime')   ｜ PG: (NOW() AT TIME ZONE :tz)::date
def hours_between(a: str, b: str) -> str    # SQLite: (julianday(a)-julianday(b))*24 ｜ PG: EXTRACT(EPOCH FROM (a-b))/3600
def upsert(table, cols, keys) -> str        # ON CONFLICT 变体
def column_exists_sql(table, col) -> str    # PRAGMA vs information_schema
```

然后 141 处逐个替换为调用这些函数。**这一步在 SQLite 上必须完全不变行为**（全量测试是回归网）。
验收：`pytest tests/ -q` 全绿 + `audit_sql_dialect.py` 高置信度归零（低置信度由占位符决定，见第 3 步）。

### 第 2 步：连接层抽象（`DB_BACKEND=sqlite|postgres`）

`data/db_core.get_db()` 现在是 `sqlite3` 直连。要加一层薄封装：

- 连接建立（`sqlite3.connect` vs `psycopg.connect`）；
- **占位符风格**（`?` vs `%s`）——188 处，**这一步最机械但最容易漏**；
- `with get_db() as conn` 的语义（提交/回滚/异常传播）必须两边一致；
- 事务与 `PRAGMA journal_mode=WAL`（仅 SQLite）；
- 迁移链 `_mN_` 的 DDL 也要能两边执行（`_add_column` 的 PRAGMA 检查 → 第 1 步的 `column_exists_sql`）。

验收：同一套测试用 `DB_BACKEND=sqlite` 与 `DB_BACKEND=postgres` **各跑一遍全绿**才算真迁移。

### 第 3 步：真实迁移演练（**必须在 staging 上真跑，不能只写脚本**）

| 步骤 | 内容 | 验收 |
|---|---|---|
| ① 空库初始化 | 建空库 → 跑全部 `_mN_` 迁移 → 查 schema 版本 / 表 / 索引 / 外键 | schema = v53、表数与 SQLite 侧一致 |
| ② 最小初始化 | **只写**社区配置 / 服务时间 / 管理员 / 网格员 / 必要政策与联系人 | **不写任何历史演示工单** |
| ③ 双向验证 | 表数、关键表行数、外键、**加密字段仍为密文且可解密**、租户字段完整、幂等键有效、通知队列有效、审计记录有效 | 逐项脚本化输出 |
| ④ 回滚演练 | 迁移失败 → 恢复备份 → 回滚代码版本 → 重启 → 检查工单与账号仍可用 | **真实跑过一次**并记录耗时 |

> ⚠️ 纪律：④ 没真跑过之前，材料里**只能**写"已编写回滚脚本，回滚演练尚未完成"。
> 写"具备可靠回滚能力"是编造。

### 第 4 步：备份与恢复（独立于 PG，SQLite 阶段也该有）

- 每日备份（库 + 附件目录）+ **保留周期**；
- **恢复演练脚本**（这条比备份本身更重要：没演练过的备份等于没有备份）；
- 恢复耗时写进试点指标（`社区试点方案-v1.md` §3.3 已列）。

## 4. 生产库初始化的红线（不可协商）

| 红线 | 理由 |
|---|---|
| **生产库从空库初始化** | 本机演示库里的工单**全部**是演示/验证脚本产生的（v53 `is_demo` 已能证明：面板显示"已标记演示 6 条 / 未标记 335 条"，未标记的那些同样来自脚本） |
| **绝不复制 `data/community_insight.db`** | 把 300+ 条演示工单迁进生产，等于第一天就在生产里跑假数据 |
| **演示账号不得作正式账号** | `demo_*` 是免密/固定密码，进生产就是安全事故 |
| **`is_demo=1` 不得进入生产统计** | 试点指标的分母必须是真实工单 |
| **staging 与 production 完全隔离**（库 / 密钥 / 账号） | 混用会把试运行数据算成试点数据 |

## 5. 与试点排期的关系（诚实版）

阶段 1 里，**"可部署骨架"与"PG 迁移"是两块**，风险完全不同：

| 块 | 内容 | 本地可验证吗 | 风险 |
|---|---|---|---|
| **1A 部署骨架** | Docker Compose、反代与 HTTPS、备份/恢复脚本、密钥管理、健康检查、日志、部署手册 | ✅ 大部分可以（备份/恢复在 SQLite 上就能演练） | 低 |
| **1B PG 迁移** | 第 1–3 步（收敛方言 → 连接层 → 真实演练） | ❌ **本机没有 Docker/PG，跑不了真实演练** | 高（141+188 处改写） |

**建议顺序：先做 1A（不阻塞、可立即验证），再做 1B**；
1B 需要一个能跑 Postgres 的环境（云主机或本机装 Docker），否则只能停在"脚本 + 计划"。

> 顺带一句实话：单社区 30–50 人试点，**SQLite(WAL) + 每日备份 + 恢复演练**在容量上完全够用。
> PG 的真正价值在**账号权限分离、多进程并发、跨机扩展**。
> 如果试点时间很紧，"先上云 + 备份演练、PG 按本计划推进"是可接受的中间态；
> 但**不能**既不换 PG、也不做备份演练。
