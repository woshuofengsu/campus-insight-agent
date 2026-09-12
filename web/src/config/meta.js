// web/src/config/meta.js — 登录页品牌指标的**唯一来源**（Login.vue 只读不写）
//
// 为什么要集中管理（外部评审 P2）：
//   原先 4 个数字硬编码在 Login.vue 模板里，其中「AI 自转率 62%」与后端实测口径对不上
//   （`db_agent.get_self_resolution_stats` 返回 AI 对话自解决率 90.9%、工单社区自办结率 12.9%，
//    没有 62% 这个合成口径）。评委先看登录页 62%、再进大屏看实时值，数字打架，反而削弱
//   「数据可验证」的卖点。
//
// 两条硬规则：
//   1. 登录页是**未登录态**，调不了 grid 锁的端点 → 不放易变的业务指标，只放可复算的稳定项
//   2. 每个数字都要能被 `scripts/demo_preflight.py` 自动核对（见 source 字段），
//      其中 rag_hit1 由 CI 的 rag_eval 步骤门禁，其余三项 preflight 现场核对
export const BRAND_METRICS = [
  {
    key: 'tests',
    value: 565,
    suffix: '',
    label: '自动化测试',
    // pytest 收集用例数（= 564 通过 + 1 需外部服务默认跳过）；全量模式由 preflight 跑 --collect-only 核对
    source: 'pytest --collect-only（preflight 全量模式核对）',
  },
  {
    key: 'rag_golden',
    value: 42,
    suffix: '',
    label: '检索评测集',
    source: 'tests/llm_eval/rag_golden.jsonl 去注释行数（preflight 核对）',
  },
  {
    key: 'rag_hit1',
    value: 100,
    suffix: '%',
    label: '命中率 hit@1',
    source: 'scripts/rag_eval.py（CI 门禁步骤核对，实测混合检索 42/42）',
  },
  {
    key: 'agents',
    value: 9,
    suffix: '',
    label: '智能体角色',
    source: 'len(agent.roles.AGENT_CLASSES)（preflight 核对）',
  },
]
