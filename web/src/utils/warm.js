// 前端关怀镜像（M1）：与 agent/tone.py 单一事实源对应，负责标题/toast 人话化。
export const greeting = (h) => {
  if (h < 6) return '夜深了，注意身体'
  if (h < 11) return '早上好'
  if (h < 13) return '中午好，记得吃饭'
  if (h < 18) return '下午好'
  return '晚上好'
}

export const humanIssueStatus = (s) =>
  ({
    '待审核': '收到，正在核对',
    '待派单': '正在安排负责人',
    '处理中': '师傅在处理啦，您等就好',
    '待反馈': '等您确认结果',
    '已完成': '已办结',
    '已驳回': '需要再补点信息'
  }[s] || s)

export const friendlyError = (msg) =>
  /频繁/.test(msg || '')
    ? '您说得有点快，我喘口气，稍等几秒哈'
    : /失败|错误|异常/.test(msg || '')
      ? '这一步没成功，我们再来一次，不行就点"找社区"'
      : msg

export const SOP_SAFE = '没什么大碍，就是有点不舒服，别担心。'
