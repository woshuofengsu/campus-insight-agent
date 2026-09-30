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
  // 老人自己按了「停下」：这不是故障（**不许**提示"不支持语音"或"说错了"）
  cancelled: '好的，停下了。您可以打字，或者再点一次说话',
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
  // 「允许停止和取消」（v3 §7.1）：老人点了开始之后必须能**自己停下**，
  // 而不是被 60 秒倒计时拖着（听错了、不想说了、旁边有人说话都要能停）。
  // 实现：把当前识别会话的 stop 句柄放在模块级变量里，`stopListening()` 从任意位置调用。
  let _activeStop = null

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
      let cancelled = false

      // 结束会话（成功/失败/取消都走这里），保证 stop 句柄不会残留
      const close = (payload) => {
        finished = true
        clearInterval(timer)
        _activeStop = null
        resolve(payload)
      }
      _activeStop = () => {
        if (finished) return false
        cancelled = true
        clearInterval(timer)
        try { rec.stop() } catch { /* 忽略 */ }
        return true
      }

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
        const reasonMap = {
          'not-allowed': 'mic-denied',
          'service-not-allowed': 'https-required',
          network: 'network',
          aborted: 'error',
          'no-speech': 'empty',
        }
        // 自己按的「停下」不算故障：浏览器会把它报成 aborted，这里要覆盖掉
        if (cancelled) return close({ ok: false, reason: 'cancelled', text: final })
        close({ ok: final.length > 0, reason: reasonMap[e.error] || 'error', text: final })
      }
      rec.onend = () => {
        if (finished) return
        if (cancelled) return close({ ok: false, reason: 'cancelled', text: final })
        close({ ok: final.length > 0, reason: final ? 'done' : 'empty', text: final })
      }
      try {
        rec.start()
      } catch {
        close({ ok: false, reason: 'error', text: '' })
      }
    })
  }

  /** 停下手里的识别（老人按了「停下」/页面要离开时调用）。返回是否真的停了一个会话。 */
  function stopListening() {
    return _activeStop ? _activeStop() : false
  }

  // —— 语音合成（朗读，音量可调；老人档可调慢语速，失败重试 3 次）——
  // 返回 true/false；**调用方必须处理 false**（iOS 需用户手势、部分机型静音），
  // 不能假设"点了就一定会响"。
  //
  // <EIcon name="alert" :size="18" /> 兜底超时（2026-09-29 实测踩到）：有些机型 `speak()` 既不触发 `onend` 也不触发 `onerror`
  // （没有语音包、被系统静音掐断、后台标签页等）。没有这个兜底，调用方的 `await say(...)`
  // **会永远挂住**——老年端报修页的后果是「确认上报」按钮永久转圈：老人既看不到结果，
  // 也点不了第二次（首批八条浏览器旅程排查时用无语音的 headless 浏览器复现的）。
  // 当前播报的"停下"句柄（v3 §7.3：允许重听、暂停与停止）
  let _speakStop = null

  /** 停止正在进行或排队的播报（页面离开、老人按「别念了」时调用）。 */
  function stopSpeaking() {
    const had = !!_speakStop
    if (_speakStop) _speakStop()
    try {
      if (window.speechSynthesis) window.speechSynthesis.cancel()
    } catch { /* 忽略：停不了也不该影响页面 */ }
    return had
  }

  function speak(text, volume = 1.0, rate = 1.0) {
    return new Promise((resolve) => {
      if (typeof window === 'undefined' || !window.speechSynthesis || !text) return resolve(false)
      let tries = 0
      let settled = false
      // 说话最长给多久：短句 3 秒起，按字数放宽（中文约 4 字/秒，留足余量）
      const guardMs = Math.min(20000, 3000 + String(text).length * 250)
      const guard = setTimeout(() => finish(false), guardMs)
      function finish(ok) {
        if (settled) return
        settled = true
        clearTimeout(guard)
        _speakStop = null
        resolve(ok)
      }
      _speakStop = () => finish(false)
      function attempt() {
        tries++
        const u = new SpeechSynthesisUtterance(text)
        u.lang = 'zh-CN'
        u.rate = rate
        u.volume = volume
        u.onend = () => finish(true)
        u.onerror = () => {
          if (tries < 3) setTimeout(attempt, 300) // 失败重试 3 次
          else finish(false)
        }
        try {
          window.speechSynthesis.cancel()
          window.speechSynthesis.speak(u)
        } catch {
          finish(false)
        }
      }
      attempt()
    })
  }

  return { recognize, speak, stopListening, stopSpeaking }
}
