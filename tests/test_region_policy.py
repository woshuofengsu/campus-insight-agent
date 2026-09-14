# -*- coding: utf-8 -*-
"""地区识别（属地化）集成测试：政策排序 / 安全底线 / 天气链路 / 端到端。

对应 docs/spec/地区识别落地方案.md v2 第 4 节（WS2/WS3/WS4 的验收点）。
全部用独立临时库，不污染正式数据。
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

# 端到端用例要跑真实 App：按本项目既有惯例用独立临时库（不污染正式数据），
# 并在 import api_web 之前设好 DB_PATH。conftest 的 _isolate_db_path 会在模块结束后复位。
_APP_TMP = tempfile.mkdtemp(prefix="region_app_")
config.DB_PATH = os.path.join(_APP_TMP, "region_app.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api_web  # noqa: E402

from utils.region import resolve_region  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(api_web.app) as c:
        yield c


@pytest.fixture()
def kb_db(monkeypatch):
    """独立临时库 + 三条同主题政策（全国 / 北京市 / 北京市海淀区）+ 一条外地政策。"""
    import config
    from data import db_core

    tmp = tempfile.mkdtemp(prefix="region_policy_")
    path = os.path.join(tmp, "kb.db")
    db_core.init_db(path)
    monkeypatch.setattr(config, "DB_PATH", path, raising=False)
    monkeypatch.setattr(db_core, "_DB_PATH", path, raising=False)
    with sqlite3.connect(path) as conn:
        rows = [
            ("社保医保", "全国高龄老人补贴办法", "高龄补贴全国统一标准，年满80岁可申领。",
             "高龄,补贴,津贴,老人", "已发布", "全国"),
            ("社保医保", "北京市高龄老人养老服务补贴办法", "北京市高龄老人养老服务补贴申领办法。",
             "高龄,补贴,津贴,老人", "已发布", "北京市"),
            ("社保医保", "北京市海淀区高龄老人津贴申领实施细则",
             "海淀区高龄津贴：80-89岁每月200元，需要身份证、户口簿、银行卡。",
             "高龄,补贴,津贴,老人,申领,办理,材料", "已发布", "北京市海淀区"),
            ("社保医保", "上海市高龄老人补贴办法", "上海市高龄老人补贴标准（外地政策）。",
             "高龄,补贴,津贴,老人", "已发布", "上海市"),
        ]
        for cat, title, content, kw, status, area in rows:
            conn.execute(
                "INSERT INTO knowledge_base (category,title,content,keywords,audit_status,applicable_area) "
                "VALUES (?,?,?,?,?,?)", (cat, title, content, kw, status, area))
        conn.commit()
    yield path


def _titles(results):
    return [r["title"] for r in results]


def test_region_none_order_equals_no_region(kb_db):
    """region=None 时排序与不传完全一致（向后兼容的地基）。"""
    from data.db_policy import search_published_knowledge
    a = search_published_knowledge("高龄老人补贴怎么领", top_k=5)
    b = search_published_knowledge("高龄老人补贴怎么领", top_k=5, region=None)
    assert _titles(a) == _titles(b)
    assert all(e.get("region_level") == "national" for e in b)


def test_local_district_ranks_first_for_local_user(kb_db):
    """属地内用户：区级细则排第一，且全国/市级条目**仍可召回**（属地不是过滤器）。"""
    from data.db_policy import search_published_knowledge
    reg = resolve_region("海淀小区")
    res = search_published_knowledge("高龄老人补贴怎么领", top_k=5, region=reg)
    assert res[0]["title"] == "北京市海淀区高龄老人津贴申领实施细则"
    assert res[0]["region_level"] == "local_district"
    assert "全国高龄老人补贴办法" in _titles(res), "全国条目必须仍在结果里（兜底）"


def test_foreign_policy_soft_penalized_but_visible(kb_db):
    """外地政策：软降权但仍在结果中（保留可发现性，不作过滤）。"""
    from data.db_policy import search_published_knowledge
    reg = resolve_region("海淀小区")
    res = search_published_knowledge("高龄老人补贴怎么领", top_k=5, region=reg)
    sh = [e for e in res if e["title"].startswith("上海市")]
    assert sh, "外地政策不应被过滤掉"
    assert sh[0]["region_level"] == "other"
    # 无属地时它的分数更高（因为没有被扣分）
    bare = search_published_knowledge("高龄老人补贴怎么领", top_k=5)
    sh_bare = [e for e in bare if e["title"].startswith("上海市")][0]
    assert sh[0]["score"] < sh_bare["score"]


def test_irrelevant_local_entry_not_boosted_into_result(kb_db):
    """属地加分只在 base>0（主题已相关）时生效：完全无关的本地条目不进结果。"""
    from data.db_policy import search_published_knowledge
    reg = resolve_region("海淀小区")
    res = search_published_knowledge("电梯维修找谁", top_k=5, region=reg)
    assert "北京市海淀区高龄老人津贴申领实施细则" not in _titles(res)


def test_answer_entry_never_downgrades_answerability(kb_db, monkeypatch):
    """安全底线（本方案的关键修正，**必须能拦住"只看 top1"的退化实现**）：

    构造：本地条目 base **低于阈值**、但被属地加成抬到 final 第一；全国条目 base 高于阈值。
    - 正确实现：选 final 排序里**第一条 base 达标**的（→ 用全国那条回答）；
    - 退化实现（answer_entry = results[0]）：本地 top1 不达标 → 转人工/RAG → 用户本来能拿到答案却拿不到。

    前提（本地 base 更低、但属地加成后 final 更高）用 `assert` 钉住 —— 否则本测试会变成**空测试**
    （故障注入实测发现：早前的版本就是空的，注入"只看 top1"竟然没被拦住）。
    为保证"排序反转"稳定复现，这里把属地加成换成受控值（加成函数本身另有 test_region.py 覆盖）。
    """
    import sqlite3 as _s

    import data.db_policy as dp
    import utils.region as ur
    from data.db_policy import ask_question, search_published_knowledge

    reg = resolve_region("海淀小区")
    q = "高龄老人补贴怎么领"
    local_title = "北京市海淀区高龄老人津贴申领实施细则"
    nat_title = "全国高龄老人补贴办法"

    bare = {e["title"]: e for e in search_published_knowledge(q, top_k=5)}
    base_local = bare[local_title]["base_score"]
    base_nat = bare[nat_title]["base_score"]
    assert base_local < base_nat, (
        f"前提不成立：本地 base {base_local} 应低于全国 base {base_nat}（fixture 被改动请调整）")

    # 阈值卡在两者之间 → 本地 base 不达标、全国 base 达标
    monkeypatch.setattr(dp, "_match_threshold", (base_local + base_nat) / 2)

    # 受控加成：保证本地条目被抬到 final 第一（否则"排序反转"无法稳定复现）
    real_boost = ur.policy_region_boost

    def fake_boost(area, region):
        b, lv = real_boost(area, region)
        return (50.0, lv) if "海淀区" in (area or "") else (b, lv)

    monkeypatch.setattr(ur, "policy_region_boost", fake_boost)

    ranked = search_published_knowledge(q, top_k=5, region=reg)
    assert ranked[0]["title"] == local_title, f"属地应把本地条目抬到第一（实际 {ranked[0]['title']}）"
    assert ranked[0]["base_score"] < dp._match_threshold, "本地条目本身不达标（这是本用例的前提）"

    res = ask_question(99991, q, source="测试", region=reg)
    assert res["matched"], f"属地不得把『本来能回答』变成转人工（reason={res.get('reason')}）"
    assert res["knowledge"]["title"] == nat_title, "应选中 base 达标的那条（全国），而不是靠属地抬上来的弱命中本地条目"
    assert res["base_score"] >= dp._match_threshold

    ranked = search_published_knowledge(q, top_k=5, region=reg)
    assert ranked[0]["title"] == local_title, (
        f"属地应把本地条目抬到第一（实际 {ranked[0]['title']}）")

    res = ask_question(99991, q, source="测试", region=reg)
    assert res["matched"], f"属地不得把『本来能回答』变成转人工（reason={res.get('reason')}）"
    assert res["knowledge"]["title"] == nat_title, "应选中 base 达标的那条（全国），而不是靠属地抬上来的弱命中本地条目"
    assert res["base_score"] >= dp._match_threshold


def test_rag_hybrid_region_rerank(kb_db):
    """Agent RAG（RRF 融合）也吃属地：本地小幅前置，region=None 顺序不变。"""
    from agent.rag import search_hybrid
    q = "高龄老人补贴怎么领"
    bare = search_hybrid(q, top_k=5)
    loc = search_hybrid(q, top_k=5, region=resolve_region("海淀小区"))
    assert bare, "基线不应为空"
    assert [r["title"] for r in search_hybrid(q, top_k=5, region=None)] == [r["title"] for r in bare]
    assert loc[0]["title"] == "北京市海淀区高龄老人津贴申领实施细则"
    assert loc[0]["region_level"] == "local_district"


def test_weather_cache_keyed_by_region(kb_db, monkeypatch):
    """天气：不同属地的缓存互不覆盖（缓存键 = adcode），且 daily advice 按属地隔离。"""
    from data import db_weather
    calls = []

    def fake_fetch(city="", city_id=""):
        calls.append((city, city_id))
        return ([{"condition": "晴", "temp_high": 20, "temp_low": 10, "wind": "微风",
                  "rain_prob": 0, "emoji": "☀️"}], f"{city}天气", True)

    monkeypatch.setattr(db_weather, "_fetch_days", fake_fetch)
    r1 = resolve_region("海淀小区")
    r2 = resolve_region("朝阳试点社区")

    w1 = db_weather.refresh_weather(r1.district, r1.city_id)
    w2 = db_weather.refresh_weather(r2.district, r2.city_id)
    assert w1["is_real"] is True and w2["is_real"] is True
    assert calls[0] == ("海淀区", "101010100")
    assert calls[1] == ("朝阳区", "101010300")
    # 两个城市各写一条缓存（键不同）
    c1 = db_weather.get_cached_weather(r1.city_id)
    c2 = db_weather.get_cached_weather(r2.city_id)
    assert c1 and c2 and c1["city"] != c2["city"]


def test_daily_advice_isolated_per_region(kb_db, monkeypatch):
    """每日建议：A 社区生成过之后，B 社区不能拿到同一份（此前按天全局缓存）。"""
    from data import db_weather
    monkeypatch.setattr(db_weather, "_fetch_days", lambda city="", city_id="": (
        [{"condition": "晴", "temp_high": 20, "temp_low": 10}], city, True))
    a = db_weather.get_daily_advice(city="海淀区", city_id="101010100")
    b = db_weather.get_daily_advice(city="朝阳区", city_id="101010300")
    assert a.get("city_key") == "101010100"
    assert b.get("city_key") == "101010300"
    assert a != b or a.get("city_key") != b.get("city_key")


def _mock_weather(monkeypatch):
    """让端到端用例不吃外网：把真实天气抓取换成固定数据（属地传参仍被验证）。"""
    from data import db_weather

    def fake_fetch(city="", city_id=""):
        return ([{"condition": "晴", "temp_high": 22, "temp_low": 12, "wind": "微风",
                  "rain_prob": 0, "emoji": "☀️", "humidity": 40, "aqi": 50, "uv": 3,
                  "advice": "注意防晒"}], f"{city}（属地）", True)

    monkeypatch.setattr(db_weather, "_fetch_days", fake_fetch)


def test_weather_endpoints_return_region_label(client, monkeypatch):
    """端到端：居民端 /weather/current 与 /forecast 带属地标签（居民账号所属社区）。"""
    _mock_weather(monkeypatch)
    r = client.post("/api/web/auth/demo", json={"role": "resident"})
    token = r.json()["data"]["token"]
    h = {"Authorization": f"Bearer {token}"}
    for path in ("/api/web/weather/current", "/api/web/weather/forecast"):
        resp = client.get(path, headers=h)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data.get("region_label"), f"{path} 缺 region_label：{data}"
        assert data.get("city_id"), f"{path} 缺 city_id：{data}"


def test_elderly_home_weather_has_region_label(client, monkeypatch):
    """端到端：老年端 /elderly/home 的天气同样带属地（三端口径一致，演示切屏不露馅）。"""
    _mock_weather(monkeypatch)
    r = client.post("/api/web/auth/demo", json={"role": "elderly"})
    token = r.json()["data"]["token"]
    resp = client.get("/api/web/elderly/home", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    w = (resp.json()["data"] or {}).get("weather") or {}
    assert w.get("region_label"), f"老年端天气缺属地：{w}"
    assert w.get("city_id"), f"老年端天气缺 city_id：{w}"


def test_policy_qa_endpoint_passes_region(client, monkeypatch):
    """端到端：居民提问走线上答题链路时，属地会透传（返回体带 region_level）。"""
    r = client.post("/api/web/auth/demo", json={"role": "resident"})
    token = r.json()["data"]["token"]
    resp = client.post("/api/web/qa/ask", json={"question": "高龄津贴多少钱一个月"},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"] or {}
    # 无论命中与否，都不应因属地引入 500；命中时带属地级别
    if data.get("matched"):
        assert data.get("region_level") in (
            "national", "local_city", "local_province", "local_district", "local_street"), data
