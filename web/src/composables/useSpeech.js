// 老年端语音工具：Web Speech 语音识别（60 秒倒计时）+ 语音合成（音量可调）
// 浏览器不支持时自动降级为文字输入，绝不阻塞。

const MAX_SECONDS = 60 // 单次语音最长 60 秒

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
      rec.onerror = () => {
        clearInterval(timer)
        resolve({ ok: final.length > 0, reason: final ? 'partial' : 'error', text: final })
      }
      rec.onend = () => {
        clearInterval(timer)
        resolve({ ok: final.length > 0, reason: final ? 'done' : 'empty', text: final })
      }
      try { rec.start() } catch { clearInterval(timer); resolve({ ok: false, reason: 'error', text: '' }) }
    })
  }

  // —— 语音合成（朗读，音量可调，失败重试 3 次）——
  function speak(text, volume = 1.0) {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window) || !text) return resolve(false)
      let tries = 0
      function attempt() {
        tries++
        const u = new SpeechSynthesisUtterance(text)
        u.lang = 'zh-CN'
        u.rate = 0.9
        u.volume = volume
        u.onend = () => resolve(true)
        u.onerror = () => {
          if (tries < 3) setTimeout(attempt, 300) // 失败重试 3 次
          else resolve(false)
        }
        speechSynthesis.cancel()
        speechSynthesis.speak(u)
      }
      attempt()
    })
  }

  return { recognize, speak }
}
