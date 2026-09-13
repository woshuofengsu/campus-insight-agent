# scripts/demo_acceptance.py — 终局验收：在**运行中的主服务**上跑真实端到端链路
# -*- coding: utf-8 -*-
"""与 `pytest`（单测）和 `demo_preflight.py`（环境自检）互补：这里打的是**真实 HTTP + 真实数据**，
用来回答一个问题——「现在打开浏览器演示，各端都能真的跑通吗？」

覆盖 8 条演示关键链路：
  1. 服务身份与版本（不是"200 就算过"，要校验是本服务）
  2. 三个演示账号可登录（居民 / 老年 / 网格）
  3. 居民 AI 对话：真实多智能体链路返回回复（意图 + 留痕）
  4. 政策问答：混合检索命中并给出可溯源答案
  5. 老年端首页：天气最高/最低温非空（B1 回归）+ 最近联系字段存在（P3-B）
  6. 网格工作台：自转率 / 红黑榜 / 知识库健康度 / 关怀指标均有数据（大屏与工作台不空）
  7. 知识图谱：按实体反查历史工单与政策（不是摆设）
  8. 全链路留痕：按 trace_id 能查到 Agent 日志

用法：python scripts/demo_acceptance.py            # 需服务已在 :8000 运行
退出码：0 = 全部通过；1 = 有失败项（并打印修复建议）
"""
import json
import os
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API = "http://127.0.0.1:8000"
FAILS: list[str] = []


def call(path: str, token: str = "", body: dict | None = None, method: str = "GET"):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def check(name: str, ok: bool, detail: str, fix: str = ""):
    mark = "✅" if ok else "❌"
    print(f"{mark} {name}：{detail}")
    if not ok:
        FAILS.append(f"{name} → {fix or detail}")


def login(role: str) -> tuple[str, dict]:
    st, body = call("/api/web/auth/demo", body={"role": role}, method="POST")
    data = (body or {}).get("data") or {}
    return (data.get("token") or ""), data


