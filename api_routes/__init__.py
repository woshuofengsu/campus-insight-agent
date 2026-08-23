# api_routes — Web API 路由模块包（P2-04 / P1-F2-01：api_web 单体拆分）
"""从 api_web.py 拆出的路由模块，通过 app.include_router 挂载。

当前已拆模块：
  - agent.py   /api/web/agent/*（Agent 统一入口 + 留痕/处理包/用量/分析）
  - deps.py    共享依赖（统一响应 / 用户上下文 / 角色校验 / 老年端免登录解析）
"""
