# 社区先知 CommunityInsight — 全面 UI 升级方案（V1）

> 依据：国际 UI 评审意见（设计系统骨架达标，但字号/对比度/图标/角色气质不达标）。
> 目标：把「系统化的骨架」升级为「无障碍的血肉 + 角色差异的气质」，对标 WCAG 2.1 AA/AAA。
> 原则：不缺时间，全量落地；先重建设计系统，再逐端应用；每阶段可回归验证。

---

## 0. 评审结论 → 升级目标

| 评审问题 | 升级目标 |
|---|---|
| 字号梯度塌陷（正文14px、辅助11px） | 正文16px、最小12px（WCAG AA） |
| 老年版"假高对比"（白底浅灰框） | 老年版 7:1 以上（WCAG AAA） |
| 两套图标语言打架（Material + emoji） | 全站统一 Material Symbols，emoji 仅装饰 |
| 三端一套气质 | 居民叙事 / 网格员工具 / 老年大块触控 |
| 网格员工作台信息密度爆表 | 视觉分区 + 表格化重构 |
| CSS 变量是平台 hack | 文档诚实标注"平台妥协"，token 层做规范 |

---

## 1. 设计 Token 系统重建（`ui/theme.py`）

### 1.1 字号梯度（重建，对齐 WCAG AA）
| Token | 现值 | 新值 | 用途 |
|---|---|---|---|
| `font_display` | 1.35em(≈21px) | **1.5em(24px)** | 页面大标题 |
| `font_title` | — | **1.25em(20px)** | 区块标题 |
| `font_body` | 0.875em(14px) | **1em(16px)** | 正文/输入/按钮 |
| `font_label` | 0.75em(12px) | **0.8125em(13px)** | 表单标签/辅助 |
| `font_micro` | 0.6875em(11px) | **0.75em(12px)** | 角标/时间戳（下限） |

> 11px 一律消灭；所有使用 `font_micro` 的地方必须检查，12px 以下禁止。

### 1.2 间距系统（8px 基准）
```
space_xs: 4px · space_sm: 8px · space_md: 16px · space_lg: 24px · space_xl: 32px
```
替换现有多处硬编码 `margin:6px 0` / `padding:8px 0` 为 token。

### 1.3 对比度标准（`ui/theme.py` + `ui/css.py`）
| 用途 | 要求 | 建议色（浅色主题） |
|---|---|---|
| 正文 `text` | ≥7:1（AAA） | #1a1a1a on #fff |
| 辅助 `text_sec` | ≥4.5:1（AA） | #475569 on #fff（实测≈7.5:1，达标） |
| 弱化 `text_muted` | ≥4.5:1 | 现值 #64748b≈4.6:1 勉强，**加深至 #526076** |
| 反色按钮文字 | ≥4.5:1 | 白字 on #4f46e5（≈5.6:1） |
| 暗色主题 | 全部 ≥4.5:1 | 重新测量 #0f0f14 底的文字对 |

**验收**：用 axe DevTools / WebAIM Contrast Checker 全站抽查，正文与辅助文字无一低于 4.5:1。

---

## 2. 图标体系统一（`ui/icons.py` 新增）

### 2.1 规范
- **功能图标**（导航/按钮/表单/状态）→ 一律 Material Symbols（`st.Page` 的 `icon=":material/xxx:"`、`st.button` 前缀）。
- **emoji 仅作情感装饰**（问候语、成功/告警的弱点缀），不得作为功能识别的唯一标识。
- **分类色点**保留（颜色承载信息，数据可视化正确姿势）。

### 2.2 迁移清单
- `app.py` 导航：已是 Material ✅（保持）。
- `ui/sidebar.py`：品牌 emoji 🏘️ 改为 Material `:material/apartment:`；紧急联系按钮的 📞/🔧 改 Material 前缀。
- `ui/pages/*`、`ui/pages_grid/*`：所有**按钮/链接的功能 emoji**（如 📊 统计、📋 工单）统一改 Material 前缀，保留一句问候 emoji。
- `ui/pages_elderly/*`：老年版大按钮的 emoji（🗣️📋💊🏥🔊）→ Material 大图标（`:material/mic:` 等），更清晰。

> 注意：Material 前缀在 `st.button`/`st.markdown` 里不渲染图标（仅 `st.Page` 支持）。**方案**：功能 emoji 只保留在 `st.Page` 导航（Material），页面内按钮改用「文字 + 语义色」或统一的 Material 图标组件（`ui/icons.py` 提供 `icon_button()` 用 CSS 内联 SVG/Material 字型）。

### 2.3 新增 `ui/icons.py`
- 提供 `material_icon(name, size=24, color)` 返回内联 SVG 字符串，用于页面内按钮/卡片的功能图标（跨 Streamlit 限制）。

---

## 3. 三角色气质差异化（每端一套排版规范）

### 3.1 居民端（叙事 + 留白 + 信任）
- 背景用极浅中性色（#fafafa），卡片圆角 16px、阴影柔和。
- 页面结构：大标题(24px) + 副标题(16px 灰) + 内容卡片（留白 space_lg）。
- 主 CTA（上报/提交）用品牌色填充大按钮；次级操作用描边按钮。
- 颜色：indigo/violet 双品牌色 + 分类色点缀。

