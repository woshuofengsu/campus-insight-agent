// web/src/utils/weatherIcon.js —— 天气"文字/数据" → 单色线性图标名
//
// 为什么要有这个文件（2026-09-29，全站去 emoji）：
//   天气图标原来是**后端给的 emoji**（`utils/weather` / `tools/query_weather.py` 返回 `emoji` 字段），
//   前端直接 `{{ w.emoji }}` 打出来。问题是：emoji 在每家手机上是不同厂商字形（大小/配色都不同），
//   同一块面板在 iPhone / 安卓 / 微信里长得不一样——而天气面板恰恰是三个端首页最显眼的一块。
//   现在改成"**前端按天气文字选图标**"：后端数据照旧（`condition` 字段本来就有），
//   图标由 `components/EIcon.vue` 画单色线性图形，跟着文字色走（暗色/高对比模式自动适配）。
//
// 纪律：映射按**关键词包含**判断（后端文案有"晴""晴间多云""雷阵雨""暴雨"等多种写法，
// 逐字相等会漏），并且**永远有兜底**（认不出来就给多云转晴），绝不出现"没有图标"的空白。
const RULES = [
  [/雷/, 'cloud-bolt'],
  [/暴雨|大雨|中雨|小雨|阵雨|雨夹雪/, 'cloud-rain'],
  [/雪|冰雹|冻雨/, 'cloud-snow'],
  [/沙|尘|雾|霾|浮尘/, 'cloud-fog'],
  [/台风|大风|风/, 'wind'],
  [/少云|晴间多云/, 'cloud-sun'],
  [/晴/, 'sun'],
  [/多云|阴|云/, 'cloud'],
]

// 后端历史上还可能只给 emoji（没有 condition 文本）时的兜底映射：按同一套语义翻译
const EMOJI_RULES = [
  [/⛈/, 'cloud-bolt'],
  [/🌧|🌦|🌊|☔/, 'cloud-rain'],
  [/❄|🌨/, 'cloud-snow'],
  [/🌫|😷/, 'cloud-fog'],
  [/🌬|💨/, 'wind'],
  [/🌤/, 'cloud-sun'],
  [/☀|🌞/, 'sun'],
  [/☁|⛅|🌈/, 'cloud'],
]

/**
 * @param {string} condition 天气文字（如"晴间多云"）
 * @param {string} [emoji]   后端可能仍带的 emoji（只在没有 condition 时才用）
 * @returns {string} 图标名（一定是 `config/icons.js` 里存在的名字）
 */
export function weatherIcon(condition = '', emoji = '') {
  const text = String(condition || '')
  for (const [re, name] of RULES) {
    if (re.test(text)) return name
  }
  for (const [re, name] of EMOJI_RULES) {
    if (re.test(String(emoji || ''))) return name
  }
  return 'cloud-sun'
}

// 空气质量/预警等级 → 语义色令牌名（不写死 hex：亮暗两套令牌各自成立）
export const AQI_ICON = 'cloud-fog'
