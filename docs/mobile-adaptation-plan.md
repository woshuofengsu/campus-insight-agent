# 手机移动端适配方案（最终版补强 · 可直接执行）

> 版本：v1.1（2026-09-12）　适用范围：社区先知 CommunityInsight 三端（居民/网格/老年）
> **执行状态：P0 已完成（21/21 全过）、P1 已完成（PWA + 大屏降级 + 横屏补强 + dvh）**；P2 为可选打磨，不阻塞答辩。
> 执行记录见 `docs/spec/dev-log.md` 第四十节。

---

## 0. 执行结果速览（2026-09-12 实跑）

| 项 | 结果 |
|---|---|
| 移动端审计（`scripts/mobile_audit.py`，真机 UA/DPR3/触屏） | **21 页 × 7 类检查全部通过** |
| 审计发现的真问题 | ① 老年端「紧急联系人」手机号 16.8px（低于适老 20px）→ 已修；② 审计脚本自身把全屏 fixed 背景误判为底栏（假阳性，已修判据） |
| PWA | `manifest.json` + `icon-192/512.png` + 4 个全屏 meta 全部就位并被服务（HTTP 200） |
| 大屏手机降级 | `/screen` 在 <900px 显示「请在电脑/投屏查看」+ 返回/仍要查看按钮（纳入审计） |
| 老年端横屏遮罩 | 触发条件补强为「触屏 + 横屏 + ≤1024px」，横屏专项审计通过 |
| iOS 高度跳变 | `.n-layout` 增 `min-height:100dvh`（不支持则回退 100vh） |
| 回归 | `ui_audit` 全站 54 页视口仍 0 违规；前端构建通过 |

---

## 1. 现状盘点（基线与执行前）

> 原计划保留在此，便于日后回溯「改之前是什么样」。

已具备（不需要重做）：响应式断点 767/359/427、`touch-action: manipulation`、
`overscroll-behavior-y: contain`、粗指针热区 ≥44px + 输入框 ≥16px、老年端安全区与大字、
网格端手机抽屉导航、键盘弹起归位、语音降级引导、`prefers-reduced-motion` + 页面不可见暂停、
深链刷新修复、`ui_audit` 全站 54 页视口客观审计。

---

## 0. 结论先行

| 维度 | 现状 | 目标 |
|---|---|---|
| 响应式排版 | ✅ 已有（断点 767/359/427、安全区、适老热区） | 保持 |
| 移动端专项验证 | ⚠️ 缺（`ui_audit` 只查视觉/无障碍，不查 iOS 输入缩放、底栏遮挡、横屏遮罩） | 新增 `mobile_audit.py` 门禁 |
| PWA「添加到主屏幕」 | ❌ 无 `manifest.json`、无全屏 meta | 补齐（低成本高观感） |
| 大屏 `/screen` 在手机上 | ❌ 未适配（桌面场景） | 明确降级提示 |
| 现场兜底 | ✅ 已有录屏 + reduced-motion | 保持 |

---

## 1. 现状盘点（基于代码事实，不凭印象）

已具备（不需要重做，只列出作为基线）：

| # | 能力 | 依据 |
|---|---|---|
| 1 | 视口配置 `viewport-fit=cover` + `theme-color` + `apple-touch-icon` | `web/index.html` |
| 2 | 消除 300ms 点击延迟 / 禁双击缩放 | `web/src/mobile.css` `touch-action: manipulation` |
| 3 | 防下拉刷新打断老年 SOS 长按 | `mobile.css` `overscroll-behavior-y: contain` |
| 4 | 触屏热区 ≥44px + 输入框字号 ≥16px（防 iOS 聚焦缩放） | `mobile.css` `@media (hover:none) and (pointer:coarse)` |
| 5 | 老年端安全区 + 大字（≥20px / 按钮 ≥72px） | `style.css` 适老段 + `ElderlyLayout.vue` `calc()+env()` |
| 6 | 老年端横屏「请竖屏使用」遮罩 | `mobile.css` `.elderly-rotate-mask`（`orientation:landscape` 且 `max-height:500px`） |
| 7 | 网格员端手机改用抽屉导航 | `PortalLayout.vue` `n-drawer` + 顶栏 ☰ |
| 8 | 键盘弹起自动滚动到输入框 + 视口归位 | `web/src/composables/useKeyboard.js` |
| 9 | 语音 Web Speech API，不支持时给大字降级引导 | `elderly/Agent.vue`、`useSpeech.js` |
| 10 | 动效尊重系统 `prefers-reduced-motion` + 页面不可见暂停 | `style.css` + `main.js` |
| 11 | 深链/刷新不再被弹回首页（此前修的移动端硬伤） | `App.vue` `await router.isReady()` |
| 12 | 移动/投影/桌面多视口 UI 客观审计 | `scripts/ui_audit.py`（全站 54 页视口含 320/390/1366/1440/1920） |

