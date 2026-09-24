# -*- coding: utf-8 -*-
"""按-id 直取越权（IDOR）收口 —— 多租户 B6 的契约测试。

**背景（实测复现过，不是假想）**：列表接口走了 SQL 里的 `tenant_id=?`，但**详情与操作接口
是按 id 直取单行的**——那条路径没有 WHERE 可加。原实现只校验角色（"是网格员就放行"），
于是朝阳试点社区的网格员拿自己的 JWT `GET /api/web/issues/352` 就能读到海淀小区工单全文
（`.shots/_tenant_idor_probe.py` 实测 HTTP 200 + 诉求正文）。

本文件三层守：
1. `test_row_in_tenant_*`：判定函数 `utils.tenant.row_in_tenant` 的 fail-closed 契约；
2. `test_*_cross_tenant_denied`：真建两个社区的行，按 id 调**路由函数**，断言跨租户被拒、
   同租户不受影响（防"一刀切全拒"）；
3. `test_all_by_id_routes_are_guarded`：**防锈闸**——用 AST 扫 `api_routes/*.py`，凡带路径参数
   的路由必须显式带 `_same_tenant`（或在白名单里写明豁免理由）。新加的按 id 路由漏了闸门会红。
"""
import ast
import json
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
UID_A = 96201
UID_B = 96202
GRID_A = 96211
GRID_B = 96212

_ROWS: dict[str, int] = {}      # 表名 → A 社区的行 id


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="tenant_idor_")
    path = os.path.join(tmp, "idor.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, community in (
                (UID_A, "resident", "A居民", A), (UID_B, "resident", "B居民", B),
                (GRID_A, "grid", "A网格", A), (GRID_B, "grid", "B网格", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, community))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    _build_rows()
    yield
    db_core._DB_PATH = _orig
    clear_cache()
    _ROWS.clear()


def _build_rows():
    """在 A 社区真建一条各类型数据（走业务写入函数，顺带验证"写入侧盖章"）。"""
    from data.db_repair import submit_issue
    from data.db_proposal import submit_proposal
    from data.db_health_content import submit_consult
    from data.db_notice import create_notice
    from data.db_policy import transfer_to_human
    from data.db_elderly_care import (add_emergency_contact, add_medication_reminder,
                                      log_emergency_call)
    from data.db_agent import create_handoff

    iid, _ = submit_issue(title="越权用例工单", category="公共设施", issue_type="室内",
                          location="1号楼", description="描述内容足够长", urgency="一般",
                          reporter_name="A居民", reporter_phone="13800000011", reporter_id=UID_A)
    _ROWS["community_issues"] = iid
    pid, _msg = submit_proposal(
        title="越权用例提案", description="这是一段足够长的提案描述内容", category="公共设施",
        reporter_name="A居民", reporter_phone="13800000012", is_public=1, reporter_id=UID_A)
    _ROWS["proposals"] = pid
    submit_consult(user_id=UID_A, name="A居民", phone="13800000013",
                   consult_type="健康知识", content="越权用例健康咨询内容")
    with db_core.get_db() as conn:
        _ROWS["health_consults"] = conn.execute(
            "SELECT id FROM health_consults WHERE user_id=? ORDER BY id DESC",
            (UID_A,)).fetchone()["id"]
    _ROWS["notices"] = create_notice(
        title="越权用例通知", notice_type="社区公告", publish_scope="全体居民",
        body="通知正文内容", elderly_summary="", publisher="A网格", publisher_id=GRID_A)
    # ask_question 只做匹配、不建行（匹配不到时返回 dict 让调用方去转人工），
    # 所以政策提问要经 transfer_to_human 建行（这也是"居民转人工"的真实路径）。
    _ok_x, _m, qid = transfer_to_human(user_id=UID_A, question="越权用例政策问题内容？",
                                      source="居民端", actor="A居民")
    _ROWS["policy_questions"] = qid
    mid, _ = add_medication_reminder(UID_A, patient_name="A老人", drug_name="A药", dosage="1片",
                                     times=["08:00"], setter_id=UID_A, start_date="2026-01-01")
    _ROWS["medication_reminders"] = mid
    cid, _ = add_emergency_contact(UID_A, name="A家属", phone="13800000014",
                                   relation="子女", setter_id=UID_A)
    _ROWS["emergency_contacts"] = cid
    _ROWS["emergency_calls"] = log_emergency_call(
        UID_A, call_type="sos", target_name="A家属", target_phone="13800000014")
    _ROWS["agent_handoffs"] = create_handoff(
        "sweep-session", UID_A, "resident", "其他", "越权用例转人工",
        {"original_input": "越权用例原始输入"})


