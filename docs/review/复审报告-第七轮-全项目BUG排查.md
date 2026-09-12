# 复审报告 · 第七轮：全项目 BUG 与优化点大排查

> 方法：独立复跑全部客观门禁 + 后端/数据/安全/前端/工程分域静态审计 + 生产库直查 + 对照前后端字段绑定。**不采信提交说明，所有结论可复现。**
> 日期：2026-09-12　HEAD=`b29426c`（处理外部评审 B1/B2/B3 + ui_audit 第 9 类）
> 项目：社区先知 CommunityInsight（FastAPI:8000 + Vue3/NaiveUI 三端 + SQLite v45 + 9 声明式 Agent）

---

## 一、总体结论与评分

**竞赛语境 9.3（维持，修掉本轮 P2 后到 9.4）；生产语境 7.6。** 工程成熟度在学生项目里属上游：564 测试全绿、26 页客观 UI 审计 0 硬残缺/0 JS 报错、鉴权与安全头成体系、上一轮我提的 B1 不仅修了还把"残缺文本扫描"和 1366/320 视口固化进了自动门禁（这是很成熟的闭环意识）。本轮**没有发现 P1 致命缺陷**，但抓到 **1 个 P2 数据安全一致性缺口（提案手机号明文，实证 181 条）** 和一串 P3 接线/纪律问题。整体不是"能不能用"的问题，而是"最后 5% 的一致性收口"。

### 客观门禁复跑（独立）
| 项 | 结果 |
|---|---|
| pytest | **564 passed, 1 skipped, 3 deselected**（564+1+3=568，与 check_claims 静态用例数一致），259s |
| ruff | 已提交代码 0；**未提交的 demo_record.py 有 1 个 B023**（见 E） |
| 前端构建 | dist 新鲜（产物 19:05 > 最新源码 18:48） |
| ui_audit | **26 页**（新增 1366 投影档 + 320 小屏档）：0 硬残缺 / 0 jsErrors / 0 横向溢出 / 0 高对比问题；3 处软项（2 处工具误报 + 1 处真问题，见 C） |
| schema / 路由 / Agent / 表 | v45 / 130 / 9 / 50 |
| warning | 109→144，增量主要是第三方 httpx/TestClient 弃用（随测试数增多），自有代码仅剩 13 处 `datetime.utcnow`（见 F） |

---

## 二、本轮新发现 BUG（按严重度，含文件/行/修法/测试）

### 🔴 P2-A　提案手机号明文落库，v36 加密迁移漏掉了 proposals 表（最实质）
- **现象（生产库直查实证）**：`SELECT … FROM proposals WHERE length(reporter_phone)>0` → **181 条全是明文**（如 id21 王阿姨 13800138000）。
- **根因**：v36 给 `user_profile / emergency_contacts / community_issues(reporter/agent/assignee) / health_consults / emergency_calls` 都加了 `*_phone_enc` 列，**唯独没给 proposals 加**；`data/db_proposal.py` 只 `_validate_phone` + 导出 `mask_phone`，**全程不调 `_enc_phone`**，INSERT（db_proposal.py:164/175-178/270-273）把明文直接写进 `reporter_phone`/`agent_phone`。
- **为什么是问题**：直接违反项目自己的硬约定"手机号必须加密落库"；展示/导出虽脱敏，但**库文件一旦被拷走就是 181 条裸号**，和工单表的加密标准不一致——评委若问"是不是所有手机号都加密了"，现在不能点头。
- **修法（走正规迁移，别裸 ALTER）**：
  1. `data/db_core.py` 新增 `_m46_proposal_phone_enc`：`proposals` 加 `reporter_phone_enc TEXT DEFAULT ''`、`agent_phone_enc TEXT DEFAULT ''`，并在 post 列表注册；迁移里把存量 181 条 `_enc_phone(明文)` 回填 enc 列、再把明文列置 `''`（照搬 v36 对 issues 的做法）。
  2. `db_proposal.py` 写路径：明文列写 `''`、真号进 enc（对照 `db_repair.py:180-191`）；读路径 `_dec_phone(enc, 明文兜底)`；导出继续 `mask_phone`。
  3. 测试：提交一条提案后断言 `reporter_phone=''` 且 `reporter_phone_enc` 以 `g1$` 前缀开头、解密回原值；再断言全库 `SELECT COUNT(*) FROM proposals WHERE length(reporter_phone)>0 = 0`。

