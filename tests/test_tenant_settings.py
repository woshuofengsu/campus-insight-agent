# -*- coding: utf-8 -*-
"""多租户**配置隔离**（B7）：`settings` 阈值按社区各生效各的。

**为什么需要这组测试**：`settings` 表历史上所有键都是全局一份——两个社区共用联动阈值、
共用政策自动回答阈值。多租户做到"业务数据隔离"之后，"配置"这层还留着跨社区共用的尾巴：
朝阳把高温联动阈值调低，海淀的提醒跟着变。B7 把配置改成「社区专属键 `键@社区` 优先、
裸键为全局默认」，本文件守住三件事：

  1. **写入只写社区键**（A 改配置，B 不受影响）——这是核心；
  2. **读取回落链正确**（社区专属 → 全局 → 代码默认）；
  3. **配置接到真正做判定的地方**（否则就是"配了但不生效"）：
     政策阈值要在 `ask_question` 的达标判定上生效，联动阈值要在
     `weather_event_to_link_keys` 上生效，且**定时任务按社区逐个判定**。

隔离写法：每个用例在临时库上跑，teardown 还原 `db_core._DB_PATH` 并清租户缓存
（同 `tests/test_tenant_isolation.py`）。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
GRID_A = 96311
GRID_B = 96312


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="tenant_cfg_")
    path = os.path.join(tmp, "cfg.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, com in ((GRID_A, "grid", "A网格", A), (GRID_B, "grid", "B网格", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


def _req(uid, role, community):
    """最小 Request 替身（路由只用到 state.user / query_params / client）。"""
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"{community}负责人", "community": community,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


# ---------------- 1. 配置存储层：写入只写社区键、读取按回落链 ----------------

def test_setting_key_convention():
    from data.db_settings import setting_key
    assert setting_key("linkage_thresholds") == "linkage_thresholds"
    assert setting_key("linkage_thresholds", A) == f"linkage_thresholds@{A}"
    # 历史行政区值不是合法租户 → 退回全局键（fail-closed，不猜社区）
    assert setting_key("linkage_thresholds", "海淀区") == "linkage_thresholds"


def test_setting_write_is_scoped_to_community():
    from data.db_settings import get_setting, set_setting
    set_setting("cfg_probe", "A值", tenant=A)
    assert get_setting("cfg_probe", tenant=A) == "A值"
    assert get_setting("cfg_probe", tenant=B) is None, "A 写的配置不该被 B 读到"
    assert get_setting("cfg_probe", tenant=None) is None, "社区键不该污染全局"
    set_setting("cfg_probe", "全局值")          # 写全局
    assert get_setting("cfg_probe", tenant=A) == "A值", "社区专属优先于全局"
    assert get_setting("cfg_probe", tenant=B) == "全局值", "未单独配置的社区回落全局"


def test_setting_rejects_ambiguous_community():
    """社区名含分隔符会让键解析歧义（a@b@c 归属不明）→ 明确报错，不猜。"""
    from data.db_settings import setting_key
    with pytest.raises(ValueError):
        setting_key("cfg_probe", "某@社区")


# ---------------- 2. 政策自动回答阈值：按社区各生效各的 ----------------

def test_policy_threshold_isolated_per_community():
    from data.db_policy import AUTO_ANSWER_THRESHOLD, get_match_threshold, set_match_threshold
    base = get_match_threshold()
    assert base == AUTO_ANSWER_THRESHOLD
    ok_, msg = set_match_threshold(3.5, actor="A网格", tenant=A)
    assert ok_, msg
    assert get_match_threshold(tenant=A) == 3.5, "A 社区应拿到自己的阈值"
    assert get_match_threshold(tenant=B) == AUTO_ANSWER_THRESHOLD, \
        "B 社区不该被 A 的配置影响（跨租户串味）"
    assert get_match_threshold() == AUTO_ANSWER_THRESHOLD, "无租户口径仍是全局/默认值"


def test_policy_threshold_global_fallback_and_override_order():
    from data.db_policy import get_match_threshold, set_match_threshold
    set_match_threshold(1.5, actor="系统", tenant=None)      # 写全局
    assert get_match_threshold(tenant=B) == 1.5, "未单独配置的社区应回落全局值"
    assert get_match_threshold(tenant=A) == 3.5, "已单独配置的社区不受全局改动影响"


def test_policy_threshold_validation_and_no_global_mutation():
    """非法值被拒；且 set 不再改写进程内全局默认（那是串味根源）。"""
    from data.db_policy import AUTO_ANSWER_THRESHOLD, _match_threshold, get_match_threshold, \
        set_match_threshold
    assert set_match_threshold(0.01, tenant=A)[0] is False
    assert set_match_threshold("abc", tenant=A)[0] is False
    assert get_match_threshold(tenant=A) == 3.5, "非法值不该写进去"
    assert _match_threshold == AUTO_ANSWER_THRESHOLD, \
        "进程内默认值必须保持不变（改它就是跨租户串味）"


def test_policy_threshold_route_is_scoped():
    """路由接线：A 网格员设完只影响 A（租户只从 JWT 身份来）。"""
    from api_routes.policy import ThresholdSet, web_qa_threshold_get, web_qa_threshold_set
    r = web_qa_threshold_set(ThresholdSet(threshold=4.0), _req(GRID_A, "grid", A))
    assert r.get("success"), r
    assert r["data"]["scope"] == A
    got_a = web_qa_threshold_get(_req(GRID_A, "grid", A))
    got_b = web_qa_threshold_get(_req(GRID_B, "grid", B))
    assert got_a["data"]["threshold"] == 4.0 and got_a["data"]["scope"] == A
    assert got_b["data"]["threshold"] == 1.5, "B 仍应看到全局值 1.5"


def test_ask_question_uses_askers_community_threshold(monkeypatch):
    """判定点接线：`ask_question` 取阈值时必须传**提问人所属社区**。

    这是"配了但没生效"的防锈断言：只改配置页读数、判定仍读全局，就是白做。
    """
    import data.db_policy as dp
    seen: list = []
    original = dp.get_setting

    def spy(key, tenant=None, default=None):
        if key == "match_threshold":
            seen.append(tenant)
        return original(key, tenant=tenant, default=default)

    monkeypatch.setattr(dp, "get_setting", spy)
    dp.ask_question(GRID_A, "社区停车位怎么申请？")
    assert A in seen, f"ask_question 没按提问人的社区取阈值（记录到 {seen}）"
    assert B not in seen


# ---------------- 3. 天气联动阈值：按社区判定 + 去重/关闭也按社区 ----------------

def test_linkage_thresholds_isolated_per_community():
    from data.db_health_content import get_linkage_thresholds, set_linkage_thresholds
    base = get_linkage_thresholds()
    assert base["high_temp"] == 35
    r = set_linkage_thresholds(high_temp=30, low_temp=0, temp_drop=5, actor="A网格", tenant=A)
    assert (r["high_temp"], r["low_temp"], r["temp_drop"]) == (30, 0, 5)
    assert get_linkage_thresholds(tenant=A)["high_temp"] == 30
    assert get_linkage_thresholds(tenant=B)["high_temp"] == 35, "B 不该被 A 改掉"
    assert get_linkage_thresholds()["high_temp"] == 35, \
        "内置默认值不许被 setter 改写（B7 前的跨租户串味根源）"


def test_weather_event_uses_community_threshold():
    """行为级：同一个 32℃ 天气事件，A（阈值 30）命中高温联动、B（默认 35）不命中。"""
    from data.db_health_content import weather_event_to_link_keys
    ev = {"temp_high": 32}
    assert weather_event_to_link_keys(ev, tenant=A) == ["高温"]
    assert weather_event_to_link_keys(ev, tenant=B) == []
    # 36℃ 两个社区都该命中（防"一刀切：谁都别触发"）
    hot = {"temp_high": 36}
    assert weather_event_to_link_keys(hot, tenant=A) == ["高温"]
    assert weather_event_to_link_keys(hot, tenant=B) == ["高温"]


def test_linkage_scope_tag_roundtrip():
    from data.db_health_content import linkage_scope_of
    assert linkage_scope_of(f"[{A}]高温|黄色|健康提示") == A
    assert linkage_scope_of("高温|黄色|健康提示") == "", "无标签 = 升级前的全局留痕"
    assert linkage_scope_of("") == ""


def test_linkage_close_is_per_community():
    """A 社区永久关闭某联动，不该连带关掉 B 社区（关闭状态也要按社区记）。"""
    from data.db_health_content import (_linkage_perm_closed, _linkage_triggered_today,
                                        close_linkage, reopen_linkage)
    assert close_linkage("暴雨", "A 社区演示关闭", actor="A网格", permanent=True,
                         confirm=True, tenant=A)[0]
    assert _linkage_perm_closed("暴雨", tenant=A) is True
    assert _linkage_perm_closed("暴雨", tenant=B) is False, "A 关了不代表 B 也关"
    assert reopen_linkage("暴雨", actor="A网格", confirm=True, tenant=A)[0]
    assert _linkage_perm_closed("暴雨", tenant=A) is False
    # 去重同样按社区：A 今天触发过，不影响 B
    from data.db_notifications import log_activity
    log_activity("系统", "联动提醒触发", "weather_linkage", 1, target_title="高温提示",
                 module="疾病预防", after_value="已触发", detail=f"[{A}]高温|黄色|健康提示")
    assert _linkage_triggered_today("高温", tenant=A) is True
    assert _linkage_triggered_today("高温", tenant=B) is False, \
        "A 触发过不该把 B 压掉（否则 B 配了阈值也收不到提醒）"


def test_legacy_unmarked_linkage_rows_count_as_global():
    """升级前的无标签留痕视为全局决策：保守地不擅自重新打开/重复触发。"""
    from data.db_health_content import _linkage_perm_closed, _linkage_triggered_today
    from data.db_notifications import log_activity
    log_activity("系统", "永久关闭联动", "weather_linkage", module="疾病预防",
                 detail="大风")
    log_activity("系统", "联动提醒触发", "weather_linkage", 2, target_title="寒潮提示",
                 module="疾病预防", after_value="已触发", detail="寒潮|橙色|健康提示")
    assert _linkage_perm_closed("大风", tenant=A) is True
    assert _linkage_perm_closed("大风", tenant=B) is True
    assert _linkage_triggered_today("寒潮", tenant=A) is True
    assert _linkage_triggered_today("寒潮", tenant=B) is True


def test_linkage_route_is_scoped():
    """路由接线：A 网格员改阈值/关联动只影响 A。"""
    from api_routes.health import (LinkageAction, LinkageThresholdsSet,
                                   web_health_linkage_action,
                                   web_health_linkage_thresholds_get,
                                   web_health_linkage_thresholds_set)
    r = web_health_linkage_thresholds_set(
        LinkageThresholdsSet(high_temp=28), _req(GRID_A, "grid", A))
    assert r.get("success"), r
    assert r["data"]["scope"] == A
    got_a = web_health_linkage_thresholds_get(_req(GRID_A, "grid", A))
    got_b = web_health_linkage_thresholds_get(_req(GRID_B, "grid", B))
    assert got_a["data"]["high_temp"] == 28
    assert got_b["data"]["high_temp"] == 35, "B 应仍是默认阈值"
    # 关闭动作也按社区；永久关闭要能真的关上（此前路由没有 permanent 入口 → 永远关不上）
    assert web_health_linkage_action(
        "台风", LinkageAction(action="close", reason="演示", permanent=True),
        _req(GRID_A, "grid", A)).get("success")
    from data.db_health_content import _linkage_perm_closed
    assert _linkage_perm_closed("台风", tenant=A) is True, "永久关闭后 A 社区应被挡住"
    assert _linkage_perm_closed("台风", tenant=B) is False, "A 关闭不该连带关掉 B"
    # 重新开启后恢复
    assert web_health_linkage_action("台风", LinkageAction(action="reopen"),
                                     _req(GRID_A, "grid", A)).get("success")
    assert _linkage_perm_closed("台风", tenant=A) is False


# ---------------- 4. 定时任务按社区逐个判定（否则"按社区配"永远不生效） ----------------

def test_scheduler_iterates_communities(monkeypatch):
    """定时任务：预警是全局的，但要**按社区各判一次**（阈值不同 → 结果不同）。"""
    import scripts.scheduler as sch
    from data import db_health_content as db_health
    from data import db_weather

    calls: list = []
    monkeypatch.setattr(db_weather, "check_cache_freshness", lambda: {"state": "ok"})
    monkeypatch.setattr(db_weather, "get_active_alerts", lambda: [
        {"id": 1, "alert_type": "高温", "level": "橙色", "effective_time": "",
         "expire_time": ""}])
    monkeypatch.setattr(db_health, "trigger_weather_linkage",
                        lambda ev, actor="系统", tenant=None: calls.append(tenant) or {"tenant": tenant})
    out = sch._health_linkage_tasks(db_weather, db_health)
    assert set(calls) == {A, B}, f"应按社区逐个判定，实际调用 {calls}"
    assert len(out) == 2, f"每个社区各应有一条结果，实际 {out}"


def test_scheduler_falls_back_when_no_tenants(monkeypatch):
    """库里还没有社区时保留一次全局调用（演示环境不能静默什么都不做）。"""
    import scripts.scheduler as sch
    from data import db_health_content as db_health
    from data import db_weather
    import utils.tenant as ut

    calls: list = []
    monkeypatch.setattr(ut, "all_tenants", lambda: [])
    monkeypatch.setattr(db_weather, "check_cache_freshness", lambda: {"state": "ok"})
    monkeypatch.setattr(db_weather, "get_active_alerts", lambda: [
        {"id": 1, "alert_type": "高温", "level": "橙色", "effective_time": "",
         "expire_time": ""}])
    monkeypatch.setattr(db_health, "trigger_weather_linkage",
                        lambda ev, actor="系统", tenant=None: calls.append(tenant) or {"tenant": tenant})
    sch._health_linkage_tasks(db_weather, db_health)
    assert calls == [None], f"没有社区时应回落一次全局调用，实际 {calls}"