### 3.2 网格员端（工具感 + 分区 + 高效）
- 背景更深一点（#f1f5f9），卡片圆角 12px（更紧凑）。
- **信息架构分区**（dashboard 重排）：
  1. KPI 行（统计数字，大而少）
  2. ⚠️ SLA 超时预警（告警红边卡片）
  3. ⏫ 升级工单 / 👴 老年关怀（独立卡片，可折叠）
  4. 需要立即处理（列表）
  5. 关联洞察（expander）
- **工单管理页表格化**：`st.dataframe` 替代手写 6 列 session_state 堆叠；批量操作用表单行。

### 3.3 老年端（大块触控 + 单一主操作 + AAA 对比）
- 全屏无侧边栏，20px+ 根字号。
- 主操作按钮 ≥64px 高，圆角 16px，**纯黑文字 on 白底**（或白字 on 高饱和主色）。
- 页面一次只突出 1 个主操作（SOS 或上报），避免多 CTA 竞争。
- 卡片：白底 + **深色边框（#334155 或 #000）**，不用浅灰。

---

## 4. 老年版真高对比（`ui/elderly_components.py` 重写）

### 4.1 对比度（WCAG AAA，7:1+）
```css
.elderly-card { background:#ffffff; color:#000000; border:2px solid #334155; }
.elderly-title { color:#000000; }
/* 主按钮：白字 on #dc2626（≈4.6:1）或 #000 字 on #fef2f2 + #dc2626 边框 */
```
- 全部 `#e2e8f0` 浅灰框 → 深色框或纯黑。
- 辅助文字 ≥14px、正文 ≥18px（老年版下限高于通用）。

### 4.2 触控（≥64px）
- 所有按钮 `min-height:64px`；卡片内可点区域 padding 20px+。
- 无下拉/滑动条；表单用大号 text_input（font-size 1.2em）。

### 4.3 语音
- `voice_input` 组件按钮加大、高对比；识别状态文字 14px+。
- TTS 语速 0.9（已有）。

---

## 5. 组件库升级（`ui/components.py`）

### 5.1 卡片系统
- 统一 `_card()` 的圆角/阴影/留白（用新 space token）。
- 卡片标题层级：`section()` 支持 `font_title`(20px) + 可选副标题。

### 5.2 按钮
- 四态：主（品牌色填充）/ 次（描边）/ 危险（红）/ 幽灵（文字）。
- 统一 `min-height`（居民 44px、老年 64px）。

### 5.3 状态徽章 `tag()`
- 语义色 + 白字（保证 ≥4.5:1）；「待处理」红、「处理中」黄（深字）、「已解决」绿。

### 5.4 表单
- label 13px、输入 16px、错误 14px 红（#b91c1c on #fff ≈ 6.5:1）。

---

## 6. 实施路线图（不缺时间，全量）

| 阶段 | 内容 | 涉及文件 | 验收 |
|---|---|---|---|
| P1 | Token 重建（字号/间距/对比度） | `ui/theme.py`、`ui/css.py` | 字号无 <12px；正文 16px |
| P2 | 图标体系统一 | `ui/icons.py`(新)、sidebar、各页 | 功能图标无 emoji 残留 |
| P3 | 老年版高对比 + 触控 | `ui/elderly_components.py`、elderly 页面 | 老年卡片 7:1；按钮 ≥64px |
| P4 | 三角色气质（居民叙事 / 网格员工具） | `ui/pages/*`、`ui/pages_grid/*` | 三端视觉可区分 |
| P5 | 网格员工作台重构（分区 + 表格化） | `ui/pages_grid/dashboard.py`、`issues_mgmt.py` | 无 session_state 堆叠；分区清晰 |
| P6 | 组件库升级（卡片/按钮/徽章/表单） | `ui/components.py` | 全站一致；对比度达标 |
| P7 | 回归 + 无障碍验收 | 全站 | axe 抽查 0 严重项；对比度测量表落盘 |

---

## 7. 验收标准（可测量，非感觉）

1. **字号**：全局扫描无 <12px 文本；正文 ≥16px。
2. **对比度**：axe DevTools 全站抽查，严重项 = 0；正文 ≥4.5:1、老年版 ≥7:1（附测量表 `docs/UI_CONTRAST.md`）。
3. **图标**：grep 无「功能 emoji」残留（仅问候/情感 emoji）。
4. **触控**：老年端按钮 ≥64px、居民 ≥44px。
5. **三角色**：截图对比三端首页，视觉气质明显不同。
6. **网格员工作台**：无 `_detail_assignee_{iid}` 式手写控件堆叠。
7. **回归**：`pytest` 全绿；Streamlit 无 widget ownership 错误。

---

## 8. 诚实标注（评审可接受项）

- **CSS 变量是平台 hack**：Streamlit 不支持原生 CSS 变量，`_ThemeAwareToken` 是 Python 层代理——设计说明里写清"平台妥协，非原生能力"。
- **Material 图标在页面内不原生支持**：用 `ui/icons.py` 的 SVG 方案桥接，同样如实标注。

---

## 9. 一句话

> 骨架已有 80 分，这轮把「字号、对比度、图标、角色气质」这四块血肉补上——
> 目标是让评审第一眼看到的不再是"功能多的演示"，而是**"有设计语言的产品"**。