def _req(uid, role, community):
    """最小可用 Request 替身（按 id 路由只用到 state.user / query_params）。"""
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"{community}{role}", "community": community,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _denied(res) -> bool:
    """路由返回统一响应：dict（_ok）或 JSONResponse（_fail）。"""
    if isinstance(res, dict):
        return not res.get("success")
    return not json.loads(bytes(res.body).decode("utf-8")).get("success")


def _err(res) -> str:
    if isinstance(res, dict):
        return res.get("error") or ""
    return json.loads(bytes(res.body).decode("utf-8")).get("error") or ""


# ---------------- 1. 判定函数契约（fail-closed） ----------------

def test_row_in_tenant_contract():
    from utils.tenant import row_in_tenant
    iid = _ROWS["community_issues"]
    assert row_in_tenant("community_issues", iid, A) is True
    assert row_in_tenant("community_issues", iid, B) is False, "跨租户必须为 False"
    assert row_in_tenant("community_issues", iid, "") is False, "空租户 → 拒绝（不许放行全量）"
    assert row_in_tenant("community_issues", iid, None) is False
    assert row_in_tenant("community_issues", iid, "海淀区") is False, "历史行政区值视为无效"
    assert row_in_tenant("community_issues", 99999999, A) is False, "行不存在 → 拒绝"
    assert row_in_tenant("community_issues", "abc", A) is False, "id 非法 → 拒绝"
    assert row_in_tenant("community_issues", -1, A) is False


def test_row_in_tenant_rejects_unknown_table():
    """表名要拼进 SQL，必须走白名单；写错要大声报错而不是静默放行。"""
    from utils.tenant import row_in_tenant
    with pytest.raises(ValueError):
        row_in_tenant("user_profile; DROP TABLE x", 1, A)


def test_tenant_tables_match_v48_migration():
    """白名单必须与 v48 迁移实际加列的表一致，避免"加了列但没进白名单"。"""
    from utils.tenant import TENANT_TABLES
    with db_core.get_db() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in TENANT_TABLES:
            assert t in tables, f"{t} 不在库里"
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
            assert "tenant_id" in cols, f"{t} 没有 tenant_id（v48 应加上）"


# ---------------- 2. 跨租户按 id 直取：逐接口断言 ----------------

_CASE_LABELS = [
    "工单详情", "工单管理动作", "提案详情", "提案投票", "提案议论列表", "提案管理动作",
    "健康咨询详情", "健康咨询回复", "通知详情", "通知管理动作", "政策提问回复",
    "政策提问删除", "用药提醒修改", "紧急联系人删除", "SOS 处置", "人工处理包关闭",
]


_ROW_TABLE = {
    "工单详情": "community_issues", "工单管理动作": "community_issues",
    "提案详情": "proposals", "提案投票": "proposals", "提案议论列表": "proposals",
    "提案管理动作": "proposals",
    "健康咨询详情": "health_consults", "健康咨询回复": "health_consults",
    "通知详情": "notices", "通知管理动作": "notices",
    "政策提问回复": "policy_questions", "政策提问删除": "policy_questions",
    "用药提醒修改": "medication_reminders", "紧急联系人删除": "emergency_contacts",
    "SOS 处置": "emergency_calls", "人工处理包关闭": "agent_handoffs",
}


