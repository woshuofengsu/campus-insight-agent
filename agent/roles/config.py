# agent/roles/config.py
"""9 角色元数据声明（供 Orchestrator 注册、前端展示、答辩材料自动生成）。

角色划分：统一入口 / 5 业务 / 自动监测 / 网格助手 / 后台审计。
"""
ROLE_META = {
    "receptionist": {
        "name": "社区接待员", "icon": "👤",
        "desc": "统一入口：意图识别、追问引导、情绪安抚、纠错确认、路由分发",
        "audience": "居民/老人",
        "human_stop": "意图不明确时转人工",
    },
    "repair_dispatch": {
        "name": "报修调度员", "icon": "🔧",
        "desc": "报修全流程：草稿、创建、分派、跟踪、反馈（复用报修状态机）",
        "audience": "居民/老人",
        "human_stop": "生成工单前必须用户确认",
    },
    "proposal_collab": {
        "name": "提案协商员", "icon": "💡",
        "desc": "提案提交、公示、投票、执行、反馈（复用提案状态机）",
        "audience": "居民",
        "human_stop": "执行决定必须负责人批准",
    },
    "health_advisor": {
        "name": "健康顾问", "icon": "🏥",
        "desc": "健康咨询、就医指引、疾病预防提醒（不诊断，仅给建议）",
        "audience": "居民",
        "human_stop": "不诊断，仅给建议；紧急症状提示就医",
    },
    "policy_expert": {
        "name": "政策专员", "icon": "📖",
        "desc": "政策问答，强制引用知识库，无引用不回答",
        "audience": "居民/老人",
        "human_stop": "无引用不回答，转人工",
    },
    "notification_manager": {
        "name": "通知管理员", "icon": "📢",
        "desc": "通知创建、定时、发布；紧急通知需负责人审核",
        "audience": "负责人",
        "human_stop": "紧急通知二次确认；Agent 不直接发布紧急通知",
    },
    "weather_guardian": {
        "name": "天气守护员", "icon": "🌤️",
        "desc": "监测天气，触发预警，联动健康与通知（自动运行）",
        "audience": "自动",
        "human_stop": "不自动执行应急措施（拨号/撤离等）",
    },
    "grid_assistant": {
        "name": "网格员工作助手", "icon": "🛠️",
        "desc": "搜索、导出、统计、待办提醒、页面跳转",
        "audience": "负责人",
        "human_stop": "不代替审批；导出/看手机号需二次确认",
    },
    "compliance_auditor": {
        "name": "合规审计员", "icon": "🛡️",
        "desc": "数据脱敏、敏感词检测、操作留痕、权限校验",
        "audience": "后台",
        "human_stop": "审计不通过拦截输出",
    },
}

# 路由映射：意图 → 业务角色（合规审计员为全局后置，不在此映射）
ROUTE_MAP = {
    "repair": "repair_dispatch",
    "proposal": "proposal_collab",
    "health": "health_advisor",
    "policy": "policy_expert",
    "notification": "notification_manager",
    "weather": "weather_guardian",
    "grid": "grid_assistant",
}

# 跨部门仲裁优先级（P2-01）：数字越小优先级越高；compliance 一票否决
DEPT_PRIORITY = {
    "compliance_auditor": 1,   # 合规审计部：最终否决权
    "safety_emergency": 2,     # 安全/紧急
    "professional": 3,         # 专业部门（报修/提案/健康/政策/通知/天气）
    "cost_liability": 4,       # 费用/责任 → 转人工
    "default": 5,              # 默认保守 → 转人工
}

# 各业务 Agent 可裁决/不可裁决范围（P2-01 部门权限表）
DEPT_SCOPE = {
    "repair_dispatch": {"can": ["报修分类", "紧急程度", "分派"], "cannot": ["费用争议", "责任归属"]},
    "proposal_collab": {"can": ["提案类别", "公示规则"], "cannot": ["执行部门资源", "预算"]},
    "health_advisor": {"can": ["健康建议", "就医指引"], "cannot": ["政策合规", "药品批准"]},
    "policy_expert": {"can": ["政策解读", "引用规则"], "cannot": ["医疗诊断", "个例适用"]},
    "notification_manager": {"can": ["通知发布", "发布范围"], "cannot": ["隐私合规", "法律风险"]},
    "weather_guardian": {"can": ["天气预警", "联动建议"], "cannot": ["应急措施执行"]},
    "grid_assistant": {"can": ["数据检索", "导出", "统计"], "cannot": ["审批", "决策"]},
    "compliance_auditor": {"can": ["全部（否决权）"], "cannot": []},
}
