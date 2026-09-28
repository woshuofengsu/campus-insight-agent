// 设计令牌（v2 方案 §12.3 / §12.7-1）：**样式表与 Naive 主题同源**。
//
// 为什么有这个文件：`style.css` 里的 CSS 变量和 `App.vue` 的 Naive `themeOverrides`
// 原来各写一份 hex —— 同一块品牌蓝在两处各改一半就会"页面里是新的、组件里是旧的"
// （本项目最忌讳的"做了但不生效"）。现在：
//   · 两边**共用的**颜色在这里列成一张表（键 → [CSS 变量名, 取值]）；
//   · `App.vue` 从这里取常量，不再内联裸 hex；
//   · `tests/test_design_tokens.py` 解析 `style.css` 逐条核对**两边取值一致**，
//     任何一边单独改动都会红（这才是"同源"的可验证含义，而不是靠自觉）。
//
// 只放**确实两边都用**的颜色。纯主题用的（Naive 填充色、hover/pressed 派生色）放 `THEME_ONLY`，
// 它们不进核对表——没有 CSS 对应变量，进表只会变成假核对。

/** 亮色令牌：[CSS 变量名, 取值]。取值必须与 `style.css` 的 `:root` 完全一致。 */
export const LIGHT_CSS_TOKENS = {
  primary: ['--primary', '#2D5BFF'],
  primaryDeep: ['--primary-deep', '#1E3A8A'],
  text: ['--text', '#16233B'],
  muted: ['--muted', '#5B6B80'],
  border: ['--border', '#E7ECF3'],
  inkSuccess: ['--ink-success', '#047857'],
  inkDanger: ['--ink-danger', '#B91C1C'],
  inkWarning: ['--ink-warning', '#B45309'],
  inkInfo: ['--ink-info', '#2563EB'],
  primaryInk: ['--primary-ink', '#2D5BFF'],
  dangerSolid: ['--danger-solid', '#DC2626'],
  successInk: ['--success-ink', '#047857'],
  statusPending: ['--st-pending', '#F59E0B'],
  statusSuccess: ['--st-success', '#10B981'],
  statusDone: ['--st-done', '#9CA3AF'],
}

/** 暗色令牌：取值必须与 `style.css` 的 `body.dark` 完全一致。 */
export const DARK_CSS_TOKENS = {
  bg: ['--bg', '#0F172A'],
  cardBg: ['--card-bg', '#1E293B'],
  text: ['--text', '#E2E8F0'],
  muted: ['--muted', '#94A3B8'],
  border: ['--border', '#334155'],
  disabled: ['--disabled', '#64748B'],
  primaryLight: ['--primary-light', '#1E3A8A'],
  inkSuccess: ['--ink-success', '#6EE7B7'],
  inkDanger: ['--ink-danger', '#FCA5A5'],
  inkWarning: ['--ink-warning', '#FCD34D'],
  inkInfo: ['--ink-info', '#93B4FF'],
  primaryInk: ['--primary-ink', '#8FA8FF'],
  statusPendingInk: ['--st-pending-ink', '#F59E0B'],
}

/** 纯主题色（Naive 填充/hover/pressed 等，style.css 没有对应变量，故不参与核对）。 */
export const THEME_ONLY = {
  lightPrimaryHover: '#4F74FF',
  lightPrimarySuppl: '#6A8DFF',
  lightSuccess: '#10B981',
  lightWarning: '#F59E0B',
  lightInfo: '#0EA5E9',
  lightErrorHover: '#C0223B',
  lightErrorPressed: '#A11C33',
  lightSuccessFill: '#047857',
  lightSuccessFillHover: '#036B4E',
  lightSuccessFillPressed: '#02543D',
  lightWarningFill: '#B45309',
  lightWarningFillHover: '#92400E',
  lightWarningFillPressed: '#78350F',
  lightInfoFill: '#0369A1',
  lightInfoFillHover: '#075985',
  lightInfoFillPressed: '#0C4A6E',
  darkPrimary: '#6A8DFF',
  darkPrimaryHover: '#8FA8FF',
  darkPrimarySuppl: '#93B4FF',
  darkSuccess: '#34D399',
  darkWarning: '#FBBF24',
  darkError: '#F87171',
  darkInfo: '#38BDF8',
  placeholder: '#8B95A8',
  darkPlaceholder: '#8B95A8',
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
