# pilot-v1 基线（阶段 0，2026-09-29）

> **用途**：试点版本的起跑线。阶段 2（服务台线）完成后会在本分支打 **`pilot-v1` 标签**并冻结界面，
> 真实老人观察**只在 `pilot-v1` 上进行**，观察期间不改界面。
>
> 上一个冻结版本是 `elderly-observation-v1`（**保留不动**，它的界面就是服务台线之前的老年端）。

---

## 1. 分支与版本

| 项 | 值 |
|---|---|
| 工作分支 | `pilot-v1`（从 `fix/WS0-WS10-audit` 的 `1bfe88f` 拉出） |
| 保留的既有标签 | `elderly-observation-v1` · `submit-2026-09-29` |
| 冻结标签（阶段 2 末尾再打） | `pilot-v1`（**尚未创建**） |
| schema 版本 | **v53**（版本化迁移 **52** 条） |

## 2. 结构事实（`python scripts/check_claims.py` 现场可复算）

| 项 | 值 |
|---|---|
| HTTP 路由 | 153 |
| Agent 角色（声明式） | 9 |
| 业务表 | 53 |
| UI 审计覆盖面 | 37 个路由页 / 58 个视口 |
| 移动端审计 | 31 页 |

## 3. 质量门禁基线（全部实测，工作区冻结下跑）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 单元/集成测试 | `python -m pytest tests/ -q` | 可运行 **1112** / **1111 通过 + 1 跳过** |
| 代码规范 | `python -m ruff check .` | 0 |
| 对外数字口径 | `python scripts/check_claims.py` | 全绿（结构数字 10 类判据 + 测试数 + 过时表述） |
| 浏览器旅程 | `python scripts/journey_check.py` | **63/63** |
| 治理侧两项对账 | `python scripts/grid_gov_check.py` | **29/29** |
| 手机流程 | `python scripts/mobile_flow_check.py` | **40/40** |
| 桌面彩排（含故障注入） | `python scripts/demo_flow_check.py --mutate --handoff --faults` | **26/26** |
| UI 客观审计 | `python scripts/ui_audit.py` | **0 HIGH** |
| 移动端审计 | `python scripts/mobile_audit.py` | 全部通过 |
| 演示前自检 | `python scripts/demo_preflight.py --fast` | **9/9** |
| 真实模型链路（平时跳过） | `pytest -m integration_api` · `RUN_LLM_EVAL=1 pytest tests/test_llm_eval.py` | **3/3** · **3/3** |

## 4. 评测指纹（判断评测数字是否可比）

| 项 | 值 |
|---|---|
| 语料 | 62 条 · 指纹 **`f613b0a9ddda7811`**（`freeze_eval_corpus.py --check` 已核对一致） |
| 对抗集 | 60 条 · 指纹 **`8331be2b9afbca38`** |
| 检索 | 阈值路径 48/48 = 100% · RRF 路径 48/48 = 100% · 纯词法 91.7% |
| 拒答 | 无依据 8/8 不自动回答 · 控制组 8/8 能答上 |
| 对抗集未达标（如实登记） | 3 条：公积金贷款额度 / 医保卡补办 / 一个人在家怕摔跤 |

## 5. 素材位置

| 类别 | 位置 | 是否进 git |
|---|---|---|
| 录屏 | `.recordings/`（7 段 webm） | ❌ 需单独打包 |
| 审计明细 JSON | `.shots/ui-audit.json` · `mobile-audit.json` | ❌ |
| 前端构建产物 | `web/dist/` | ❌（审计/演示前必须 `npm run build`） |

## 6. 阶段 0 之后要做的事（顺序与门槛）

| 阶段 | 内容 | 门槛 |
|---|---|---|
| 1A | 部署骨架：Compose / 反代与 HTTPS / 备份与恢复演练 / 密钥 / 健康检查 / 日志 / 部署手册 | 空库可启动 · **备份可恢复** · staging 可跑完整流程 · 不写生产库 |
| 1B | PostgreSQL 迁移（**141 处高置信度 SQL 方言**，见 `PG迁移盘点与计划.md`） | 同一套测试 `DB_BACKEND=sqlite\|postgres` 各跑一遍全绿 · **真实迁移 + 回滚演练各一次** |
| 2 | 服务台线：`/service-desk` 独立入口 · `submission_channel` · reporter/operator 分离 · `station_id` · 事项编号 · 工作人员查询 · 会话清理 | 跨社区拒绝 · 共享设备清理 · 重复提交不建两单 |
| 3 | 冻结验证：跑齐上面 §3 全部门禁 + staging 隔离 + 服务台专项 | 全绿后才允许观察 |
| 4 | **打 `pilot-v1` 标签 → 真实老人观察（5–8 位 / 4 任务 / 7 指标）** | 观察期间**不改界面** |

## 7. 变更登记（每次改动前填一行）

| 日期 | 改了什么 | 影响哪个门禁 | 观察是否受影响 | 回退点 |
|---|---|---|---|---|
| 2026-09-29 | 阶段 0：拉 `pilot-v1` 分支 + 记基线 | 无（只加文档） | 否 | `1bfe88f` |
| 2026-09-29 | 新增 `scripts/audit_sql_dialect.py`（PG 迁移前置盘点） | 新增审计工具（不进 pytest） | 否 | 删该脚本 |

---

## 8. 未验证项（本基线时点，如实登记）

- **真机走查**：Android Chrome / iOS Safari / 微信内置浏览器 —— 未开展（支持件已备：`/device-check.html` + `docs/eval/真机验证记录.md`）
- **真实老人观察**：0 位（方案要求 5–8 位）
- **真实社区试点**：未开展（方案见 `docs/eval/社区试点方案-v1.md`）
- **PostgreSQL 真实迁移与回滚演练**：未执行（本机无 Docker/psql/psycopg；计划见 `PG迁移盘点与计划.md`）
- **备份恢复演练**：未执行
