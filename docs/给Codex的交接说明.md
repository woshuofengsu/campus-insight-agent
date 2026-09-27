# 交给 Codex 用：交接说明 + 硬约束

> 场景：你要让 **Codex**（OpenAI Codex CLI 或 Codex Cloud）参与修改本项目。
> 本项目有 781 项测试、多个口径门禁、**且马上要现场演示**——Codex 不知道这些约定就会踩坏。
> 把这份文件连同 `AGENTS.md` 一起给它（Codex 通常**自动读仓库根目录的 `AGENTS.md`**）。

---

## 一、怎么让 Codex 干活（两条路，按当前时间点选）

| 方式 | 能否读写文件 | 怎么用 | 适合现在吗 |
|---|---|---|---|
| **Codex CLI（本地）** | ✅ 直接读写你的文件夹 | 在项目根目录起 Codex，把仓库根当工作目录 | ✅ **推荐**：改完能立刻跑门禁、能起服务看页面 |
| Codex Cloud | ✅ 但改的是 GitHub 上的分支 | 连你的 GitHub 仓 → 它开 PR → 你 review 后合 | ⚠️ 决赛前慎用：它跑不了本机服务/手机端验证，改动要你本地再验一遍 |

**别同时让两个 AI 改同一批文件**（比如我（DSH）和 Codex 同时改 `api_routes/*.py`）——会互相覆盖。
分工建议：**按目录/文件分**，或者一个改、另一个只评审。

---

## 二、⚠️ 先给它立规矩（这段直接粘给 Codex）

```
你在帮我改一个参赛项目（社区先知 CommunityInsight，基层治理多智能体系统）。
技术栈：Python 3.12 + FastAPI（api_web.py:8000）+ Vue3/Vite（web/）+ SQLite（WAL，schema v48）。

第一步：先读 AGENTS.md（项目约定 + 踩过的坑），再读 docs/spec/dev-log.md 最后 200 行（最近做了什么、为什么）。
然后**先给我改动计划**（改哪些文件、为什么、怎么验证），我确认后再动手。

硬约束（违反会造成演示事故）：
1. 改完必须：`python -m ruff check .` 为 0；`python -m pytest tests/ -q` 必须全绿
   （基线：**781 项可运行 = 780 passed + 1 skipped**；不是 780/781 就是改坏了）。
2. **跑 pytest 前必须停掉 :8000 的服务**（服务在跑时部分 e2e 会因库冲突假失败）；
   反过来，UI 审计（ui_audit / mobile_audit）**需要服务在跑**。两者要求相反。
3. 改了 `web/src` 任何文件 → 必须 `cd web && npm run build`，否则审计和演示看的是旧包。
4. **比赛期不做数据层大重构**：不要改 `data/db_*.py` 的结构；加表/加列只能走
   `data/db_core.py` 的迁移注册表（`_mN_*` + 幂等），**禁止运行时 ALTER**。
5. **不许改对外材料里的数字**（测试数 / 路由数 / 业务表数 / schema 版本）。
   口径门禁：`python scripts/check_claims.py` 必须 3 项全绿。
   当前口径：**781 用例 · 135 路由 · 51 业务表 · schema v48**。
6. 多租户硬规则（v48 真隔离）：租户 = 社区名；**写入必须盖章**（`utils.tenant.stamp_tenant`）；
   **读取必须显式传 `tenant=`**（合法→过滤；空串→空集；不传→抛错）；
   **按 id 直取的详情/操作接口必须过 `api_routes.deps._same_tenant` 闸门**；
   配置走 `data/db_settings.py`（`键@社区` 为社区专属）。有两条静态门禁守这些规则。
7. 安全类校验一律 **fail-closed**；`except` 里**禁止静默吞异常**（有门禁测试会红）。
8. **别删/别重 seed 演示库**（`data/community_insight.db`）：它已经清理过压测残留，是上台用的；
   也**别碰 `.env`、`*.db`、`.shots/db-backup-*.db`**。
9. 领地声明：`docs/competition/上台前清单.md` 与 `演示脚本.md` 里的**数字和步骤**是实测过的，
   要改请先问我（改错会让现场台词和屏幕对不上）。
```

---

## 三、给 Codex 的"这项目现在是什么状态"（省得它瞎猜）

- **完成度**：老年端深化（P3 安全闭环 / P4 健康记录 / 无障碍降级）、多租户真隔离（v48 + 按-id 收口 + 写入侧 + 配置层 + 工具上下文）都已落地并有测试。
- **门禁现状**（2026-09-25 实测）：`ruff` 0 · pytest **780 passed/1 skipped** · `demo_preflight` **9/9** · `ui_audit` **0 HIGH** · `mobile_audit` 全部通过 · `mobile_flow_check` **22/22** · `check_claims` 3/3。
- **演示数据**：海淀工单 176 / 朝阳 2 · 提案 24 · 通知 5 · 知识 62。**数字别乱动**。
- **已知未修复项（重要，别当成"已解决"）**：
  1. **遗留草稿顶替新报修**：`draft_contents` 里的旧报修草稿会被恢复，导致新报修的确认卡片显示
     **上一次的问题**。**规避**：上台前跑 `python scripts/demo_reset.py --apply`（走应用自带
     「取消」路径清草稿）。**根因已缩小**（新草稿未落库 + 每轮恢复覆盖），修复未完成。
  2. **网格员工单全流程的真实路径是 5 步**（展开行 → 审核通过 → 派单(填姓名+电话) → 开始处理 →
     提交处理结果），**不是**脚本原稿写的 2 步。
  3. 真机（iOS Safari / 微信）未验证；手机首连需本人在防火墙弹窗点「允许」。

---

## 四、Codex 改完之后，你这样收尾

```bash
python -m ruff check .                     # 1) 规范
# 2) 停掉 :8000 的服务后：
python -m pytest tests/ -q                 #    全绿（781 项可运行）
python scripts/check_claims.py             #    3 项全绿（数字口径没被改坏）
# 3) 重新起服务（必须 0.0.0.0 手机才能连）：
python -m uvicorn api_web:app --host 0.0.0.0 --port 8000
python scripts/demo_reset.py               #    演示状态体检
python scripts/demo_preflight.py           #    9/9
python scripts/mobile_flow_check.py --base http://<内网IP>:8000   # 22/22
```

提交前确认工作区里**没有** `.env` 与 `*.db`（已在 `.gitignore`，别用 `-f` 强加）。
