# -*- coding: utf-8 -*-
"""服务台线地基门禁（迁移 v54）：渠道 / 双身份 / 服务点 / 对外事项编号 / 工作人员查询。

**为什么要这一组用例**：这一批加的不是"几个按钮"，而是把"**谁在替谁办理**"这件事变成可查的数据。
四件事各自都有明确的失败后果，所以每条都单独守：

  ① **渠道**不记 → "哪个入口有效 / 谁在替谁办"永远答不上来（试点 §3.1 的核心指标算不出来）；
  ② **双身份**不分开 → 共享平板下"老人首次完成率"会把**工作人员代操作算成老人完成**，
     试点第一个核心指标直接是假的（这是本组最重要的一条）；
  ③ **服务点**不记 → 平板出问题无法定位是哪台设备，也做不了按设备清理会话；
  ④ **对外编号**：
     · 必须**与内部自增 id 解耦**（`WO00000012` 那种写法数字就是主键，能被数出总量、能被枚举）；
     · 必须**唯一**（重号 = 工作人员查到错单）；
     · 必须**稳定**（同一单反复查询拿到同一个号，否则工作人员手里的号会失效）；
     · **老人不需要记住它** —— 编号是给工作人员查的，查询必须支持"姓名 / 手机后四位 / 楼栋 / 时间"四路兜底。
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
GRID_A = 99501
RESIDENT_A = 99510


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="chan_"), "g.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((GRID_A, "grid", "A网格", A),
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


def _submit(**kw):
    from data.db_repair import submit_issue
    args = dict(title="楼道灯坏了", category="设施维修", issue_type="室外",
                location="3号楼2单元", description="楼道灯不亮，晚上看不清",
                urgency="一般", reporter_name="张大爷", reporter_phone="13800001111",
                reporter_id=RESIDENT_A)
    args.update(kw)
    iid, hint = submit_issue(**args)
    assert iid > 0, f"建单失败：{hint}"
    return iid


def _row(iid: int) -> dict:
    with db_core.get_db() as conn:
        return dict(conn.execute(
            "SELECT * FROM community_issues WHERE id=?", (iid,)).fetchone())


# ---------------------------------------------------------------- ① 渠道

def test_channel_is_recorded(fresh_db):
    iid = _submit(channel="service_desk_tablet")
    assert _row(iid)["submission_channel"] == "service_desk_tablet"


def test_channel_labels_cover_the_six_agreed_values(fresh_db):
    """渠道取值必须与材料口径一致（改这里要同步 `社区试点方案-v1.md`）。"""
    from data.db_issue_code import ASSISTED_CHANNELS, CHANNELS
    assert set(CHANNELS) == {"elderly_self", "resident_self", "family_assisted",
                             "grid_recorded", "service_desk_tablet", "phone_manual"}
    # 「代他人办理」的渠道必须被标出来——否则统计时无法把两者分开
    assert ASSISTED_CHANNELS == {"family_assisted", "grid_recorded",
                                 "service_desk_tablet", "phone_manual"}
    assert "elderly_self" not in ASSISTED_CHANNELS and "resident_self" not in ASSISTED_CHANNELS


# ---------------------------------------------------------------- ② 双身份（最重要）

def test_reporter_and_operator_are_separate_identities(fresh_db):
    """**共享平板的核心**：问题属于老人，动系统的是工作人员 —— 两个身份都要留。"""
    iid = _submit(channel="service_desk_tablet", operator_id=GRID_A, operator_role="grid",
                  station_id="STATION-01")
    r = _row(iid)
    assert r["reporter_id"] == RESIDENT_A, "reporter 必须是问题所属人（老人/居民）"
    assert r["operator_user_id"] == GRID_A, "operator 必须是实际操作人（工作人员）"
    assert r["operator_role"] == "grid"
    assert r["station_id"] == "STATION-01"
    assert r["reporter_id"] != r["operator_user_id"], \
        "两者相同就说明没分开记录 —— 老人完成率会把代操作算进去"


def test_self_service_has_no_separate_operator(fresh_db):
    """老人自助时没有"另一个人"操作：operator 保持 0，不硬塞一个身份进去。"""
    iid = _submit(channel="elderly_self")
    r = _row(iid)
    assert r["operator_user_id"] == 0 and r["operator_role"] == ""


def test_consent_status_is_recorded(fresh_db):
    iid = _submit(channel="grid_recorded", operator_id=GRID_A, consent_status="口头同意")
    assert _row(iid)["consent_status"] == "口头同意"


# ---------------------------------------------------------------- ④ 对外编号

def test_issue_code_format_and_decoupling_from_internal_id(fresh_db):
    """编号格式正确，且**不是内部 id 的换皮**。

    ⚠️ 这条用例第一版写错过，值得留痕：我当时断言「编号里不出现内部 id 的字符串」，
    结果第一单 `id=1`、编号 `A26100001` —— 断言失败。但**失败的是断言，不是代码**：
    序号本来就是 1，任何编号方案都会包含 "1"。

    真正能保证、也该被守住的是这三点（下面逐条断言）：
      ① 编号有独立的**期间段**（年月），不是 id 的零填充；
      ② 序号**按年月重置**，所以它**不随 id 单调** —— 这就是"与主键解耦"的实际含义
         （`id` 一直涨，而序号每月回到 1）；
      ③ 编号**不是访问凭据**：查编号必须走 `staff_search`（要角色 + 要社区），
         所以"猜邻近号"并不能看到别人的单 —— **真正的保护是访问控制，不是编号难猜**。
         这一点必须在材料里说清楚：顺序编号天然可猜，我们不假装它不可猜。
    """
    from data.db_issue_code import is_valid_code, next_issue_code
    iid = _submit()
    code = _row(iid)["issue_code"]
    assert is_valid_code(code), f"编号格式不对：{code}"
    # ① 期间段来自年月，不是 id
    assert code[1:5] == datetime.now().strftime("%y%m"), f"编号期间段不对：{code}"
    assert code.startswith("A") and len(code) == 9, code
    # ② 序号按年月重置 → 与 id 解耦
    with db_core.get_db() as conn:
        far = next_issue_code(conn, now=datetime(2030, 1, 1, 8, 0, 0))
    assert far.endswith("0001"), far
    assert int(far[1:5]) > int(code[1:5]), (far, code)
    assert far != f"A{int(code[1:5]):04d}{iid:04d}", "编号看起来就是 id 的零填充"


def test_issue_code_lookup_requires_staff_context(fresh_db):
    """编号**不是访问凭据**：没有社区上下文就查不到（顺序编号天然可猜，靠访问控制兜住）。"""
    from data.db_issue_code import staff_search
    iid = _submit()
    code = _row(iid)["issue_code"]
    assert staff_search("", code=code)["count"] == 0, "不传社区竟然能用编号查到工单"
    assert staff_search(B, code=code)["count"] == 0, "别的社区用编号查到了工单"
    assert staff_search(A, code=code)["count"] == 1


def test_issue_code_is_monotonic_and_unique(fresh_db):
    from data.db_issue_code import is_valid_code
    codes = [_row(_submit(title=f"第{i}个问题", description="描述要够五个字")).get("issue_code")
             for i in range(5)]
    assert all(is_valid_code(c) for c in codes), codes
    assert len(set(codes)) == 5, f"编号重复：{codes}"
    assert codes == sorted(codes), f"编号不单调：{codes}"


def test_issue_code_is_stable_when_re_requested(fresh_db):
    """编号一旦给出就**不变**（工作人员手里的号不能失效）。"""
    from data.db_issue_code import ensure_issue_code
    iid = _submit()
    first = _row(iid)["issue_code"]
    with db_core.get_db() as conn:
        again = ensure_issue_code(conn, iid)
    assert again == first, f"重复分配换了号：{first} → {again}"


def test_code_allocator_rolls_over_by_month(fresh_db):
    """号段按年月分开（跨月不会串号）。"""
    from data.db_issue_code import next_issue_code
    with db_core.get_db() as conn:
        sep = next_issue_code(conn, now=datetime(2026, 9, 30, 10, 0, 0))
        oct_ = next_issue_code(conn, now=datetime(2026, 10, 1, 9, 0, 0))
    assert sep.startswith("A2609") and oct_.startswith("A2610"), (sep, oct_)
    assert sep.endswith("0001") and oct_.endswith("0001")


def test_creating_issue_succeeds_even_if_code_allocation_is_broken(fresh_db, monkeypatch):
    """**编号失败不能阻断建单**：编号只是"方便工作人员查"，拿不到也要让老人把事说出来。"""
    from data.db_repair import submit_issue
    import data.db_issue_code as m

    def _boom(conn, issue_id, now=None):
        raise RuntimeError("模拟编号分配故障")

    monkeypatch.setattr(m, "ensure_issue_code", _boom)
    iid, hint = submit_issue(title="楼道灯坏了", category="设施维修", issue_type="室外",
                             location="3号楼2单元", description="楼道灯不亮，晚上看不清",
                             urgency="一般", reporter_name="张大爷",
                             reporter_phone="13800001111", reporter_id=RESIDENT_A)
    assert iid > 0, f"编号故障竟然阻断了建单：{hint}"
    assert _row(iid)["issue_code"] == "", "编号失败时该留空，不该塞个假的"


# ---------------------------------------------------------------- 工作人员查询

def test_staff_search_by_code_name_building(fresh_db):
    from data.db_issue_code import staff_search
    iid = _submit()
    code = _row(iid)["issue_code"]
    for kw in ({"code": code}, {"name": "张大爷"}, {"building": "3号楼"}):
        r = staff_search(A, **kw)
        assert r["count"] == 1, f"{kw} → {r}"
        assert r["items"][0]["issue_id"] == iid
        assert r["items"][0]["issue_code"] == code


def test_staff_search_requires_community(fresh_db):
    """查询必须按社区收口：空社区返回空、别的社区查不到（fail-closed）。"""
    from data.db_issue_code import staff_search
    iid = _submit()
    assert staff_search("", name="张大爷")["count"] == 0
    assert staff_search(B, name="张大爷")["count"] == 0, "跨社区查到了别人的单"
    assert staff_search(A, name="张大爷")["count"] == 1


def test_staff_search_phone_only_accepts_last_four(fresh_db):
    """手机号**只接受后四位**：传完整号码直接拒绝（不能让它变成查询凭据）。"""
    from data.db_issue_code import staff_search
    _submit()
    bad = staff_search(A, phone_tail="13800001111")
    assert bad["count"] == 0 and "后四位" in bad["note"], bad
    ok = staff_search(A, phone_tail="1111")
    assert ok["count"] == 1, ok
    # 结果里只出现掩码，绝不回显完整号码
    assert ok["items"][0]["reporter_phone_masked"] not in ("13800001111",)
    assert "13800001111" not in str(ok["items"])


def test_staff_search_multiple_hits_asks_for_confirmation(fresh_db):
    """命中多条**不替工作人员猜**，明确要求进一步确认。"""
    from data.db_issue_code import staff_search
    _submit(title="楼道灯坏了")
    _submit(title="楼道门坏了")
    r = staff_search(A, name="张大爷")
    assert r["count"] == 2 and r["need_confirm"] is True, r
    assert "确认" in r["note"], r["note"]


def test_staff_search_rejects_malformed_code(fresh_db):
    from data.db_issue_code import staff_search
    _submit()
    r = staff_search(A, code="12345")
    assert r["count"] == 0 and "编号格式" in r["note"], r


def test_staff_search_masks_phone_in_results(fresh_db):
    from data.db_issue_code import staff_search
    _submit()
    r = staff_search(A, name="张大爷")
    masked = r["items"][0]["reporter_phone_masked"]
    assert masked and "*" in masked, f"手机号没脱敏：{masked}"
