// 设计令牌（v2 方案 §12.3 / §12.7-1）：**样式表与 Naive 主题同源**。
//
// 为什么有这个文件：`style.css` 里的 CSS 变量和 `App.vue` 的 Naive `themeOverrides`
// 原来各写一份 hex —— 同一块品牌色在两处各改一半就会"页面里是新的、组件里是旧的"
// （本项目最忌讳的"做了但不生效"）。现在：
//   · 两边**共用的**颜色在这里列成一张表（键 → [CSS 变量名, 取值]）；
//   · `App.vue` 从这里取常量，不再内联裸 hex；
//   · `tests/test_design_tokens.py` 解析 `style.css` 逐条核对**两边取值一致**，
//     任何一边单独改动都会红（这才是"同源"的可验证含义，而不是靠自觉）。
//
// 只放**确实两边都用**的颜色。纯主题用的（Naive 填充色、hover/pressed 派生色）放 `THEME_ONLY`，
// 它们不进核对表——没有 CSS 对应变量，进表只会变成假核对。
//
// v3（2026-10-06「社区服务站」重设计）：品牌色从演示蓝 `#2D5BFF` 换成**稳重蓝绿** `#1B6B5A`，
// 中性色从中性偏冷换成温和灰白/蓝灰。改这里的值必须同步 `style.css` 的 `:root`，
// 否则 `tests/test_design_tokens.py` 直接红（这条路是故意设成"改一边就跑不起来"的）。

/** 亮色令牌：[CSS 变量名, 取值]。取值必须与 `style.css` 的 `:root` 完全一致。 */
export const LIGHT_CSS_TOKENS = {
  primary: ['--primary', '#1B6B5A'],
  primaryDeep: ['--primary-deep', '#12503F'],
  text: ['--text', '#1E2A32'],
  muted: ['--muted', '#5C6B73'],
  border: ['--border', '#E2E7E5'],
  inkSuccess: ['--ink-success', '#0F6B4F'],
  inkDanger: ['--ink-danger', '#9E2B23'],
  inkWarning: ['--ink-warning', '#8A5A00'],
  inkInfo: ['--ink-info', '#1F5F7A'],
  primaryInk: ['--primary-ink', '#1B6B5A'],
  dangerSolid: ['--danger-solid', '#B4392F'],
  successInk: ['--success-ink', '#0F6B4F'],
  statusPending: ['--st-pending', '#C98A16'],
  statusSuccess: ['--st-success', '#3E8E72'],
  statusDone: ['--st-done', '#8A949A'],
}

/** 暗色令牌：取值必须与 `style.css` 的 `body.dark` 完全一致。 */
export const DARK_CSS_TOKENS = {
  bg: ['--bg', '#101614'],
  cardBg: ['--card-bg', '#1A2320'],
  text: ['--text', '#E6EBE8'],
  muted: ['--muted', '#9DAAA5'],
  border: ['--border', '#2C3833'],
  disabled: ['--disabled', '#7A8681'],
  primaryLight: ['--primary-light', '#123B31'],
  inkSuccess: ['--ink-success', '#7FD3B4'],
  inkDanger: ['--ink-danger', '#F0A6A0'],
  inkWarning: ['--ink-warning', '#E8C88A'],
  inkInfo: ['--ink-info', '#9CC6D8'],
  primaryInk: ['--primary-ink', '#8FD3BE'],
  statusPendingInk: ['--st-pending-ink', '#E8C88A'],
}

/** 纯主题色（Naive 填充/hover/pressed 等，style.css 没有对应变量，故不参与核对）。 */
export const THEME_ONLY = {
  lightPrimaryHover: '#227A66',
  lightPrimarySuppl: '#2F8B74',
  lightSuccess: '#3E8E72',
  lightWarning: '#C98A16',
  lightInfo: '#2C6E8F',
  lightErrorHover: '#99302A',
  lightErrorPressed: '#7F2822',
  lightSuccessFill: '#0F6B4F',
  lightSuccessFillHover: '#0C5A42',
  lightSuccessFillPressed: '#094834',
  lightWarningFill: '#8A5A00',
  lightWarningFillHover: '#754C00',
  lightWarningFillPressed: '#5F3D00',
  lightInfoFill: '#1F5F7A',
  lightInfoFillHover: '#1A4F66',
  lightInfoFillPressed: '#154052',
  darkPrimary: '#8FD3BE',
  darkPrimaryHover: '#A5DFCC',
  darkPrimarySuppl: '#9CC6D8',
  darkSuccess: '#7FD3B4',
  darkWarning: '#E8C88A',
  darkError: '#F0A6A0',
  darkInfo: '#9CC6D8',
  placeholder: '#8A949A',
  darkPlaceholder: '#8A949A',
}

function pick(table) {
  const out = {}
  for (const [key, pair] of Object.entries(table)) out[key] = pair[1]
  return out
}

/** 亮色取值（`themeOverrides` 直接用）。 */
export const LIGHT = pick(LIGHT_CSS_TOKENS)
/** 暗色取值（`themeOverrides` 直接用）。 */
export const DARK = pick(DARK_CSS_TOKENS)