### 🟡 P3-B　老年首页"最近联系"是永远不显示的死绑定
- **现象**：`web/src/views/elderly/Home.vue` 有 `v-if="home?.latest_contact"` 的"最近联系：…"块，但后端 `api_routes/elderly.py:130-141` 的 home payload **只返回 community_phone，没有 latest_contact** → 该块恒不渲染。
- **关键**：后端其实有现成函数 `data/db_elderly_care.py:1262 get_latest_contact_call(uid)`，是**接了一半忘了在端点里塞进去**（和上轮 B1 同类：前后端字段没对齐）。
- **修法**：elderly.py home() 的返回 dict 补一行，把最近联系格式化成人文案，例如
  `"latest_contact": _fmt_contact(get_latest_contact_call(uid))`（拿不到给 None，前端 v-if 自然不显示）；加 1 条测试：造一条联系记录后 home 接口 `latest_contact` 非空。

### 🟡 P3-C　老年首页用药角标 12px，低于适老 20px 字号下限
- **现象**：ui_audit 在 elderly-home 三个变体都报 `span.n-base-slot-machine-current-number__inner px=12 need=20`。来源是 Home.vue:245 的 `<n-badge :value="home.due_medications">`——Naive 角标内部用 slot-machine 渲染数字，默认 12px，老人看不清。
- **修法（二选一）**：① CSS 放大：`.elderly-page .n-badge .n-badge-sup{font-size:max(1rem,16px);min-width:24px;height:24px}`；② 更适老的做法是**不依赖小角标**，把数量直接写进大按钮文字（"用药提醒 2"），与大字体系一致。改完 ui_audit fonts 项应清零。

### 🟡 P3-D　运行时裸 ALTER 补列，schema 漂移（违反"别直接 ALTER"约定）
- `data/db_notice.py:95 _ensure_columns()` 运行时给 notices 补 `scope_target_json`，而 **db_core 正规建表里没有这列**（pinned_at 有）→ 纯靠 db_core 建新库会缺列，直到该函数跑到才补上。
- `data/db_proposal.py:89` 同样有运行时 `ALTER TABLE proposals ADD COLUMN`；`agent/rag.py:78-82` 惰性补 kb_embeddings 三列（此前已记录、可接受）。
- **修法**：借 P2-A 的 m46 一次性收口——把 scope_target_json、proposals 缺列、kb_embeddings 三列全部写进 db_core 正规建表 + 迁移注册，删除运行时 `_ensure_columns`/裸 ALTER，让"全新建库"和"存量升级"走同一条路径。

### 🟡 P3-E　新工具 demo_record.py 未提交且 ruff 报错
- `git status`：`?? scripts/demo_record.py`、`M .gitignore` 都没提交；`ruff check` 在 **demo_record.py:206 报 B023（闭包未绑定循环变量 shots）**。这文件是答辩录屏工具（真浏览器录 webm+关键帧，只读不真发 SOS），思路很好，但**一旦提交，CI 的 ruff 门禁会直接红**。
- **修法**：把 206 行对 `shots` 的捕获改成默认参数绑定或在循环外构造（list.append 运行时虽不出错，但按 ruff 要求消除晚绑定），本地 `ruff check .` 归零后连同 .gitignore 一起提交。

### ⚪ P3-F　13 处 `datetime.utcnow()` 残留（告警收尾）
自有代码弃用告警已从 113→13，剩：db_proposal.py×4(100/454/742/754)、db_weather.py×2(14/93)、db_elderly_care.py×2(746/1138)、db_repair.py:513、db_health_content.py:79、api_routes/issues.py:69、api_routes/proposals.py:141。统一换 `datetime.now(timezone.utc)` 即可清零自有告警（剩下的是第三方 httpx 弃用，升级 starlette/httpx 后消失，不阻塞）。