def main() -> int:
    print("=== 终局验收（真实服务 + 真实数据）===\n")

    # 1) 服务身份
    st, body = call("/api/web/health")
    svc = ((body or {}).get("data") or {}).get("service")
    check("服务身份", st == 200 and svc == "CommunityInsight Web",
          f"HTTP {st}，service={svc!r}",
          "端口可能被别的程序占用：netstat -ano | findstr :8000，然后重启主服务")

    # 2) 三角色登录
    tokens = {}
    for role, label in (("resident", "居民"), ("grid", "网格员"), ("elderly", "老年")):
        tk, data = login(role)
        tokens[role] = tk
        check(f"{label}端登录", bool(tk), f"用户={data.get('name')} 角色={data.get('role')}",
              "确认 DEMO_MODE=true 且种子数据已灌（init_db）")

    rh = {"resident": tokens.get("resident", ""), "grid": tokens.get("grid", ""),
          "elderly": tokens.get("elderly", "")}

    # 3) 居民 AI 对话（真实多智能体链路；注意字段名是 text）
    #    先发一次「算了」清掉遗留会话状态：演示账号是共享的，上一次对话可能停在追问态，
    #    会让本轮输入被当成"追问应答"→ 脚本出现假失败（与 ui_audit 依赖服务稳定同类问题）。
    call("/api/web/agent/chat", rh["resident"], {"text": "算了"}, "POST")
    st, body = call("/api/web/agent/chat", rh["resident"],
                    {"text": "我家阳台水管漏水了，水都流到楼下了"}, "POST")
    d = (body or {}).get("data") or {}
    reply = (d.get("reply") or "")
    if not reply:                     # 偶发限流/瞬时失败 → 退避重试一次，别把抖动当缺陷
        import time
        time.sleep(2.0)
        st, body = call("/api/web/agent/chat", rh["resident"],
                        {"text": "我家阳台水管漏水了"}, "POST")
        d = (body or {}).get("data") or {}
        reply = (d.get("reply") or "")
    check("居民 AI 对话（多智能体链路）", st == 200 and len(reply) >= 8,
          f"HTTP {st} 意图={d.get('intent')!r} 回复={reply[:42]!r}",
          "看服务日志的异常；或跑 python scripts/demo_collaboration.py 定位")

    # 4) 政策问答（混合检索 + 引用；路由前缀是 /api/web/qa）
    st, body = call("/api/web/qa/ask", rh["resident"], {"question": "医保怎么报销"}, "POST")
    p = (body or {}).get("data") or {}
    matched = bool(p.get("matched"))
    check("政策问答（检索命中）", st == 200 and matched and bool(p.get("answer")),
          f"HTTP {st} 命中={matched} 命中条目={str(p.get('title'))[:18]!r} "
          f"检索分={p.get('score')} 答案={str(p.get('answer'))[:30]!r}",
          "确认知识库已导入（scripts/import_kb_corpus.py）且检索阈值正常")

    # 5) 老年端首页（B1 天气温度 + P3-B 最近联系字段）
    st, body = call("/api/web/elderly/home", rh["elderly"])
    e = (body or {}).get("data") or {}
    w = e.get("weather") or {}
    ok_temp = w.get("temp_high") is not None and w.get("temp_low") is not None
    check("老年端天气高低温暖", st == 200 and ok_temp,
          f"{w.get('condition')} {w.get('temp_low')}°~{w.get('temp_high')}°",
          "回归：get_simplified_weather 必须同时返回 temp_high/temp_low")
    check("老年端首页字段齐全", "latest_contact" in e and "care_line" in e,
          f"问候={e.get('greeting')!r} 关怀={str(e.get('care_line'))[:24]!r} "
          f"最近联系={str(e.get('latest_contact'))[:20]!r}",
          "home payload 缺字段（前后端契约）")

    # 6) 网格工作台四类指标都有数据
    grid_ok = True
    details = []
    for path, key, label in (("/api/web/agent/self-resolution", "total_dialogs", "自转率"),
                             ("/api/web/agent/board", "red_board", "红黑榜"),
                             ("/api/web/agent/kb-health", "kb_total", "知识库健康度"),
                             ("/api/web/agent/care-metrics", "events", "关怀指标")):
        st, body = call(path, rh["grid"])
        dd = (body or {}).get("data") or {}
        has = st == 200 and bool(dd)
        grid_ok = grid_ok and has
        details.append(f"{label}={'有' if has else '空'}")
    check("网格工作台/大屏指标", grid_ok, "、".join(details),
          "对应数据层函数是否有数据（seed 是否灌入）")

    # 7) 知识图谱反查（断言"真的查到了东西"，不接受空结果算过）
    st, body = call("/api/web/agent/kg/entity?name=%E7%94%B5%E6%A2%AF", rh["grid"])
    kg = (body or {}).get("data") or {}
    n_issue = len(kg.get("related_issues") or [])
    n_kb = len(kg.get("related_knowledge") or [])
    check("知识图谱按实体反查（电梯）", st == 200 and bool(kg.get("found")) and (n_issue or n_kb),
          f"命中={kg.get('found')} 工单={n_issue} 政策={n_kb} 关联实体={len(kg.get('related_entities') or [])}",
          "跑 python scripts/rebuild_kg.py 重建图谱（或 POST /api/web/agent/kg/rebuild）")

    # 8) 留痕可追溯
    st, body = call("/api/web/agent/logs?limit=3", rh["grid"])
    logs = (body or {}).get("data") or []
    check("Agent 留痕可查（仲裁/校验落库）", st == 200 and isinstance(logs, list) and len(logs) > 0,
          f"最近 {len(logs)} 条 agent_logs",
          "正常：有对话后才会产生留痕；先跑一次居民对话")

    print(f"\n结果：{'全部通过，可以演示' if not FAILS else f'{len(FAILS)} 项待修复'}")
    for f in FAILS:
        print("  →", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
