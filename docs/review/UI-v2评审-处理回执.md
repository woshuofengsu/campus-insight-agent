# 《UI-v2 评审与 BUG 核查》处理回执

> 对应评审文档：`docs/review/UI-v2评审与BUG核查.md`（HEAD=`288c704` 时点）
> 处理日期：2026-09-12　本轮回执对应的提交见文末
> 原则：**评审提的每条都处理，处理不了的说明原因**；每条都附可复现证据。

## 一、立即做（3 项）—— 全部闭环

### 🔴 B1 老年端首页天气最高温缺失（已修，含回归测试）

| 项 | 内容 |
|---|---|
| 根因 | `data/db_weather.py::get_simplified_weather()` 返回 `temp`(=最高温)/`temp_low`，**没有 `temp_high` 键**；而 `web/src/views/elderly/Home.vue:200`（大字显示）与 `:86`（语音播报文案）都读 `temp_high` → 渲染成「晴 17°~°」、播报漏最高温 |
| 影响面 | 仅老年端首页（居民端走完整天气接口、网格天气概览走 `get_community_weather_overview`，都含 `temp_high`）——**偏偏是适老旗舰页**，评审判断准确 |
| 修法 | 返回 dict 补 `"temp_high": d.get("temp_high") if d else None`（保留 `temp` 兼容既有引用，`tone.care_line` 等仍可用） |
| 回归测试 | `tests/test_elderly.py::TestElderlyWeatherPayload` 2 项：① 断言 `temp_high`/`temp_low` 两键同时存在且非空、`temp == temp_high`（兼容契约）；② 端到端断言拼出的温度串不含 `°~°`/`None` 且 `temp_high ≥ temp_low` |
| 实机验证 | `ui_audit` 第 9 类检查在**未修复的现状**下抓到 `[温度缺失占位] «晴 17°~°» div.panel-hi`；修复 + 重启服务后 26 个页面 `residue=0` |

### 🟡 B2 老年端大按钮 4 字标签折行、同排参差（已修）

- 为什么不能直接用 `white-space:nowrap`：3 列在 390px 视口下每格只有 ~109px，而「图标 32px + 4 个汉字 80px + 内边距 28px」≈ 140px —— **nowrap 必然重新撑破容器**（这正是上一轮 153px 横向溢出的成因），所以采用评审给的第二种方案「等高对齐」，并顺带把结构统一：
  - 每格改成**图标在上、文字在下**（`.elderly-grid-3 .elderly-btn .n-button__content { flex-direction:column }`），图标缩到 1.6rem、内边距收到 4px；
  - 徽标包裹层与按钮都 `height:100%`，同排严格等高。
- 实测（真实浏览器量测）：390px 与 320px 两种视口下，**6 个按钮全部 109×79（320px 下 134×79），同排高度集合 `{79}` 唯一 → 严格等高**；图标行 + 文字行结构一致，4 字标签单行放下（若折行高度会涨到 ~100px，实测没有）。

### 🟡 B3「老年端暗色首页」截图其实是浅色（已查明：不是应用 bug，是我的截图工具 bug）

- 根因：`scripts/shots.py` 的暗色截图靠**点击「🌙 夜间」按钮**，而老年端布局（`ElderlyLayout.vue`）**根本没有这个按钮** → 点击超时被 `except` 吞掉，于是拍下了浅色页却命名成 `-dark`。评审看到的现象完全属实，感谢抓这个——它会让「我已验证暗色」的说法变成假证据。
- 修法：改为 `context.add_init_script("localStorage.setItem('ci_theme','dark')")` 预置主题（与 `ui_audit` 同一套），并加**断言式自检**：截图前检查 `document.body.className` 是否含 `dark`，不含就报错，杜绝再出现「假 dark 图」。
- **回答评审的问题**：老年端**不是刻意保持亮色**，它跟随主题（`ci_theme`），且暗色下的面板**已全部验证达标**（`ui_audit` 老年首页/用药/通知 3 个暗色页 `contrast=0`；`ElderlyLayout` 原先写死浅底导致暗色 1.16:1 的 bug 也已在上一轮修掉）。若你认为「适老产品就该锁定亮色」以免老人困惑，这是一行改法（在 `ElderlyLayout` 挂载时强制 light），说一声我就加——目前没有强锁，因为跟随系统主题对视力敏感的老人反而更友好。