### ⚪ P3-G　插件入口 api.py 把原始异常文本回给客户端
`api.py`（扣子插件入口 :18800，非主服务）多处 `raise HTTPException(500, detail=str(e))`（191/266/305/323/365），可能把内部文件路径/SQL 片段透出；**主服务 api_web 无此问题**。改为统一"服务繁忙，请稍后再试" + 服务端 `logger.exception` 落 trace_id。

### ⚪ nit　ui_audit 自身一处误报
residueSoft 把"A · B"中的中点判成"尾部分隔符"（登录"基层治理 ·"、grid-qa"办事指引 ·"），实为正常分隔符被元素文本边界截断。**app 不用改，改工具**：尾部分隔符正则排除 `·`/`·`（中点后允许接换行+文字即视为合法）。

---

## 三、上轮问题修复核验（b29426c，逐个独立验证）

| 上轮项 | 核验方式 | 结论 |
|---|---|---|
| B1 老年天气缺最高温 | 直调 `get_simplified_weather()` → `{temp:27, temp_high:27, temp_low:17}` 三键齐全；26 页 residue 硬扫描全空 | ✅ 真修好 |
| B2 老年按钮 4 字折行 | `.elderly-btn{min-height:72px}` 整排等高，参差消除；但**未加 nowrap，4 字仍折两行**（可接受，想单行再加 nowrap） | 🟡 基本解决 |
| B3 老年暗色意图 | ElderlyLayout 导航改 `var(--primary-light,#E8EDFF)` 跟主题令牌 | ✅ 已跟主题 |
| ui_audit 第 9 类 | 已加 undefined/NaN/[object Object]/{{}}/`°~°`/Infinity 硬扫描 + 空括号/尾分隔软扫描，且**补了我建议的 1366 投影档和 320 小屏档** | ✅ 超预期 |

---

## 四、分域扫描结论（没问题的地方也给结论，不反复折腾）

- **鉴权/越权**：中间件对 `/api/web/*` 统一验 JWT，无有效 token 在进路由前直接 401；公开白名单最小（login/health/根/favicon）；`_user`=已登录、`_require_role`=指定角色两级清晰；JWT secure-by-default（无密钥且非显式 DEMO_MODE 直接拒绝启动）；演示登录生产模式中间件层 403。**无未授权写洞。**
- **注入**：所有 f-string SQL 拼的都是**内部标识符/白名单字段**（db_notice 先 `if k in allowed` 过滤再拼 `k=?`，值全参数化），未发现用户输入进 SQL 结构。**无注入。**
- **加密**：工单新数据写法正确（明文列写空串、真号进 `*_enc`、读时解密+旧数据兜底）；缺口仅提案表（P2-A）。上传 5MB 在路由和工具层双重校验。
- **安全头/链路**：CSP、HSTS、X-Frame-Options=DENY、nosniff、Referrer-Policy、Permissions-Policy 齐全；traceId 经 contextvar 透传、data 层落库、响应头回传——**原 P2"无 request_id 串联"其实已闭环。**
- **多智能体**：Blackboard 带锁、history 封顶 500；全仓无可变默认参陷阱；角色工具白名单闭集；LLM 闭集输出/默认关特性开关维持。
- **前端卫生**：0 处 console.log/debugger；26 页 0 运行时 JS 报错；v-for 均有 key；CountUp/ready 门控维持；dist 为最新构建。
- **已知可接受债（不阻塞比赛）**：进程内状态/限流多 worker 需 Redis、SQLite→PG、KB `SELECT *` 全表（现 59 行无风险）——docs/scaling.md 已有路径，按既定来。

---

## 五、优先改进清单

### 立即做（半天内，堵唯一实质洞 + 红线）
1. **P2-A 提案手机号加密**：m46 加列+存量 181 条回填加密+清空明文+写读路径+1 条断言测试（对照工单实现，约 1-2h）。
2. **P3-E**：修 demo_record.py:206 B023，`ruff check .` 归零后提交（别让 CI 在你答辩前变红）。
3. **P3-B**：elderly home 补 latest_contact，让"最近联系"真正显示。

