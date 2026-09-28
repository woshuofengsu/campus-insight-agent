// 老年端「紧急求助」共享逻辑（v3 复核 B4：独立紧急求助要在任何页面都能一键到达）。
//
// 为什么抽出来：原来这套逻辑只写在首页（`Home.vue`），老人到了别的页面就找不到求助入口；
// 而把 SOS 复制到导航栏又会变成两套实现（改一处漏一处）。所以抽成 composable：
// **首页大按钮**和**顶部导航的红色求助键**共用同一份状态机与同一套文案。
//
// 安全设计（保持不变，`scripts/mobile_flow_check.py` 会实测）：
//   ① 长按 3 秒才进入确认 —— 单击绝不触发（防误触是第一位的）；
//   ② 确认框 10 秒内不点就自动取消（老人误触后什么都不做也不会惊动社区）；
//   ③ 触发后如实说明「已通知负责人 + 已审核的联系人」，并且**明说手机不会自动连续拨号**，
//      需要时点「拨打 120」——不许把"已弹拨号盘"说成"已经打通了"。
import { ref, onBeforeUnmount } from 'vue'
import { elderly } from '../api'
import { useSpeech } from './useSpeech'

const HOLD_MS = 3000
const CONFIRM_SECONDS = 10

export function useSos({ onMessage, speakOpts = () => [1.0, 0.9] } = {}) {
  const { speak } = useSpeech()
  const sosConfirm = ref(false)
  const sosCountdown = ref(CONFIRM_SECONDS)
  const contactNames = ref('')
  let pressTimer = null
  let sosTimer = null

  function say(text) {
    const [vol, rate] = speakOpts()
    // 播报是增强项：失败由调用页面（ttsOk 降级条）统一说明，这里不阻塞主流程
    return speak(text, vol, rate)
  }

  /** 取已审核通过的紧急联系人姓名（用于确认框与结果文案；取不到就说"暂无"）。 */
  async function loadContactNames() {
    try {
      const rows = (await elderly.contacts()) || []
      contactNames.value = rows.filter((c) => c.status === '审核通过')
        .slice(0, 3).map((c) => c.name).join('、')
    } catch { /* 取不到不影响求助本身（负责人通知才是主链路） */ }
    return contactNames.value
  }

  /** 按下：3 秒后弹确认框（配合 @pointerdown/@touchstart）。 */
  function pressStart() {
    if (pressTimer) clearTimeout(pressTimer)
    pressTimer = setTimeout(() => {
      sosConfirm.value = true
      sosCountdown.value = CONFIRM_SECONDS
      if (sosTimer) clearInterval(sosTimer)
      sosTimer = setInterval(() => {
        sosCountdown.value -= 1
        if (sosCountdown.value <= 0) {
          clearInterval(sosTimer)
          sosTimer = null
          sosConfirm.value = false
          onMessage?.info?.(`${CONFIRM_SECONDS} 秒未确认，求助已自动取消`)
          say('求助已取消')
        }
      }, 1000)
    }, HOLD_MS)
  }

  /** 松开/移出：取消长按计时（已进确认框时不撤销，交由倒计时或用户点选）。 */
  function pressCancel() {
    if (pressTimer) clearTimeout(pressTimer)
    pressTimer = null
  }

  /** 老人点了「取消」：明确取消并停止倒计时。 */
  function cancelConfirm() {
    if (sosTimer) clearInterval(sosTimer)
    sosTimer = null
    sosConfirm.value = false
  }

  /** 老人确认求助：真实调用后端（通知负责人），文案如实说明后续要手动拨号。 */
  async function confirmSos() {
    if (sosTimer) clearInterval(sosTimer)
    sosTimer = null
    sosConfirm.value = false
    try {
      if (!contactNames.value) await loadContactNames()
      await elderly.emergency()
      const suffix = contactNames.value ? `，已通知紧急联系人：${contactNames.value}` : ''
      await say(`紧急求助已发出${suffix}，需要时请点拨打120`)
      onMessage?.success?.(
        `紧急求助已发出${suffix}。手机无法自动连续呼叫，请点「拨打 120」手动求助。`)
    } catch (e) {
      onMessage?.error?.(e.message || '触发失败')
    }
  }

  onBeforeUnmount(() => {
    if (pressTimer) clearTimeout(pressTimer)
    if (sosTimer) clearInterval(sosTimer)
  })

  return {
    sosConfirm, sosCountdown, contactNames,
    pressStart, pressCancel, cancelConfirm, confirmSos, loadContactNames,
  }
}