## 二、答辩前建议（按你的 4/5/6/7 条）

| # | 建议 | 状态 |
|---|---|---|
| 4 | **给 ui_audit 加第 9 类「渲染后残缺文本扫描」** | ✅ **已落地，并且就是用未修复的现状验证过它能抓 B1**（见下） |
| 5 | 三端各录 15s 动效屏录 | ⏳ 待你确认设备后我出录屏脚本/分镜（`scripts/demo_*.py` 已有三个可复用场景） |
| 6 | 补 1366×768 投影分辨率核对 | ✅ 已加 4 个视口档：`login-1366`、`screen-1366`、`grid-dashboard-1366`、`elderly-home-1366`，全部 0 违规 |
| 7 | 把「6 个真 bug + 对比度实测 + 工具化」整理进 dev-log/答辩备份 | ✅ 已写入 `docs/spec/dev-log.md` 第三十六、三十七节（含实测数字与踩坑记录，可直接当质量故事用） |

### 第 9 类检查的实现（评审建议 #4）

新增在 `scripts/ui_audit.py`，扫渲染后 DOM 的可见文本节点，分两档：

- **HARD（计入 HIGH，失败即门禁红）**：`undefined`、`NaN`、`[object Object]`、模板未渲染 `{{`/`}}`、**温度缺失占位 `°~°`/`~` 夹空**、`Infinity`
- **SOFT（只提示不失败，避免误报）**：空括号 `（）`、尾部分隔符（如「基层治理 ·」这类正常的标题截断）

**关键点：先用未修复现状证明它有效，再修 bug。** 未修复时输出：

```
## elderly-home  ·  /elderly/home  ·  390px
   ⚠ 渲染残缺文本 1（数据层字段对不上）:
      [温度缺失占位] «晴 17°~°»  div.panel-hi
```

修复 + 重启服务后：**26 个页面 `residue=0`**。这样「结构 + 数据」两层客观审计闭环：
- 结构层：对比度 / 溢出 / 热区 / 字号 / 断图 / 暗色亮度 / 动效生效 / reduced-motion
- 数据层：渲染残缺文本扫描（字段对不上会被抓）

## 三、总检查结果（本轮验证）

```powershell
python scripts/ui_audit.py     # 26 个页面/视口（含 4 个 1366×768、6 个暗色）→ 全部 0 违规
python -m pytest tests/ -q     # 564 passed / 1 skipped（新增 B1 回归 2 项）
ruff check .                   # All checks passed
cd web; npm run build          # ✓ built in
python scripts/demo_preflight.py  # 完整模式 8/8
```

## 四、保留意见与不做的事（说清理由，不装作都做了）

1. **登录页一屏动效仍偏满**（你的唯一审美保留意见）：本轮已去掉「常驻流动渐变」这一层，保留 mesh 光斑 + 粒子 + 按钮流光。再往下收就只剩光斑，竞赛开场效果会明显变弱——我建议**保持现状到答辩结束后**再按你 #8/#9 的长远项做令牌化与降级。
2. **#8 内联色继续向令牌收口 / #9 低端机降级**：这轮已把 46 处内联写死色收成亮/暗成对令牌、内联浅色块做成 ratchet 门禁（只减不增），blur 在小屏已从 18px 降到 10px、页面不可见时全站暂停动画。`prefers-reduced-transparency` 与「低内存设备改纯色」暂未做——后者没有可靠的浏览器信号（`navigator.deviceMemory` 仅 Chromium 部分支持），硬做会变成猜。
3. **#10 design-tokens.json**：认同方向，但当前超时风险更高，且三处色值目前由 `style.css` 单一来源 + 主题覆盖两处保证，暂不抽离。
4. **你的「⚪ 已排除的疑似 bug」判断我复核过**：路由切换后偶发空白确实是我方无关的截图管线取帧假象（DOM 挂载正常、强制重排即恢复），与你的结论一致。