### 答辩前（1-2 天，打磨一致性）
4. **P3-C**：老年角标字号放大或把数量并进大按钮文字，ui_audit fonts 清零。
5. **P3-D**：m46 顺带把运行时裸 ALTER 收回正规迁移，全新建库与存量升级同路径。
6. **P3-F**：清掉 13 处 utcnow，自有告警归零，截图写进"工程质量"页。
7. 录屏工具 demo_record 跑一遍产出三端 15s webm 作为现场设备兜底。

### 答辩后/长远（生产化）
8. P3-G 插件入口异常文案脱敏；推进 Redis/PG（scaling.md 三步）；KB 检索随规模加分页边界。

---

## 六、本轮针对性答辩问答（ canonical 20 问见《终审全面评价》，这里只补本轮新发现会被追问的）

1. **"你说手机号全加密，我看库里怎么还有明文？"** → 诚实答：工单/用户/联系人/咨询/紧急呼叫已 AES-256-GCM 加密，本轮自查发现**提案表是 v36 的遗漏、181 条仍明文，已列 m46 迁移做存量回填加密并清空明文列**（现场可展示迁移和"明文计数=0"的测试）。主动暴露+给出闭环，比被查出来强。
2. **"怎么证明前端不会出现字段对不上的花屏（undefined/空值拼接）？"** → 展示 ui_audit 第 9 类：26 页渲染后扫 undefined/NaN/`°~°`/未渲染模板/[object Object]，0 命中；并讲这正是上轮抓出老年天气缺最高温后沉淀成的自动门禁。
3. **"为什么既有规则又有 LLM，到底哪里是 AI？"** → 规则保确定性和成本，LLM 只在意图兜底/政策生成/协商演示，且闭集输出+引用强制+默认关闭；用 42 条金标 hit@1 100% vs 纯词法 85.7% 说话。
4. **"SQL 里为什么有 f-string？是不是注入？"** → 拼的是白名单内的列名/内部标识符，用户值永远走 `?` 参数；可现场指 `if k in allowed`。
5. **"SQLite 能扛并发吗？"** → WAL + busy_timeout 5000 + synchronous NORMAL，压测 550 并发零失败；多 worker/规模化路径在 scaling.md（Redis→PG），比赛期零代码改动。
6. **"适老是不是只把字号调大？"** → 不是：字号用 max(rem,px) 保底、热区≥72px、只保留 SOS 呼吸动效、reduced-motion 全站可关、角标这类细节也用客观审计卡 20px 下限。
7. **"测试数为什么和用例数对不上？"** → 564 passed +1 skipped +3 deselected =568 静态用例，口径一致，可现场跑。
8. **"九个子 Agent 是不是过度设计？"** → 生产可合并到 5-6 个（通知/天气偏薄已自认），但九角色对应基层真实岗位分工，竞赛讲职责闭环，保留；黑板+仲裁+校验是可演示的真协作流。

---

## 七、最终结论

方向正确、工程扎实，已经过七轮迭代收敛到"一致性收口"阶段，**没有伤筋动骨的架构或安全问题**。本轮唯一需要认真对待的是 **P2-A 提案手机号明文**——它不影响演示（展示层已脱敏），但触碰项目自己立的"加密落库"红线，且修复成本很低（一个 m46 迁移），务必在答辩前清掉，让"敏感数据全加密"这句话没有例外。其余 P3 都是半天内可收的小尾巴。**建议：按"立即做"3 项收口后冻结功能、不再加新特性，全力转答辩脚本与真实数据叙事。**

### 附：本轮取证清单
- 生产库：proposals 明文 181 条（直查）；加密列枚举（db_core v36 五表有 enc、proposals 无）
- 函数实测：get_simplified_weather → temp/temp_high/temp_low 齐全
- 门禁：pytest 564+1+3=568；ruff 仅 demo_record B023；ui_audit 26 页 JSON（0 residue/jsErrors，elderly fonts 12px×3 变体，中点软误报）
- 代码定位：db_proposal.py:164/175/270（明文写）、elderly.py:130-141（缺 latest_contact）、elderly/Home.vue:245（n-badge）、db_notice.py:95-104（运行时 ALTER）、api_web.py:131-171（鉴权中间件）、deps.py:87-95（两级鉴权）、api.py:191 等（异常文案）