**结论**：响应式与适老的基础已经扎实，剩下的差距集中在「专项验证」「PWA」「大屏降级」三块。

---

## 2. 差距与风险点（诚实清单）

| # | 差距 / 风险 | 影响 | 严重度 |
|---|---|---|---|
| G1 | **无移动端专项审计**：iOS 输入框 <16px 会聚焦缩放、底部标签栏遮挡末屏内容、横屏遮罩是否真的触发——`ui_audit` 都不测 | 真机上一眼可见的体验 bug，但测试测不出 | 🔴 P0 |
| G2 | **无 `manifest.json`** + 无 `mobile-web-app-capable`/`apple-mobile-web-app-*` | 「添加到主屏幕」不是全屏应用，体验像网页 | 🟡 P1 |
| G3 | `/screen` 治理大屏在手机上是桌面布局，8 卡被压扁或横向滚 | 演示时若手机误开大屏会显得"没适配" | 🟡 P1 |
| G4 | 老年横屏遮罩触发条件偏窄（`landscape` 且 `max-height:500px`），部分横屏机型不触发 | 横屏老年端排版错乱无提示 | 🟡 P1 |
| G5 | 网格员端宽表格（工单列表多列）在 390px 下只能横向滚动，无"表格横向滚动"提示 | 可用但不够顺滑 | 🟢 P2 |
| G6 | 附件上传在移动端（拍照/相册）未专项验证 | 提交报修图片可能失败 | 🟡 P1（真机验证项） |
| G7 | `100vh` 在移动浏览器地址栏收起/展开时的高度跳变（iOS 经典问题） | 底栏可能被地址栏盖住 | 🟡 P1 |

---

## 3. 目标与验收标准（每条可度量）

验收口径统一：**自动化用 `scripts/mobile_audit.py`（退出码 0），人工用下面的真机清单**。

| 目标 | 验收标准 |
|---|---|
| T1 移动端 0 违规 | `mobile_audit.py` 覆盖 ≥20 页（三端），横向溢出/热区/输入框/遮挡/字号/JS 报错全 0，横屏遮罩在老年端正确显示 |
| T2 PWA 完整体验 | 手机「添加到主屏幕」后：独立图标 + 全屏无地址栏 + 主题色正确；Chrome DevTools「Application」无 PWA 报错 |
| T3 大屏降级 | 手机打开 `/screen` 显示「请在桌面或横屏查看」提示（不渲染挤压布局）；桌面/大屏不受影响 |
| T4 真机通过 | iPhone + Android 各一台，走完第八节 8 步清单，0 阻断问题 |

---

## 4. 分阶段执行

### P0 —— 移动端专项验证（先测后改，约 0.5 天）

**步骤 1：跑通移动端审计**

`scripts/mobile_audit.py` 已写好（iPhone UA / DPR3 / 触屏，覆盖居民 8 页 + 网格 2 页 + 老年 9 页 + 横屏专项），本轮运行被打断，**下一步先跑**：

```powershell
python scripts/mobile_audit.py        # 退出码 0 = 全过；否则逐条修
```

它检查 6 类 `ui_audit` 不查的东西：
1. 横向溢出（含未被祖先裁剪的越界元素）
2. 触屏热区 <44×44
3. **输入框字号 <16px（iOS 聚焦缩放）**
4. 字号下限（常规 12 / 老年 20）
5. **滚动到底部后被固定底栏遮挡的元素**（`elementFromPoint` 真测）
6. 老年端横屏遮罩是否在正确方向触发

