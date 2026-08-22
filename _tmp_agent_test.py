# -*- coding: utf-8 -*-
"""Agent 引擎功能验证（不依赖服务）。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.database import init_db
init_db(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "community.db"))

from agent import web_agent as A
from agent.web_agent_service import handle_chat, _clear

# 1. 意图识别
assert A.detect_intent("我家水管漏水了") == "报修", A.detect_intent("我家水管漏水了")
assert A.detect_intent("我想提个建议，社区多装路灯") == "提案"
assert A.detect_intent("医保怎么报销") == "政策问答"
assert A.detect_intent("最近有什么通知") == "通知查询"
assert A.detect_intent("今天天气怎么样") == "天气查询"
assert A.detect_intent("帮我联系社区") == "联系社区"
assert A.detect_intent("你们这个怎么用") == "使用帮助"
assert A.detect_intent("你是谁") == "自我介绍"
assert A.detect_intent("我要取消报修") == "撤回引导"
assert A.detect_intent("今天有什么待办", "grid") == "待办提醒"
assert A.detect_intent("导出本月工单", "grid") == "导出数据"
assert A.detect_intent("我不舒服", "elderly") == "身体不适"
print("意图识别 OK")

# 2. 纠错
assert A.correct_text("我加水管漏水") == "我家水管漏水", A.correct_text("我加水管漏水")
assert A.correct_text("楼道等不亮了") == "楼道灯不亮了", A.correct_text("楼道等不亮了")
assert A.correct_text("那个水哗哗的快点来") == "那个水管哗哗的快点来"
print("纠错 OK")

# 3. 紧急/情绪/礼貌
assert A.detect_emergency("水哗哗的，快点来") is True
assert A.detect_emotion("还不来，你们管不管") is True
assert A.detect_polite("谢谢你们") is True
assert A.detect_go_out("我要出门") is True
print("紧急/情绪/礼貌 OK")

# 4. 报修完整流程（状态机）
uid, name = 99901, "测试居民"
_clear("resident", uid)
r1 = handle_chat("resident", uid, name, "我家水管漏水了")
print("R1:", r1["intent"], "|", r1["reply"], "|", r1["actions"])
assert r1["status"] == "追问" and r1["intent"] == "报修"
r2 = handle_chat("resident", uid, name, "家里")
print("R2:", r2["reply"])
r3 = handle_chat("resident", uid, name, "紧急")
print("R3:", r3["reply"])
assert r3["status"] == "需确认"
r4 = handle_chat("resident", uid, name, "确认提交")
print("R4:", r4["reply"], "related=", r4["related_id"])
assert r4["status"] == "成功" and r4["related_id"]
print("报修闭环 OK")

# 5. 纠错确认流程
_clear("resident", uid)
r = handle_chat("resident", uid, name, "我加水管漏水")
print("纠错确认:", r["reply"], r["status"])
assert r["status"] == "需确认" and r["intent"] == "纠正确认"
r2 = handle_chat("resident", uid, name, "对")
print("确认后:", r2["reply"])
assert r2["intent"] == "报修"
print("纠错确认流程 OK")

# 6. 政策/天气/通知/联系社区（各自清会话）
for q, exp in [("医保怎么报销", "政策问答"), ("今天天气怎么样", "天气查询"),
               ("最近有什么通知", "通知查询"), ("帮我联系社区", "联系社区")]:
    _clear("resident", uid)
    r = handle_chat("resident", uid, name, q)
    print(f"{q} → {r['intent']} | {r['reply'][:50]}")
    assert r["intent"] == exp

# 7. 负责人端
_clear("grid", uid)
r = handle_chat("grid", uid, name, "今天有什么待办")
print("待办:", r["reply"])
assert "待办" in r["reply"]
r = handle_chat("grid", uid, name, "导出本月工单")
print("导出:", r["reply"], r["status"])
r = handle_chat("grid", uid, name, "确认")
print("导出确认:", r["reply"], r["actions"])
assert r["actions"] and r["actions"][0]["type"] == "download"
r = handle_chat("grid", uid, name, "本周工单统计")
print("统计:", r["reply"][:80])
r = handle_chat("grid", uid, name, "打开待审核工单")
print("跳转:", r["actions"])
print("负责人端 OK")

# 8. 老年端
_clear("elderly", uid)
r = handle_chat("elderly", uid, name, "我不舒服")
print("老年不适:", r["intent"], r["reply"][:50])
assert r["intent"] == "身体不适"
_clear("elderly", uid)
r = handle_chat("elderly", uid, name, "家里灯不亮了")
print("老年报修:", r["intent"], r["reply"][:60], r["status"])
assert r["intent"] == "报修" and r["status"] == "需确认"
r = handle_chat("elderly", uid, name, "确认提交")
print("老年提交:", r["reply"][:50], r["status"])
assert r["status"] == "成功"
print("老年端 OK")

# 9. 越权（文档第八问：居民不能导出/审核）
assert A.detect_intent("导出所有数据") is None  # 居民关键词表无导出
print("越权防护 OK")

print("\n全部 Agent 引擎验证通过 ✅")
