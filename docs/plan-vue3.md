# FastAPI + Vue3 重构方案（优化版）

> 依据用户提供的《社区服务多智能体系统重构方案》优化：**数据层零改动**是本方案第一原则，
> 因此剔除与现有体系冲突的 SQLModel/Alembic/新表结构，改为直接复用现有 `data/` 层与 SQLite schema。

## 一、核心决策（与原始方案差异）

| 原始方案 | 优化后 | 理由 |
|---|---|---|
| SQLAlchemy 2.0 + SQLModel + Alembic 新表 | **复用现有 SQLite schema（v28）+ data/ 层函数** | 现有 40+ 表、版本迁移、338 测试全保留；工作量 5 天 vs 15 天 |
| 新表 users/work_orders/qa_questions... | 映射现有表（见映射表） | 数据层零改动 |
| passlib[bcrypt] | **复用现有 PBKDF2 哈希（db_core._hash_password）** | 已有哈希与自动迁移逻辑 |
| roles 动态权限表 | **静态角色守卫（resident/grid/elderly）** | 角色已固定，RBAC 在端点层校验 |
| 并入 api.py | **新建 api_web.py 独立 app** | 扣子用的 api.py（API-key）不受影响 |
| 单端口 | api_web.py 单进程 8000（API+静态），api.py 保持 18800（扣子） | 互不干扰 |

## 二、表映射（复用现有）

| 方案新表 | 现有表 |
|---|---|
| users | user_profile |
| work_orders | community_issues |
| proposals | proposals |
| notifications | notices |
| knowledge_base | knowledge_base |
| qa_questions / qa_replies | policy_questions |
| health_consultations / health_replies | health_consults |
| weather_check_tasks | weather_check_tasks |
| medication_reminders | medication_reminders |
| emergency_contacts | emergency_contacts |
| emergency_events | emergency_calls |
| contact_logs | contact_logs |
| audit_logs | activity_log + exception_log |

## 三、后端（api_web.py，P1）

- JWT（PyJWT 或 stdlib hmac 签名，随 requirements 定），`POST /api/web/auth/login` → `{token, role, user_id, name}`
- Bearer 中间件解析 `request.state.user`；老年端免登录用 `elder_id` 参数 + 绑定校验（复用 db_user 绑定逻辑）
- 统一响应 `{success, data, error, code, message}`；错误码 0/1001/1002/1003/1004/1005/2001
- 端点清单：auth / 报修状态机全操作 / 提案闭环 / 通知 / 天气 / 政策 / 健康 / 老年端 SOS+用药+联系人 / 附件上传（复用 utils/uploads.py）
- 附件上传 `POST /api/web/upload` → 返回相对路径

## 四、前端（P2-P5）

- Vue3 + Vite + Vue Router + Pinia + Axios + Naive UI
- 新视觉：主色社区绿 #2E7D32 + 紧急橙 #FF9800（按原始方案）
- 三端路由 `/resident/*`、`/grid/*`、`/elderly/*`、`/screen` 治理大屏
- 老年端：Web Speech 语音（60 秒/转写确认/音量）、10 秒确认超时、20px+ 大字、底部红色 SOS
- 核心闭环约 18 页（优先演示路径，不 1:1 复刻）

## 五、部署

- `npm run build` → dist/，api_web.py 静态托管 + history fallback
- Dockerfile：python:3.11-slim + dist/ + uvicorn api_web:app:8000
- 数据库文件挂载卷持久化

## 六、测试

- 后端：pytest + httpx，每个端点正/异常用例（auth/权限/状态机/特殊规则）
- 端到端：demo_script.py 模拟 6 条完整演示流程
- 前端：浏览器冒烟（登录 → 三端闭环）

## 七、里程碑

| 阶段 | 内容 | 验证 |
|---|---|---|
| P1 | api_web.py：JWT + 7 模块端点 + pytest | pytest 全绿 + curl 冒烟 |
| P2 | Vue3 骨架 + 三端路由 + 登录 + 主题 | 登录 → 路由通 |
| P3 | 居民端 9 页 | 报修/提案/政策闭环 |
| P4 | 网格员端 8 页 | 工单审核→派单→反馈 |
| P5 | 老年端 6 页 | 语音/大字/SOS |
| P6 | 联调 + Docker + 端到端 | 单进程可演示 |

## 八、风险

- 时间不足 → Streamlit 保留备用，P1 完成即可回退
- 语音准确率 → Web Speech + 文本兜底
- SQLite 并发 → 演示规模足够，预留迁移

## 九、开发规范

- 每阶段一个分支，`[P1] feat: ...` 提交
- .env 管理敏感配置，不入库