**步骤 2：按报错逐条修，每修一处重跑一次**（改动只在前端）

预期会命中的修复点（若命中则按此改）：
- 输入框 <16px → 给对应 `n-input` 加 `font-size:16px`（移动端媒体查询内统一兜底，最稳）。
- 底栏遮挡 → 内容容器 `padding-bottom` 已是 `calc(76px + env(safe-area-inset-bottom))`，若仍遮挡则把 76px 改为「底栏实测高度 + 8px」。
- 横屏遮罩不触发 → 见 P1-G4。

**步骤 3：把 `mobile_audit.py` 接进门禁**
- 在 `demo_preflight.py` 增加第 10 项「移动端适配」（`--fast` 跳过，完整模式跑，或改为独立命令 + 写进 `docs/mobile-deploy.md` 发布清单）。**决策点**：`ui_audit` 已 10 分钟，`mobile_audit` 再 ~5 分钟，完整模式会到 15 分钟；建议**独立命令**（不进 preflight），写进发布清单即可，避免答辩前自检变慢。

### P1 —— PWA 与完整体验（答辩前，约 1 天）

**G2 补齐 PWA**（改动最小、观感最大）

1. 新建 `web/public/manifest.json`：
```json
{
  "name": "社区先知 CommunityInsight",
  "short_name": "社区先知",
  "start_url": "/login",
  "display": "standalone",
  "background_color": "#EEF3FF",
  "theme_color": "#2D5BFF",
  "icons": [
    { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" },
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```
2. 由现有 `favicon.svg` 生成 PNG（192/512）。**无设计工具就用 Playwright 渲染截图转 PNG，或写一个 10 行的 PIL 脚本**；没有 PIL 就只保留 SVG + 加 192 PNG（maskable 用纯色底 + 图标）。
3. `index.html` 补 meta：
```html
<link rel="manifest" href="/manifest.json" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="default" />
<meta name="apple-mobile-web-app-title" content="社区先知" />
```
4. 验证：Chrome DevTools → Application → Manifest 无报错、图标可识别；真机「添加到主屏幕」全屏打开。

**G7 高度跳变（100vh → dvh/svh）**

`style.css` 给根容器加现代单位兜底（旧浏览器回退 100vh）：
```css
.app-shell { min-height: 100vh; min-height: 100dvh; }
```
并确认底部标签栏 `position: fixed; bottom: 0` 在 iOS 地址栏收起时不被遮挡（用 `env(safe-area-inset-bottom)` 已是必要条件）。

**G3 大屏移动端降级**

`Screen.vue` 加一个 `<768px` 的降级层：显示「治理大屏请在桌面浏览器或横屏查看」+ 一个「返回」按钮；桌面与 ≥768px 不渲染该层。**不改大屏本体逻辑**。

**G4 老年横屏遮罩补强**

`mobile.css` 把触发条件从「`landscape` 且 `max-height:500px`」放宽到「`landscape` 且 `max-width:1024px` 且 `pointer:coarse`」（即"小屏触屏设备的横屏"），避免部分机型漏触发；竖屏与桌面不受影响。

**G6 附件上传移动端验证（真机）**

真机清单里加一步：居民端「提交报修」→ 上传图片（拍照 + 相册各一次）→ 确认能提交且图能回显。后端已有 5MB 双重校验，**预计只验证不改代码**；若真机报错再修。

### P2 —— 可选打磨（不阻塞答辩，按余力）

| 项 | 做法 | 价值 |
|---|---|---|
| 网格表格横滚提示 | 工单列表外层加「← 左右滑动看更多列 →」提示（仅 <768px） | 体验 |
| 老年 SOS 触觉反馈 | 长按确认时 `navigator.vibrate?.(80)` | 适老亮点 |
| 底部标签过渡 | 激活态小条已有 `tab-pop`，可加 0.15s 背景过渡 | 观感 |
| Service Worker / 离线能力 | **未做**：PWA 目前只做到「可添加到主屏幕 + standalone 全屏」，**对外不得宣称离线能力**（口径由门禁守着）；真离线要手写 app-shell SW，工程量大，放 P2 | 技术分 |