def _case(label):
    """(说明, 表, 调用) —— 在**用例执行期**构造（收集期还没有数据行）。"""
    from api_routes import agent as agent_mod
    from api_routes import elderly as elderly_mod
    from api_routes import health as health_mod
    from api_routes import issues as issues_mod
    from api_routes import notices as notices_mod
    from api_routes import policy as policy_mod
    from api_routes import proposals as proposals_mod

    cases = {
        "工单详情": ("community_issues", lambda r: issues_mod.issue_detail(iid, r)),
        "工单管理动作": ("community_issues", lambda r: issues_mod.issue_action(
            iid, issues_mod.IssueAction(action="resolve"), r)),
        "提案详情": ("proposals", lambda r: proposals_mod.proposal_detail(pid, r)),
        "提案投票": ("proposals", lambda r: proposals_mod.proposal_vote(
            pid, proposals_mod.ProposalVote(score=5), r)),
        "提案议论列表": ("proposals", lambda r: proposals_mod.proposal_comments(pid, r)),
        "提案管理动作": ("proposals", lambda r: proposals_mod.proposal_action(
            pid, proposals_mod.ProposalAction(action="close"), r)),
        "健康咨询详情": ("health_consults", lambda r: health_mod.web_consult_detail(hid, r)),
        "健康咨询回复": ("health_consults", lambda r: health_mod.web_consult_reply(
            hid, health_mod.ConsultReply(reply="越权回复内容"), r)),
        "通知详情": ("notices", lambda r: notices_mod.web_notice_detail(nid, r)),
        "通知管理动作": ("notices", lambda r: notices_mod.web_notice_action(
            nid, notices_mod.NoticeAction(action="delete"), r)),
        "政策提问回复": ("policy_questions", lambda r: policy_mod.web_qa_reply(
            qid, policy_mod.QaReply(reply="越权回复内容"), r)),
        "政策提问删除": ("policy_questions", lambda r: policy_mod.web_qa_question_delete(qid, r)),
        "用药提醒修改": ("medication_reminders", lambda r: elderly_mod.web_medication_modify(
            rid, elderly_mod.MedicationCreate(drug_name="B药", dosage="2片", times="09:00"), r)),
        "紧急联系人删除": ("emergency_contacts", lambda r: elderly_mod.web_contacts_delete(ecid, r)),
        "SOS 处置": ("emergency_calls", lambda r: elderly_mod.web_sos_action(
            call_id, elderly_mod.SosAction(action="respond"), r)),
        "人工处理包关闭": ("agent_handoffs", lambda r: agent_mod.agent_handoff_resolve(handoff, r)),
    }
    # 绑定在函数内，保证每个 lambda 拿到的是本模块当前的 id（模块级 _ROWS）
    iid = _ROWS["community_issues"]
    pid = _ROWS["proposals"]
    hid = _ROWS["health_consults"]
    nid = _ROWS["notices"]
    qid = _ROWS["policy_questions"]
    rid = _ROWS["medication_reminders"]
    ecid = _ROWS["emergency_contacts"]
    call_id = _ROWS["emergency_calls"]
    handoff = _ROWS["agent_handoffs"]
    table, call = cases[label]
    return table, call


@pytest.mark.parametrize("label", _CASE_LABELS)
def test_cross_tenant_by_id_denied(label):
    """B 社区网格员按 id 直取 A 社区的行 → 必须被拒。"""
    _table, call = _case(label)
    res = call(_req(GRID_B, "grid", B))
    assert _denied(res), f"{label}：跨租户竟然成功了（越权！）"
    err = _err(res)
    assert ("非本社区" in err) or ("无权" in err) or ("不存在" in err), \
        f"{label}：拒绝理由不像权限拦截：{err!r}"


@pytest.mark.parametrize("label", _CASE_LABELS)
def test_same_tenant_by_id_not_blocked(label):
    """防"一刀切全拒"：A 社区网格员访问自己社区的行，闸门必须放行。

    ⚠️ 这里**故意不调用路由**（很多操作类接口会改状态，调了会破坏其他用例的数据），
    只断言闸门本身的判定——闸门放行 + 业务层各自的校验，才是完整的判定链。
    """
    from utils.tenant import row_in_tenant
    table = _ROW_TABLE[label]
    rid = _ROWS[table]
    assert row_in_tenant(table, rid, A) is True, f"{label}：同社区竟被闸门拦下（过度收紧）"
    assert row_in_tenant(table, rid, B) is False, f"{label}：跨社区竟被放行"


def test_same_tenant_readers_still_work():
    """同社区读接口的正常路径必须仍然可用（真读，断言拿到内容）。"""
    from api_routes import health as health_mod
    from api_routes import issues as issues_mod
    from api_routes import notices as notices_mod
    from api_routes import proposals as proposals_mod
    req = _req(GRID_A, "grid", A)
    for label, res in (
            ("工单详情", issues_mod.issue_detail(_ROWS["community_issues"], req)),
            ("提案详情", proposals_mod.proposal_detail(_ROWS["proposals"], req)),
            ("健康咨询详情", health_mod.web_consult_detail(_ROWS["health_consults"], req)),
            ("通知详情", notices_mod.web_notice_detail(_ROWS["notices"], req))):
        assert isinstance(res, dict) and res.get("success"), f"{label}同社区读取失败：{res}"
        assert res["data"], f"{label}返回空数据"


def test_empty_community_grid_denied():
    """身份解析不出社区（库里也没社区）→ fail-closed，不许放行。"""
    from api_routes import issues as issues_mod
    ghost = 96299
    with db_core.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                     "VALUES (?, ?, 'grid', '无社区网格', 1, '')", (ghost, f"u{ghost}"))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    res = issues_mod.issue_detail(_ROWS["community_issues"], _req(ghost, "grid", ""))
    assert _denied(res), "没有租户身份的网格员不应读到任何社区的数据"


