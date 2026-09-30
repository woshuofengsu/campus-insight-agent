// web/src/utils/idemToken.js —— 写操作的**幂等编号**（一次"意图"一个编号，重试沿用）
//
// 为什么要统一到一处（2026-09-29）：
//   卡8 的服务端幂等（`data/db_idempotency.begin`）要求客户端对**同一次意图**反复提交时
//   带**同一个**编号，才会被识别成重复。老年端报修、网格端人工待办各自写了一份生成逻辑，
//   现在通知发布/撤回也要用 —— 三份复制迟早会分叉（比如一处用 32 位、一处带横线，
//   服务端按 `(scope,key)` 存，格式不一致不会报错、只会**静默不幂等**）。
//
// 用法：
//   const t = tokenOnce(bucket, `${id}:${action}`)   // 没编号就生成，有就复用
//   ... 提交成功后 dropToken(bucket, key)             // 这次意图结束，下次点击是新意图
export function newToken() {
  try {
    if (typeof window !== 'undefined' && window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID().replace(/-/g, '')
    }
  } catch { /* 忽略：回落下面的方案 */ }
  return 't' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
}

/** 取（必要时生成）某个意图的编号；`bucket` 是调用方的 `ref({})`。 */
export function tokenOnce(bucket, key, make = newToken) {
  if (!bucket.value[key]) bucket.value[key] = make()
  return bucket.value[key]
}

/** 意图完成后清掉编号（下次点击＝新的一次意图）。 */
export function dropToken(bucket, key) {
  delete bucket.value[key]
}