---

## 5. 验证门禁整合

```powershell
# 自动化（改完必跑）
cd web && npm run build                         # 必须打印 ✓ built in（别只看末尾几行）
python -m pytest tests/ -q                      # 576 passed / 1 skipped（可运行 577）
ruff check .                                    # 0
python scripts/ui_audit.py                      # 全站 54 页视口 × 9 类 0 违规
python scripts/mobile_audit.py                  # ≥20 页移动端 0 违规（P0 后启用）
python scripts/demo_acceptance.py               # 11/11 端到端
python scripts/demo_preflight.py                # 9/9

# 人工真机清单（写进 docs/mobile-deploy.md 第八节）
# ① iPhone Safari + Android Chrome 各一台
# ② 三端各走一遍：登录→首页→列表→详情→提交/取消
# ③ 老年端：横屏弹「请竖屏使用」、SOS 长按 3 秒弹确认（取消不真发）
# ④ 输入框聚焦：页面不自动放大（字号 ≥16px 的验证）
# ⑤ 滚到列表底部：最后一行不被底部标签栏遮挡
# ⑥ 「添加到主屏幕」：全屏打开、图标/主题色正确
# ⑦ 切飞行模式刷新：已打开页面不白屏（Service Worker 若做了 P2 才测离线）
# ⑧ 暗色模式：三端暖色面板/状态标签都变暗（此前已修，顺带复验）
```

---

## 6. 风险与降级

| 风险 | 降级 |
|---|---|
| 现场设备带不动动效 | 已有 `prefers-reduced-motion` 全站可关 + 页面不可见暂停 + 7 段录屏兜底（含属地化两社区对比） |
| 真机拿不到（只有模拟器/仿真） | Playwright 设备仿真（iPhone UA/DPR3/触屏）已覆盖 95% 问题；至少争取一台真机复验第八节清单 |
| 键盘遮挡输入框 | 已有 `useKeyboard.js`（focusin 滚动 + visualViewport 归位）；真机清单第 ④ 步验证 |
| iOS 地址栏高度跳变 | G7 用 `100dvh/svh` 兜底；若仍跳，底栏改 `position: sticky` 备选 |
| 图标 PNG 生成缺工具 | 只保留 SVG（manifest `purpose:any`），iOS 部分版本对 SVG 图标支持不稳，则补一个 192 PNG（用浏览器截图或在线工具，不引入新依赖） |

---

## 7. 落地文件清单（改哪些、不动哪些）

| 文件 | 动作 | 内容 |
|---|---|---|
| `scripts/mobile_audit.py` | 已建（未提交） | 先跑通，P0 用它逐条修 |
| `web/public/manifest.json` | 新建 | PWA 清单 |
| `web/public/icon-192.png` / `icon-512.png` | 新建 | 图标（由 favicon.svg 派生） |
| `web/index.html` | 改 | 加 manifest + 全屏 meta |
| `web/src/style.css` | 改 | `100dvh` 兜底；老年横屏遮罩触发条件放宽；移动端输入框 16px 兜底 |
| `web/src/views/Screen.vue` | 改 | <768px 降级提示层（不动本体逻辑） |
| `docs/mobile-deploy.md` | 改 | 第八节发布清单补 mobile_audit + 真机 8 步 |
| `scripts/demo_preflight.py` | 可选改 | 是否加第 10 项（建议不加，保持自检快；改文档引用即可） |
| 后端 `api_routes/**`、`data/**`、`agent/**` | **不动** | 移动端适配是纯前端，避免引入回归 |

---

## 8. 一句话总结（给执行者）

移动端基础已扎实，剩下的是「**先跑 `mobile_audit.py` 找出真问题 → 逐个修 → 补 PWA 三件套（manifest + 图标 + 全屏 meta）→ 大屏手机降级 → 真机 8 步复验**」。所有改动纯前端、每条可度量、改完跑第六节门禁；风险点（动效/键盘/高度跳变）都已有兜底或在方案里给出降级。
