# -*- coding: utf-8 -*-
"""「系统建议分类 vs 人工最终分类」门禁（收敛方案第 6–7 阶段）。

**为什么要这组用例**：这两个阶段解决的是一句很容易变成假话的话——
"我们的自动分类挺准的"。这句话要成立，必须同时满足三件事，缺一件就是口径造假：

  ① **写入侧真的写了**（第 6 阶段）：基线核对时 `community_issues.suggested_category`
     285 条**全部为空**——也就是"系统建议"这一列根本没有数据，
     那么任何"建议 vs 最终"的对照表都只有右半边。
  ② **两列语义真的分开**：`category` 是当前生效分类（网格员可改），
     `suggested_category` 是系统当初的建议（不随人工修改而变）。
     如果两者总是一起被改，对照表就永远显示"100% 一致"——那是**字段设计导致的假一致**。
  ③ **覆盖率必须能报出来**：第 6 阶段才补的写入侧，历史单为空是正常的，
     所以要看的是"有建议的条数 / 总条数"，而不是只报一致率。

第 7 阶段还守两条：
  ④ 改动的人和时间要能从留痕里追出来；
  ⑤ 分类变了却**没有留痕** = 有绕过 `update_issue_category` 的写入路径 → 报出来（`unlogged_changes`）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
GRID_A = 99601
GRID_B = 99602
RESIDENT_A = 99610


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="catcorr_"), "g.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((GRID_A, "grid", "A网格", A),
                                     (GRID_B, "grid", "B网格", B),
                                     (RESIDENT_A, "resident", "A居民", A)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _submit(title, suggested="", category="公共设施", reporter=RESIDENT_A, tenant=A):
    from data.db_repair import submit_issue
    iid, _hint = submit_issue(
        title=title, category=category, issue_type="室外", location="3号楼2单元",
        description=f"{title}（描述）", urgency="一般", reporter_name="测试居民",
        reporter_phone="13800001111", reporter_id=reporter, suggested_category=suggested)
    assert iid > 0, "建单失败"
    with db_core.get_db() as conn:
        conn.execute("UPDATE community_issues SET tenant_id=? WHERE id=?", (tenant, iid))
        conn.commit()
    return iid


def _row(iid):
    with db_core.get_db() as conn:
        return dict(conn.execute(
            "SELECT category, suggested_category FROM community_issues WHERE id=?",
            (iid,)).fetchone())


# ---------------------------------------------------------------- ① 写入侧

def test_submit_writes_suggested_category(fresh_db):
    """提交时把**系统建议**落库（第 6 阶段的核心：这一列以前 285 条全空）。"""
    iid = _submit("楼道灯坏了", suggested="设施维修")
    r = _row(iid)
    assert r["suggested_category"] == "设施维修", r
    assert r["category"] == "公共设施", r


def test_no_system_suggestion_stays_empty(fresh_db):
    """没有系统建议时（居民自己选分类）**保持空**，不许把人工选择冒充成系统命中。"""
    iid = _submit("楼道灯坏了", suggested="")
    assert _row(iid)["suggested_category"] == ""


def test_two_columns_are_independent(fresh_db):
    """② 语义分开：人工改分类只动 `category`，`suggested_category` 保持系统原值。

    这是整张对照表能不能成立的前提——如果一起被改，表里永远显示"100% 一致"，
    那是字段设计造出来的假一致，不是系统真的准。
    """
    from data.db_repair import update_issue_category
    iid = _submit("垃圾桶满了没人清", suggested="环境卫生", category="环境卫生")
    assert _row(iid) == {"category": "环境卫生", "suggested_category": "环境卫生"}
    ok, msg = update_issue_category(iid, "物业服务", actor="A网格")
    assert ok, msg
    r = _row(iid)
    assert r["category"] == "物业服务", "人工修改没生效"
    assert r["suggested_category"] == "环境卫生", "系统建议被人工修改覆盖掉了（对照表会失真）"


def test_tool_path_records_llm_suggestion(fresh_db, monkeypatch):
    """Agent 工具链路：走了自动分类就把结果记为系统建议；走"两值都给"的快路径则不算。

    ⚠️ 姿态必须钉住（项目纪律：测试要姿态无关）：`_llm_classify` 会**真打网络**，
    本机 `.env` 开着 key 时这条会走 LLM（慢、且网络抖动会假失败）。
    这里把 key 置空 → 确定性走关键词兜底，测的是"是否记为系统建议"，与分类器实现无关。
    """
    import config as _cfg
    monkeypatch.setattr(_cfg, "DEEPSEEK_API_KEY", "", raising=False)
    from tools.action_report_issue import report_issue
    # `report_issue` 是 langchain 的 StructuredTool（`@tool` 装饰），要取 `.func` 才是真函数。
    # ⚠️ 位置必须过 `validate_location`（要"小区/院落 + 楼栋单元房号"）：
    # 只写"3号楼2单元"会被拒（返回"报修地址请填写…"），**不建单**，测试会拿到空表。
    fn = getattr(report_issue, "func", report_issue)
    fn(title="幸福小区3号楼2单元楼道灯坏了需要维修", location="幸福小区3号楼2单元",
       description="灯不亮，晚上上下楼看不清", reporter_name="测试居民",
       reporter_phone="13800001111")
    with db_core.get_db() as conn:
        row = dict(conn.execute(
            "SELECT category, suggested_category FROM community_issues ORDER BY id DESC LIMIT 1"
        ).fetchone())
    assert row["suggested_category"], "自动分类的结果没有落成系统建议"
    assert row["suggested_category"] == row["category"], "刚建单时两者应相等（还没人改）"

    # 快路径：分类与紧急程度都由调用方给（例如安全网传的）→ 没有"系统建议"这回事
    fn = getattr(report_issue, "func", report_issue)
    fn(title="幸福小区5号楼1单元灯具破损", location="幸福小区5号楼1单元",
       description="灯具破损有掉落风险", category="安全隐患", urgency="紧急",
       reporter_name="测试居民", reporter_phone="13800001111")
    with db_core.get_db() as conn:
        row2 = dict(conn.execute(
            "SELECT category, suggested_category FROM community_issues ORDER BY id DESC LIMIT 1"
        ).fetchone())
    assert row2["category"] == "安全隐患"
    assert row2["suggested_category"] == "", \
        "调方给的分类不是系统建议，不许记成系统命中（否则一致率会虚高）"


# ---------------------------------------------------------------- ③ 覆盖率

def test_coverage_is_reported_and_honest(fresh_db):
    """覆盖率必须显示：历史单（无建议）算 `no_suggestion`，**不算**成"系统建议正确"。"""
    from data.db_issue_knowledge import category_corrections
    _submit("有建议的单", suggested="设施维修", category="设施维修")
    _submit("历史单没有建议", suggested="")
    _submit("历史单没有建议2", suggested="")
    r = category_corrections(days=180, tenant=A)
    assert r["total"] == 3
    assert r["with_suggestion"] == 1
    assert r["no_suggestion"] == 2, "历史单必须单独计数"
    assert r["coverage"] == pytest.approx(33.3, abs=0.2), r["coverage"]
    assert r["agreed"] == 1 and r["corrected"] == 0
    assert r["agreement_rate"] == 100.0
    assert r["sample_enough"] is False, "只有 1 条有建议 → 必须标样本不足"
    assert "样本不足" in r["note"], r["note"]


def test_empty_suggestion_list_explains_itself(fresh_db):
    """一条系统建议都没有时，说明"清单为空是预期的"（别让人以为坏了）。"""
    from data.db_issue_knowledge import category_corrections
    _submit("历史单", suggested="")
    r = category_corrections(days=180, tenant=A)
    assert r["with_suggestion"] == 0 and r["coverage"] == 0.0
    assert "预期" in r["note"] and "第 6 阶段" in r["note"], r["note"]


# ---------------------------------------------------------------- ④⑤ 留痕与异常

def test_correction_records_who_and_when(fresh_db):
    """改过的条目要能追出**谁在什么时候改的**（从 activity_log），并给出建议→最终的配对。"""
    from data.db_issue_knowledge import category_corrections
    from data.db_repair import update_issue_category
    iid = _submit("垃圾桶满了", suggested="环境卫生", category="环境卫生")
    update_issue_category(iid, "物业服务", actor="A网格")
    r = category_corrections(days=180, tenant=A)
    assert r["corrected"] == 1 and r["agreed"] == 0
    assert r["corrected_rate"] == 100.0
    assert r["pairs"] == [{"suggested": "环境卫生", "final": "物业服务", "count": 1}], r["pairs"]
    item = next(i for i in r["items"] if i["issue_id"] == iid)
    assert item["changed"] is True
    assert item["changed_by"] == "A网格", item
    assert item["changed_at"], "没有改动时间（留痕没读到）"
    assert r["unlogged_changes"] == 0


def test_silent_category_change_is_flagged(fresh_db):
    """绕过 `update_issue_category` 直接改分类（分类变了但无留痕）必须被**报出来**。

    这条守的是"留痕是真的还是摆设"：如果有别的写入路径能改分类而不留痕，
    那么"改动可追溯"这句话就是假的，必须让它在清单里露头。
    """
    from data.db_issue_knowledge import category_corrections
    iid = _submit("被偷偷改过的单", suggested="环境卫生", category="环境卫生")
    with db_core.get_db() as conn:          # 模拟"绕过受控入口"的写入
        conn.execute("UPDATE community_issues SET category='其他' WHERE id=?", (iid,))
        conn.commit()
    r = category_corrections(days=180, tenant=A)
    assert r["corrected"] == 1
    assert r["unlogged_changes"] == 1, "分类变了却没有留痕，竟然没被报出来"
    item = next(i for i in r["items"] if i["issue_id"] == iid)
    assert item["changed"] is True and item["changed_by"] == ""


def test_list_is_tenant_scoped(fresh_db):
    """A 社区的对照清单里不能出现 B 社区的单（派生清单同样要按社区收口）。"""
    from data.db_issue_knowledge import category_corrections
    _submit("A 社区的单", suggested="设施维修", category="设施维修", reporter=RESIDENT_A, tenant=A)
    r_b = category_corrections(days=180, tenant=B)
    assert r_b["total"] == 0 and r_b["items"] == []
    r_none = category_corrections(days=180, tenant="")
    assert r_none["total"] == 0 and "缺少社区归属" in r_none["note"], r_none["note"]


def test_lists_are_desensitized_and_not_for_training(fresh_db):
    """脱敏 + 口径：清单里不许出现手机号；必须写明"不用于模型训练"。"""
    from data.db_issue_knowledge import category_corrections
    _submit("漏水了联系我13800001111", suggested="设施维修", category="设施维修")
    r = category_corrections(days=180, tenant=A)
    assert "13800001111" not in str(r["items"]), "清单里出现了完整手机号"
    assert "不用于模型训练" in r["disclaimer"], r["disclaimer"]


# ---------------------------------------------------------------- 接口层

def _req(uid, role="grid", com=A):
    from types import SimpleNamespace
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"n{uid}", "community": com,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _code(r) -> int:
    """`_ok` 返回 dict、`_fail`/`_require_role` 返回 JSONResponse —— 统一取 code。"""
    if isinstance(r, dict):
        return int(r.get("code", -1))
    try:
        import json
        return int(json.loads(r.body.decode("utf-8")).get("code", -1))
    except Exception:  # noqa: BLE001
        return -1


def test_route_requires_grid_and_scopes(fresh_db):
    """接口是网格员专用，且按调用者身份取社区。"""
    from api_routes.issues import issue_category_corrections
    _submit("A 社区的单", suggested="设施维修", category="设施维修")
    r = issue_category_corrections(_req(GRID_A), days=180, limit=50)
    assert r["code"] == 0 and r["data"]["total"] == 1
    assert _code(issue_category_corrections(_req(RESIDENT_A, "resident"), days=180, limit=50)) != 0
    rb = issue_category_corrections(_req(GRID_B, com=B), days=180, limit=50)
    assert rb["data"]["total"] == 0


def test_route_limit_is_clamped(fresh_db):
    """`limit` 钳在 1–200（清单是给人看的，不给人拉全库）。"""
    from api_routes.issues import issue_category_corrections
    for i in range(6):
        _submit(f"单{i}", suggested="设施维修", category="设施维修")
    r = issue_category_corrections(_req(GRID_A), days=180, limit=2)
    assert len(r["data"]["items"]) == 2
    r2 = issue_category_corrections(_req(GRID_A), days=180, limit=200)
    assert len(r2["data"]["items"]) == 6


# --------------------------------------------------------------------------------
# v53：**演示数据必须能被认出来**（外部复核 P2）
#
# 为了让对照样本多一点，我们用 seed 脚本走真实链路造过演示工单。它们是真的
# （真实接口/真实分类/真实留痕）但**不是真实居民诉求**。不标记 → 会和真实工单混进同一个分母，
# 于是"覆盖率/一致率"里掺了自造数据而材料上不写 —— 那正是本项目最忌讳的
# "数字看着是真的、其实是自造的"。
# --------------------------------------------------------------------------------

def test_demo_flag_is_separated_from_real_data(fresh_db):
    """演示数据与真实数据必须**分开报**（三个分母：total / real / demo）。"""
    from data.db_issue_knowledge import category_corrections
    from data.db_repair import submit_issue
    # 3 条真实 + 2 条演示（演示的走同一个提交入口，只是带 is_demo=1）
    for i in range(3):
        _submit(f"真实单{i}", suggested="设施维修", category="设施维修")
    for i in range(2):
        # ⚠️ description 有"至少 5 个字"的校验（实测踩到：写成"演示数据"会被如实拦下）
        iid, hint = submit_issue(
            title=f"演示单{i}", category="环境卫生", issue_type="室外",
            location="3号楼2单元", description="这是一条演示用的诉求描述", urgency="一般",
            reporter_name="演示居民", reporter_phone="13800002222",
            reporter_id=RESIDENT_A, suggested_category="环境卫生", is_demo=1)
        assert iid > 0, f"演示单没建成：{hint}"
        with db_core.get_db() as conn:
            conn.execute("UPDATE community_issues SET tenant_id=? WHERE id=?", (A, iid))
            conn.commit()
    r = category_corrections(days=180, tenant=A)
    assert r["total"] == 5
    assert r["demo"]["total"] == 2, r["demo"]
    assert r["real"]["total"] == 3, r["real"]
    assert r["demo"]["with_suggestion"] == 2 and r["real"]["with_suggestion"] == 3
    # 免责声明由数据驱动：分母里有演示数据就必须出现那三条
    assert "不代表真实居民样本" in r["demo_note"]
    assert "不用于模型训练" in r["demo_note"]
    assert "不代表线上准确率" in r["demo_note"]
    # ⚠️ 不许把"未标记"那部分叫成"真实居民数据"（演示库里那些同样来自演示/验证脚本）
    assert "真实来源工单" not in r["demo_note"], r["demo_note"]
    assert "未标记" in r["demo_note"], r["demo_note"]
    # 明细也要标出哪条是演示，别让人自己猜
    demo_items = [i for i in r["items"] if i["is_demo"]]
    assert len(demo_items) == 2, r["items"]


def test_demo_flag_defaults_off_and_demo_note_empty(fresh_db):
    """默认不是演示数据；没有演示数据时免责声明为空（不能变成常驻噪音）。"""
    from data.db_issue_knowledge import category_corrections
    _submit("真实单", suggested="设施维修", category="设施维修")
    r = category_corrections(days=180, tenant=A)
    assert r["demo"]["total"] == 0 and r["real"]["total"] == 1
    assert r["demo_note"] == "", r["demo_note"]


def test_demo_flag_only_honoured_in_demo_mode(fresh_db, monkeypatch):
    """**安全闸**：`mark_as_demo` 只在 `DEMO_MODE` 生效，生产姿态必须忽略。

    为什么要这道闸：这个标记是"把自造样本从真实样本里剔除"的依据。
    生产环境也能随便标，就等于开了一条"把真实工单伪装成演示数据（或反过来）"的路，
    统计口径可以被调用方改写。所以这里直接调真函数验证两个姿态，而不是读源码猜。
    """
    import config as _cfg
    from api_routes.elderly import _demo_flag
    monkeypatch.setattr(_cfg, "DEMO_MODE", True, raising=False)
    assert _demo_flag(True, 1) == 1, "演示姿态下标记应当生效"
    assert _demo_flag(False, 1) == 0, "不传就不该标"
    monkeypatch.setattr(_cfg, "DEMO_MODE", False, raising=False)
    assert _demo_flag(True, 1) == 0, "生产姿态竟然允许把工单标成演示数据（口径可被改写）"
    assert _demo_flag(False, 1) == 0
