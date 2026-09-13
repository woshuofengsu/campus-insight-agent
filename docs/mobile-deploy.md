# 移动端部署方案（Mobile Deploy Plan）

> 面向手机客户端到端落地的方案。目标形态：**手机浏览器直访（H5 响应式）**。
> 部署环境未最终确定（局域网演示 / 公网+域名 / 公网自签三种，见 §5）。
> 演示重点端：**老年端 + 居民端**。
> 状态：§2–§4 代码已落地并 `npm run build` 通过；§5–§7 视部署环境择机执行。

---

## 一、方案选型

| 方案 | 选择 | 迁移成本 | 说明 |
|---|---|---|---|
| H5 响应式 | **采用** | 无 | 现有 Vue3 + Vite + Naive UI 同源架构，零迁移 |
| PWA | 可选 | 0.5 天（手写，不引插件以避免 Vite 8 兼容风险） | 已落地「可安装（类 App 全屏）」；**service worker / 离线未做**（见 §4.3） |
| 微信小程序 | 不采用 | 重写 | 仅当分发限定微信生态时；WXML 不能复用 Vue SFC |
| 原生 App | 不采用 | 重写 | 仅需要蓝牙/NFC/后台定位/推送时 |

结论：主路线 H5 + 可选 PWA。**硬约束：语音识别（webkitSpeechRecognition）要求 HTTPS（或 localhost）**——这直接决定部署环境选择，是移动端第一硬约束。

---

## 二、响应式排版与适配（已落地）

