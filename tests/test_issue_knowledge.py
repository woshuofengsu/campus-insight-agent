# -*- coding: utf-8 -*-
"""工单知识沉淀（v52）：**字段来源落库** + **同类处置画像可查询**（v4 §6 B 栏最后一条工程活）。

守三件事：
  ① 提交时的"字段 → 来源"真的**存进库**了（不是只在页面上闪一下），且只收白名单里的值
     （这张表是拿来做"不许编造"事后审计的，脏值比空值更危险）；
  ② 同类处置画像的数字**来自真实记录**：办结率、平均时长、超时率、第三方占比、常见责任方、常见处置词；
     样本量低于阈值必须**如实标注**"样本不足"，不让人拿两条记录当规律；
  ③ 一律按 `tenant` 收口：空租户返回空结构，绝不查全库；跨社区的工单查不到。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
RESIDENT_A = 99701
GRID_A = 99711
GRID_B = 99712


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="issuekb_"), "k.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((RESIDENT_A, "resident", "A居民", A),
                                     (GRID_A, "grid", "A网格", A),
                                     (GRID_B, "grid", "B网格", B)):
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
    base = dict(title="楼道灯坏了", category="公共设施", issue_type="室外",
                location="3号楼2单元", description="楼道灯不亮，晚上看不见", urgency="一般",
                reporter_name="A居民", reporter_phone="13800001111", reporter_id=RESIDENT_A)
    base.update(kw)
    return submit_issue(**base)


def test_submit_persists_field_sources(fresh_db):
    """字段来源真的落库了，而且**只保留白名单里的键值**。"""
    iid, hint = _submit(field_sources={"location": "user", "title": "text",
                                       "urgency": "suggestion", "scope": "default",
                                       "胡说八道": "user", "location2": "乱写"})
    assert iid > 0 and hint == "ok"
    with db_core.get_db() as conn:
        raw = conn.execute("SELECT field_sources FROM community_issues WHERE id=?",
                           (iid,)).fetchone()["field_sources"]
    assert raw, "字段来源没有被写进库"
    from data.db_issue_knowledge import issue_field_sources
    r = issue_field_sources(iid, tenant=A)
    assert r["sources"] == {"title": "text", "location": "user",
                            "scope": "default", "urgency": "suggestion"}, r["sources"]
    assert "胡说八道" not in raw and "location2" not in raw, "白名单没起作用（脏值进库了）"


def test_submit_without_sources_says_so_honestly(fresh_db):
    """网页表单直接填写的单没有来源记录 → 要**如实说明**，不能编一个默认来源。"""
    iid, _ = _submit()
    from data.db_issue_knowledge import issue_field_sources
    r = issue_field_sources(iid, tenant=A)
    assert r["sources"] == {}
    assert "没有字段来源记录" in r["note"], r


def test_field_sources_are_tenant_scoped(fresh_db):
    """跨社区查不到字段来源（读取侧 fail-closed）。"""
    iid, _ = _submit(field_sources={"location": "user"})
    from data.db_issue_knowledge import issue_field_sources
    assert issue_field_sources(iid, tenant=B)["sources"] == {}, "B 社区读到了 A 社区的工单"
    assert "不属于本社区" in issue_field_sources(iid, tenant=B)["note"]
    assert issue_field_sources(iid, tenant="")["sources"] == {}, "空租户必须返回空"


def _seed_resolved(n: int, *, third_party: int = 0, overdue: int = 0, days_ago: int = 1):
    """造 n 条已办结工单（带处置说明与责任方），用于核画像数字。"""
    with db_core.get_db() as conn:
        for i in range(n):
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, status, "
                "reporter_id, reported_at, resolved_at, escalated_at, assignee_name, resolve_note, "
                "non_community_responsibility, tenant_id) VALUES "
                "(?,?,?,?,?,?, datetime('now', ?), datetime('now', ?), ?, ?, ?, ?, ?)",
                (f"灯泡不亮#{i}", "公共设施", "3号楼", "灯不亮", "处理结束", RESIDENT_A,
                 f"-{days_ago + 1} days", f"-{days_ago} days",
                 f"-{days_ago} days" if i < overdue else None,
                 "王师傅", "已更换灯泡，联系物业巡检同楼层线路", 1 if i < third_party else 0, A))
        conn.commit()


def test_category_profile_numbers_come_from_records(fresh_db):
    """画像的每个数字都要能从记录里对上（不许是拍脑袋的估算）。"""
    _seed_resolved(10, third_party=2, overdue=3, days_ago=1)   # 每条 24h
    from data.db_issue_knowledge import category_profile
    p = category_profile(category="公共设施", days=180, tenant=A)
    assert p["total"] == 10 and p["resolved"] == 10
    assert p["resolved_rate"] == 100.0
    assert 23.0 <= (p["avg_hours"] or 0) <= 25.0, p["avg_hours"]      # 24h ± 容差
    assert p["overdue"] == 3 and p["overdue_rate"] == 30.0
    assert p["third_party"] == 2 and p["third_party_rate"] == 20.0
    assert p["top_assignees"][0]["name"] == "王师傅"
    assert p["sample_enough"] is True and p["note"] == ""
    assert any("灯泡" in k[0] or "更换" in k[0] for k in p["top_keywords"]), p["top_keywords"]
    # 分类分布用于下拉（不受 category 过滤影响）
    assert any(c["category"] == "公共设施" for c in p["categories"])


def test_category_profile_flags_small_sample(fresh_db):
    """样本太少必须**明确标注**，否则就是拿个案当规律。"""
    _seed_resolved(2)
    from data.db_issue_knowledge import category_profile
    p = category_profile(category="公共设施", tenant=A)
    assert p["total"] == 2 and p["sample_enough"] is False
    assert "样本不足" in p["note"], p


def test_category_profile_is_tenant_scoped(fresh_db):
    _seed_resolved(6)
    from data.db_issue_knowledge import category_profile
    assert category_profile(category="公共设施", tenant=B)["total"] == 0
    assert category_profile(category="公共设施", tenant="")["total"] == 0


def test_category_profile_masks_phone_in_keywords(fresh_db):
    """处置关键词先脱敏：留痕/统计里不许出现完整手机号。"""
    with db_core.get_db() as conn:
        for i in range(6):
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, status, "
                "reporter_id, reported_at, resolved_at, assignee_name, resolve_note, tenant_id) "
                "VALUES (?,?,?,?,?,?, datetime('now','-2 days'), datetime('now','-1 days'), ?, ?, ?)",
                (f"联系住户#{i}", "公共设施", "3号楼", "灯不亮", "处理结束", RESIDENT_A,
                 "王师傅", "已联系住户13800001111确认时间", A))
        conn.commit()
    from data.db_issue_knowledge import category_profile
    p = category_profile(category="公共设施", tenant=A)
    joined = " ".join(k[0] for k in p["top_keywords"])
    assert "13800001111" not in joined, f"统计里出现了完整手机号：{joined}"