def test_legacy_district_value_denied():
    """token 里是历史行政区值（'海淀区'）→ 归一化为空租户 → 拒绝（fail-closed）。"""
    from api_routes import issues as issues_mod
    res = issues_mod.issue_detail(_ROWS["community_issues"], _req(GRID_A, "grid", "海淀区"))
    assert _denied(res), "行政区是 v41 的历史口径，不能当租户用"


def test_resident_self_scope_still_denied_for_others():
    """居民自身范围不变：A 居民读不到 B 居民的单（原行为守住）。"""
    from api_routes import issues as issues_mod
    res = issues_mod.issue_detail(_ROWS["community_issues"], _req(UID_B, "resident", B))
    assert _denied(res)


# ---------------- 3. 防锈闸：按 id 路由必须带闸门 ----------------

# 豁免白名单：按 id 但**不需要** `_same_tenant` 的路由 → 必须写明理由（空理由视为未豁免）
_ID_ROUTE_EXEMPT = {
    ("issues.py", "issue_draft_delete"): "草稿表非租户表，且按本人 reporter_id 校验（他人草稿取不到）",
    ("proposals.py", "proposal_draft_delete"): "同上：草稿按本人校验",
    ("messages.py", "web_message_read"): "站内信按收件人 uid 自身范围校验（messages 非租户表）",
    ("health.py", "web_health_article_action"): "健康内容为全局知识库（health_contents 非租户表）",
    ("health.py", "web_health_article_detail"): "健康内容为全局知识库（health_contents 非租户表）",
    ("health.py", "web_health_linkage_action"): "联动记录按 link_key 自身范围，键内含社区 adcode",
    ("health.py", "web_consult_feedback"): "居民反馈自己的咨询：数据层 feedback_consult 校验 user_id",
    ("health.py", "web_consult_toggle"): "居民撤回/重开/关闭自己的咨询：数据层三个函数都校验 user_id",
    ("policy.py", "web_qa_feedback"): "居民反馈自己的提问：路由已校验 q.user_id == uid",
    ("policy.py", "web_knowledge_action"): "知识库为全局共享（knowledge_base 非租户表）",
    ("policy.py", "web_knowledge_versions"): "知识库为全局共享（knowledge_base 非租户表）",
    ("policy.py", "web_knowledge_new_version"): "知识库为全局共享（knowledge_base 非租户表）",
    ("agent.py", "agent_history_delete"): "对话记录按 uid 自身范围校验（delete_dialog 带 uid）",
    ("agent.py", "agent_trace_chain"): "trace_id 服务端生成不对外，agent_logs 已按 tenant 过滤",
    ("weather.py", "web_check_task_confirm"): "先按 tenant 过滤列表再定位任务，找不到即 1004",
    ("opinions.py", "web_opinion_convert"): "舆情源为全局采集框架（community_opinions 非租户表）",
}


def _by_id_routes():
    """扫 api_routes/*.py，返回 [(文件, 函数名, 路径, 函数源码)]（只取带 {参数} 的路由）。"""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api_routes")
    out = []
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(root, fn), encoding="utf-8").read()
        tree = ast.parse(src)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not hasattr(dec.func, "attr"):
                    continue
                if dec.func.attr not in ("get", "post", "put", "delete", "patch"):
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                path = str(dec.args[0].value)
                if "{" in path:
                    out.append((fn, node.name, path, ast.get_source_segment(src, node) or ""))
    return out


def test_all_by_id_routes_are_guarded():
    """凡带路径参数且判定了"能"的路由，必须显式带租户闸门（或白名单写明豁免）。

    这条是**防锈**用的：以后新加一个 `@router.get("/{id}")` 而忘了 `_same_tenant`，
    这里会直接红，而不是等到演示当天被人跨社区读走数据。
    """
    missing = []
    for fn, fname, path, body in _by_id_routes():
        if "_same_tenant(" in body:
            continue
        if (fn, fname) in _ID_ROUTE_EXEMPT and _ID_ROUTE_EXEMPT[(fn, fname)]:
            continue
        missing.append(f"{fn}::{fname}  {path}")
    assert not missing, (
        "以下按-id 路由既没有 _same_tenant 闸门，也没有豁免理由：\n  "
        + "\n  ".join(missing)
        + "\n（多租户 B6：按 id 直取的详情/操作接口必须校验行归属社区）")


def test_guarded_route_count_is_meaningful():
    """护栏本身别退化：带闸门的按 id 路由不能少于 15 条（漏改会在这里暴露）。"""
    guarded = [f"{fn}::{fname}" for fn, fname, _p, body in _by_id_routes() if "_same_tenant(" in body]
    assert len(guarded) >= 15, f"带租户闸门的按 id 路由只有 {len(guarded)} 条，疑似漏改：{guarded}"