### 2.1 viewport / 安全区基础（`web/index.html`）

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
<meta name="format-detection" content="telephone=no" />
<meta name="theme-color" content="#2D5BFF" />
```

- `viewport-fit=cover`：没有它 iOS 刘海屏 `env(safe-area-inset-*)` 恒为 0，安全区全失效。
- 不加 `maximum-scale=1`/`user-scalable=no`：老年端依赖系统放大手势。iOS 聚焦放大用 §3.1 的输入 16px 方案规避。

### 2.2 断点与全局移动规则（`web/src/mobile.css`，新建）

断点：`≤359`(xs) / `360-427`(sm) / `428-767`(md) / `≥768`(lg 保持现状)。

```css
body {
  -webkit-tap-highlight-color: transparent;
  touch-action: manipulation;       /* 消 300ms 延迟 + 禁双击缩放 */
  overscroll-behavior-y: contain;   /* 防下拉刷新打断长按 SOS */
}
@media (hover: none) and (pointer: coarse) {
  .n-button { min-height: 44px; }
  input, textarea, select, .n-input__input-el { font-size: 16px !important; }
}
```

### 2.3 输入防 iOS 聚焦放大（`mobile.css`）

任何输入控件字号 ≥16px（§2.2 同块），iOS 不会自动放大。

### 2.4 安全区（布局样式写在 `.vue` 内，用 `calc()+env()`，不用全局 `!important` 覆盖 inline）

- `PortalLayout.vue` 居民端：header `padding-top:calc(env(safe-area-inset-top))`、底栏 `padding-bottom:env(safe-area-inset-bottom)`、内容区 `padding-bottom:calc(76px + env(...))`。
- `ElderlyLayout.vue`：头部/导航条 `calc + env`；`.elderly-nav`/`.elderly-page` 的 safe-area 在 `mobile.css` 兜底。

### 2.5 老年端字号策略（review 修正：**不动全局根字号**）

不在 `html` 上放大根字号（避免与老年端大量 px 内联如 `min-height`/`padding` 失衡），改用 `max(rem, px)` 设像素下限：

```css
.elderly-page  { font-size: max(1.25rem, 20px); }
.elderly-title { font-size: max(1.8rem, 28px); }
.elderly-btn   { font-size: max(1.35rem, 21px) !important; min-height: 72px !important; }
```

老年端导航按钮 `min-height` 由 52px 提升到 **64px**（≥60px 下限）。

---

## 三、手机端交互适配（已落地）

### 3.1 软键盘（`web/src/composables/useKeyboard.js`，新建 + `main.js` 挂载）

`focusin` 后 300ms 把聚焦元素 `scrollIntoView({block:'center'})`；visualViewport 兜底 iOS 键盘收起归位。CSS：`html { scroll-padding-bottom:120px; }`。

### 3.2 语音降级 + 语速（`useSpeech.js` + `Agent.vue`）

`onerror` 细分 reason，UI 按 reason 显示大字号引导；**`unsupported` 时会显式降级并自动聚焦文字输入框**（不再静默）：

| reason | 来源 | UI 文案 |
|---|---|---|
| `unsupported` | 环境无 Web Speech | 当前浏览器不支持语音，已为您切换为大字文字输入，请直接打字（并聚焦输入框） |
| `mic-denied` | 权限被拒 | 请点地址栏🔒→麦克风→允许 |
| `https-required` | 非安全上下文 | 语音需 HTTPS，请用 Safari/Chrome 直接打开 |
| `network` | 网络错误 | 网络不稳，请再按一次 |

**M1 语速可调**：`useSpeech.speak(text, volume, rate)` 新增 `rate`（老人档 0.9），老年端首页音量旁加"语速：慢/正常"，选择写入 `user_profile.preferences.speech_rate`；`elderly/home` 返回 `speech_rate`。

### 3.3 长按防误触 + SOS 诚实化（`Home.vue` + `mobile.css`）

SOS 长按按钮加 `data-longpress`，CSS `.elderly-btn,[data-longpress]{-webkit-touch-callout:none}` 防系统菜单。长按 3 秒逻辑已有（`pressStart`/`pressCancel`，3000ms）。

**M 系列合规话术（移动端一致）**：SOS 触发后**不承诺自动连续拨号**——H5 无法系统级连续呼叫。改为"已向已审核紧急联系人发送求助提醒 + 留痕 + 显眼的一键拨打120"；确认弹窗的"将依次呼叫"已改"将向已审核联系人（…）发送求助提醒，用时请点拨打120"。触发后第一句是安抚（`tone.pick("sos")`）。

### 3.4 网格员端手机可看（`PortalLayout.vue`）

<768px 隐藏桌面侧栏（`.grid-desktop-sider`），显示顶栏汉堡 + `n-drawer` 抽屉导航；≥768px 保持桌面侧栏。

### 3.5 横屏提示（`ElderlyLayout.vue` + `mobile.css`）

浏览器无法强制竖屏，用提示层兜底：

```css
@media (orientation: landscape) and (max-height: 500px) {
  .elderly-rotate-mask { display: flex; }
}
```

### 3.6 聊天 UX 与人情味（近期优化，移动端同样受益）

- **AgentChat（居民/网格共用）**：消息区改为**固定高度 `min(380px,55vh)` + `flex column` + 首条 `margin-top:auto`**（短对话贴底、长对话可正常滚动；用 `margin-top:auto` 而非 `justify-content:flex-end`，后者会导致溢出内容滚不上去）；**多智能体执行链默认收起为一行开关**（`🤖 多智能体执行链（N 步）▾ 展开`），点击才展开，避免长链占屏。
- **agent/chat 每用户限流**（N5，60 次/分）：超限返回"您说得有点快，我喘口气，稍等几秒再说"，前端 `warm.js friendlyError` 人话化，不显示裸状态码。
- **老年端人情味**（M1–M4）：`elderly/home` 返回 `greeting/display_name/care_line/speech_rate`，首页显示分时段问候 + 今日一句关怀并语音播报（21:00–8:00 静默不播）；用药提醒加"✅ 我吃了 / ⏰ 10 分钟后再说"（v42 打卡，连续 N 天鼓励）；工单 `status_human` 人话时间轴；办结 24h 回访通知、久未上线提醒网格员问候。

---

## 四、打包与构建（已落地）

### 4.1 构建命令

```powershell
cd web
npm ci
npm run build   # 产物 → web/dist/
npx vite preview --host 0.0.0.0 --port 4173
```

FastAPI（`api_web.py:204-207`）已托管 `web/dist`（`_DIST` + SPA fallback），直接起后端即可访问。

### 4.2 vendor 拆包（已落地，`web/vite.config.js`）

Vite 8（rolldown）要求 `manualChunks` 用**函数形式**。**注意坑**：不要把 vue/vue-router/pinia/axios 硬归到同一个 vendor chunk——会破坏 axios 跨 chunk 的导出绑定，导致真机白屏 `TypeError: e is not a function`（已被真机测试抓出）。正确做法：只把体积最大的 naive-ui 独立拆 chunk，其余交给 Vite 默认聚合。

```js
manualChunks(id) {
  if (id.includes('node_modules')) {
    if (id.includes('naive-ui') || id.includes('@css-render') || id.includes('@juggle') ||
        id.includes('date-fns') || id.includes('evtd') || id.includes('seemly')) return 'naiveui'
  }
  return undefined
},
```

效果：`naiveui-*.js` 1.44MB（独立 chunk，不随业务代码变化，可 `immutable` 一年缓存）/ `index-*.js` ~40KB（vue+router+pinia+axios 默认聚合）。已验证无 `e is not a function` 报错。

### 4.3 PWA（**已完成：可安装**；**未做**：service worker / 离线）

**当前实际落地的东西**（都已在仓库里，可直接访问验证）：

| 文件 | 状态 |
|---|---|
| `web/public/manifest.json` | ✅ 已落地（`name`/`short_name`/`start_url`/`display:standalone`/`theme_color`/3 个图标含 512 maskable/2 个快捷方式） |
| `web/public/icon-192.png`、`icon-512.png` | ✅ 已落地（`scripts/gen_pwa_icons.py` 用 Playwright 渲染 `favicon.svg` 生成，不引新依赖） |
| `web/index.html` | ✅ `<link rel="manifest">` + `viewport-fit=cover` + 4 个 iOS meta + `apple-touch-icon` 用 PNG |

**能做什么**：手机浏览器「添加到主屏幕」后以 standalone 全屏（类 App）运行。
**不能做什么**：**没有 service worker，所以没有离线能力** —— 断网打不开、也没有后台同步。
这是**刻意的取舍**：接诉即办业务强依赖后端实时数据，缓存政策/工单反而可能让人看到过期内容。

> ⚠️ **对外口径（答辩/材料必须一致）**：只说「**可添加到手机主屏幕的类 App 体验**」；
> **任何"脱网也能用"式的能力承诺都不能说**（本机断网时页面打不开）。若被追问，
> 按 `docs/review/复审报告-第九轮-移动端与常开方案.md` Q2 的诚实答法回应。
> 这条口径由 `tests/test_claims_consistency.py::test_pwa_is_installable_but_not_offline` 与
> `scripts/check_claims.py` 的过时表述表共同守着（表里登记了四个禁止出现的短语，写进任何当前状态文档都会红）。

**若将来真要做**（路线图，非比赛期）：手写 app-shell 版 service worker（只缓存 `index.html`/css/js，
**不缓存 `/api`**），约 30 行，仍不引构建插件；同时必须补脱网状态的 UI 提示与缓存版本失效策略。

---

## 五、部署到服务器（三种环境，**待定**）

> 优先级 B > A(降级) > C。老年端语音演示**必须 HTTPS**。

### 5.1 公网 + 域名 + Let's Encrypt（正式）

Certbot 申请证书 → Nginx 静态直出 `dist` + `/api` 反代 8000。关键配置：

```nginx
location /assets/ { root /opt/.../dist; add_header Cache-Control "public, max-age=31536000, immutable"; }
location = /index.html { root /opt/.../dist; add_header Cache-Control "no-cache"; }
location / { root /opt/.../dist; try_files $uri $uri/ /index.html; }
location ~ ^/(api|web)/ { proxy_pass http://127.0.0.1:8000; }
```

### 5.2 局域网演示

```powershell
python -m uvicorn api_web:app --host 0.0.0.0 --port 8000
```

**硬限制**：非 HTTPS 非 localhost 时 iOS/Android 均禁用麦克风与语音识别 → 自动降级文字输入（会显式提示并聚焦输入框）。仅安卓演示机可用 `chrome://flags/#unsafely-treat-insecure-origin-as-secure` 免。iOS 在此环境只演示文字链路。

> **两套姿态**：演示 `Copy-Item .env.demo.example .env.demo`（填真 `DEEPSEEK_API_KEY`）再 `Copy-Item .env.demo .env`（LLM 开关=1：自主协商/政策 RAG/意图兜底）；兜底/断网用 LLM 全 0 的 `.env`（规则全链路不依赖 LLM）。语音与规则链路无需 LLM。前端已构建（`web/dist`），起服务即访问。

### 5.3 公网自签证书（临时）

`openssl req -x509 ...` + uvicorn `--ssl-keyfile/--ssl-certfile`，手机需手动信任，仅 24h 临时演示。

---

## 六、手机端测试清单

> **本节已升级（2026-09-12）**：原来只写了"未执行，需真机"。现在**自动化部分已执行并清零**——
> `scripts/mobile_audit.py` 用真机 UA（iPhone）+ DPR3 + 触屏事件，对三端 **21 个页面**做 7 类专项检查
> （横向溢出 / 热区<44px / **输入框<16px（iOS 聚焦缩放）** / 字号下限 / **被底栏遮挡** / 横屏遮罩 / 大屏降级），
> 当前 **21/21 全部通过**。下面 6.5 是仍需人工真机确认的部分。

### 6.0 自动化审计（每次改前端后必跑）

```powershell
python scripts/mobile_audit.py     # 21 页 × 7 类检查，退出码 0 = 通过
```

| 已自动化检查 | 说明 |
|---|---|
| 横向溢出（320/360/390 宽） | 含未被祖先裁剪的越界元素定位 |
| 触屏热区 <44×44 | 按钮/链接/入口卡/底部标签 |
| **输入框字号 <16px** | iOS 聚焦会整页放大，这是最容易被忽略的真机问题 |
| 字号下限（常规 12 / 老年 20） | 老年端按适老阈值单独卡 |
| **滚动到底部被底栏遮挡** | 用 `elementFromPoint` 真测是否被固定栏盖住 |
| 老年端横屏遮罩 | 横屏必须显示「请竖屏使用」，竖屏必须隐藏 |
| 治理大屏手机降级 | 手机宽度下必须显示「请在电脑/投屏查看」提示层 |

### 6.1 调试通道

`index.html` 加 `?debug=1` 触发 Eruda 控制台（脚本已改同源外部文件，符合 CSP）；Android 用 `chrome://inspect`。

### 6.2 设备 × 浏览器矩阵

iPhone SE/8(375) · iPhone 14/15(390-393) · Pro Max(430) · 小屏安卓(360) · iPad Mini(768)；浏览器：iOS Safari、iOS 微信、Android Chrome、安卓微信、系统浏览器（X5）。

### 6.3 通用测试点

键盘弹出不遮输入框 / 底栏不被 Home Indicator 遮挡 / 无 300ms 延迟 / 下拉不触发刷新 / 系统最大字号档不溢出 / 微信内可登录浏览。

### 6.4 老年端专项（重点）

字号实测 ≥20px / 按钮 ≥60px / 对比度 WCAG AA / 长按 SOS 防系统菜单 / HTTPS 下语音转文字+朗读 / 降级走文字并聚焦输入框 / 横屏提示 / 连点防误触 / 朗读音量与**语速（慢/正常）**可调。

> **新增（M1–M4）必测**：①首页分时段问候 + 今日一句关怀（语音播报；**21:00–8:00 静默不播**，只静默卡片）；②用药"✅ 我吃了 / ⏰ 10 分钟后再说"打卡 + 连续 N 天鼓励（同一天重复 taken 幂等）；③SOS 确认弹窗文案为"发送求助提醒 + 用时请拨120"（非"自动依次呼叫"）；④情绪词先安抚（如"漏水一地，急死了"→先安抚再走报修）。
> **补充必须项（review 三刀之一）**：微信内置浏览器内自动朗读（`speechSynthesis`）可能静默失败——列为必测项，iOS 微信若失败则确保不阻塞、按钮态正确复位。

### 6.5 真机 8 步（自动化测不到的，必须人工）

| # | 步骤 | 通过标准 |
|---|---|---|
| 1 | iPhone Safari + Android Chrome 各一台，三端各走「登录→首页→列表→详情→提交/取消」 | 无白屏、无横向滚动、返回不丢状态 |
| 2 | 任意输入框聚焦 | **页面不自动放大**（输入框字号 ≥16px 的实证） |
| 3 | 滚到列表最底部 | 最后一行/按钮**不被底部标签栏遮住**（自动化已测，真机复验一下） |
| 4 | 老年端横屏 | 弹「请竖屏使用」；转回竖屏自动消失 |
| 5 | 老年端 SOS 长按 3 秒 | 弹确认框并倒计时；**点取消不产生真实求助** |
| 6 | 「添加到主屏幕」→ 打开 | **全屏运行（无地址栏）**、图标正确、主题色为品牌蓝 |
| 7 | 居民端「提交报修」上传图片（拍照 + 相册各一次） | 能选中并提交，图回显正常（后端 5MB 双重校验） |
| 8 | 切系统深色模式 | 三端暖色面板/状态标签/工作台数字都变暗（此前修过，顺带复验） |


---

## 七、安全与合规

| 项 | 要求 |
|---|---|
| 传输 | 生产仅 443，80 强制 301；语音 API 受此约束 |
| JWT 密钥 | **secure-by-default**：未配 `WEB_JWT_SECRET` 且未显式 `DEMO_MODE=true` 直接拒启（近期收紧）；按 `docs/deploy-keys.md` 注入 |
| 演示登录 | 生产（`DEMO_MODE=false`）`/api/web/auth/demo` 中间件层 403，杜绝无密领 JWT；API 文档生产关闭 |
| Token | 现 localStorage；正式版可选迁 httpOnly Cookie |
| 手机号展示 | 真 **AES-256-GCM**（全库 `g1$`，旧密文兼容）+ 前端脱敏（`138****8000`）；列表页抽查无明文 |
| 登录防爆破 | IP 级（5 次/5 分钟）+ **用户名级全局硬限**（防轮换 IP） |
| 上传 | 文件夹白名单 + realpath 归属校验 + 扩展名白名单（图片/PDF，分块读限 5MB）——防路径穿越/恶意文件 |
| 注销 | PIPL 级联匿名化（user_profile + 紧急联系人 + 健康咨询 + 工单 + 提案 的 PII/密文全清） |
| 语音隐私 | 转写文本入库、原始录音 7 天保留；隐私页补一句"语音识别由浏览器厂商处理" |

---

## 八、生产发布检查清单（P1-10，上线前逐条勾选）

| # | 检查项 | 处置 | 状态 |
|---|---|---|---|
| 1 | `?debug=1` 的 Eruda 调试面板 | 已被 CSP `script-src 'self'` 自然拦截（P1-2 附带效果），无需删代码；确认生产不依赖调试 CDN | ✅ |
| 2 | `.env` 不入库 | 已 `gitignore`（含 `.env`/`.env.bak`）；确认 `git status` 无 `.env` | ✅ |
| 3 | `DEMO_MODE` | 生产设置 `false`（关闭演示免登录/演示按钮），仅保留 JWT 门禁 | ⬜ 上线时 |
| 4 | `WEB_JWT_SECRET` / `CRYPTO_KEY` | 生产必配（无则拒绝启动 / 加密不可用），按 `docs/deploy-keys.md` 注入 | ⬜ 上线时 |
| 5 | 安全响应头 | 生产 `curl -I` 核验 5 个头（P1-2） | ⬜ 上线时 |
| 6 | 手机号明文 | 生产前 `SELECT COUNT(*)` 核验全库明文列 = 0；全库密文为 `g1$`（AES-256-GCM） | ⬜ 上线时 |
| 7 | 压测 | `python scripts/benchmark_business.py` 业务混合压测（p50/p95/p99、错误率、QPS）；`benchmark_concurrency.py` 复验 550 并发 | ⬜ 上线时 |
| 8 | 数字一致性 | `python scripts/check_claims.py`（测试数/schema/路由/角色/表数，并交叉核对登录页 meta.js），材料数字与其一致 | ⬜ 每次发材料前 |
| 9 | 数据安全 | `python scripts/audit_phone_encryption.py`（8 张含手机号表明文计数必须为 0） | ⬜ 改数据层后 |
| 10 | UI 无障碍 | `python scripts/ui_audit.py`（全站 34 个路由页 / 54 个页面视口 × 9 类检查，0 违规） | ⬜ 改前端后 |
| 11 | **移动端适配** | `python scripts/mobile_audit.py`（21 页 × 7 类专项：溢出/热区/输入框字号/底栏遮挡/横屏遮罩/大屏降级） | ✅ 当前 21/21 |
| 12 | **PWA 可安装** | `/manifest.json` + `/icon-192.png` + `/icon-512.png` 可访问；「添加到主屏幕」全屏运行 | ✅ 资源就位（真机复验） |

