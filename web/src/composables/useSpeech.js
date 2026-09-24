// 老年端语音工具：Web Speech 语音识别（60 秒倒计时）+ 语音合成（音量可调）
//
// 2026-09-24 无障碍/降级硬化（B4）：
//   1. 新增 `speechCapability()`：**同步**探测 ASR/TTS/安全上下文，页面挂载即可渲染降级提示条，
//      而不是等老人点了按钮才发现"这台机器不能用"；
//   2. 降级文案统一到 `reasonText()`（原来只有 Agent.vue 自己写了一份，其余页把"不支持"误报成"没听清"）；
//   3. 页面上的降级提示条统一带 `data-speech-fallback` 属性——审计脚本靠它做机器验证
//      （注入脚本删掉 SpeechRecognition/speechSynthesis 后重载，断言提示条出现且输入框可聚焦）。
//
// 背景（真机现实）：iOS Safari 的 TTS 需要**用户手势**触发，挂载即 `speak()` 会静默不响；
// 微信内置浏览器大概率没有 Web Speech。所以"语音"永远是增强项，**打字/点按必须是保底路径**。

const MAX_SECONDS = 60 // 单次语音最长 60 秒

// 统一降级文案：reason → 给老人看的话（不要出现技术术语）
const REASON_MSG = {
  unsupported: '这台手机不支持语音，已切换成打字输入，您可以直接打字',
  'https-required': '语音需要安全连接，已切换成打字输入，您可以直接打字',
  'mic-denied': '没有拿到麦克风权限，请在浏览器里允许，或者直接打字',
  network: '语音服务连不上，您可以直接打字，或者稍后再试',
  empty: '没听清，请再说一次',
  error: '语音出了点小问题，您可以直接打字',
}

/** 同步探测本机语音能力（页面挂载即可判断，无需等用户点击）。 */
export function speechCapability() {
  if (typeof window === 'undefined') {
    return { hasASR: false, hasTTS: false, secure: false, asrReason: 'unsupported', ttsReason: 'unsupported' }
  }
  const hasASR = !!(window.SpeechRecognition || window.webkitSpeechRecognition)
  // 用**真值判断**而不是 `'speechSynthesis' in window`：属性存在但值是 undefined 时（浏览器实现残缺、
  // 被扩展或注入脚本置空）`in` 会误判成"支持"，等到调用时才炸。这条是审计检查⑧实测逼出来的。
  const hasTTS = !!window.speechSynthesis
  const secure = window.isSecureContext !== false
  return {
    hasASR,
    hasTTS,
    secure,
    asrReason: hasASR ? (secure ? '' : 'https-required') : 'unsupported',
    ttsReason: hasTTS ? '' : 'unsupported',
  }
}

/** reason → 降级文案（页面统一用它，别各写一份）。 */
export function reasonText(reason) {
  return REASON_MSG[reason] || REASON_MSG.error
}

export function useSpeech() {
  // —— 语音识别（录音转文字）——
  function recognize() {
    return new Promise((resolve) => {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition
      if (!SR) return resolve({ ok: false, reason: 'unsupported', text: '' })
      const rec = new SR()
      rec.lang = 'zh-CN'
      rec.interimResults = true
      rec.maxAlternatives = 1
      rec.continuous = false

      let final = ''
      let timer = null
      let remain = MAX_SECONDS
      let finished = false

      // 60 秒倒计时自动结束（方案：单次语音最长 60 秒）
      timer = setInterval(() => {
        remain -= 1
        if (remain <= 0 && !finished) {
          finished = true
          clearInterval(timer)
          try { rec.stop() } catch { /* 忽略 */ }
        }
      }, 1000)

      rec.onresult = (e) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) {
            final = e.results[i][0].transcript
            finished = true
            clearInterval(timer)
          }
        }
      }
      rec.onerror = (e) => {
        clearInterval(timer)
        const reasonMap = {
          'not-allowed': 'mic-denied',
          'service-not-allowed': 'https-required',
          network: 'network',
          aborted: 'error',
          'no-speech': 'empty',
        }
        resolve({ ok: final.length > 0, reason: reasonMap[e.error] || 'error', text: final })
      }
      rec.onend = () => {
        clearInterval(timer)
        resolve({ ok: final.length > 0, reason: final ? 'done' : 'empty', text: final })
      }
      try { rec.start() } catch { clearInterval(timer); resolve({ ok: false, reason: 'error', text: '' }) }
    })
  }

  // —— 语音合成（朗读，音量可调；老人档可调慢语速，失败重试 3 次）——
  // 返回 true/false；**调用方必须处理 false**（iOS 需用户手势、部分机型静音），
  // 不能假设"点了就一定会响"。
  function speak(text, volume = 1.0, rate = 1.0) {
    return new Promise((resolve) => {
      if (typeof window === 'undefined' || !window.speechSynthesis || !text) return resolve(false)
      let tries = 0
      function attempt() {
        tries++
        const u = new SpeechSynthesisUtterance(text)
        u.lang = 'zh-CN'
        u.rate = rate
        u.volume = volume
        u.onend = () => resolve(true)
        u.onerror = () => {
          if (tries < 3) setTimeout(attempt, 300) // 失败重试 3 次
          else resolve(false)
        }
        window.speechSynthesis.cancel()
        window.speechSynthesis.speak(u)
      }
      attempt()
    })
  }

  return { recognize, speak }
}
