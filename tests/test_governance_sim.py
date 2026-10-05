# -*- coding: utf-8 -*-
"""治理情景模拟器门禁（v4 收敛方案第 5 阶段）。

**要守住的是"算账的诚实"**，不是"算得对不对"——公式本身很简单（乘法除法），
真正会出事故的是这四种情形，所以每条都有用例：

  ① **算不出来时给不给假数字**：没有已办结工单 → 拿不到实测平均处理时长 →
     工时与人手必须**为 None**，不许拿 0 或默认值糊弄（本项目最忌讳"做了但不生效"的反面：
     "算不出却给个数"）。
  ② **「人均可用工时未配置」必须明说**：返回里带 `人均可用工时未配置，无法折算人手`，
     而不是悄悄用某个默认值折算出一个看起来很像样的人手数。
  ③ **样本不足要标**：< 5 条明确 `sufficient=False` + 「样本不足」文案。
  ④ **租户 fail-closed**：不传社区 → 空结构 + 明确"缺少社区归属"，
     **不能**把 `0 条` 说成"这个社区真没工单"（那是两件事），更不能汇总全库。
  ⑤ 配置项**按社区分键**：A 社区填了人均可用工时，B 社区不能跟着变。
  ⑥ **只读**：跑一次模拟不许改动任何业务数据（工单数、状态都不变）。
  ⑦ 标签纪律：结果必须带「情景估算」与"不是预测"的口径，防止被当成承诺写进材料。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
RESIDENT_A = 99710
RESIDENT_B = 99711


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="govsim_"), "g.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((99701, "grid", "A网格", A),
                                     (99702, "grid", "B网格", B),
                                     (RESIDENT_A, "resident", "A居民", A),
                                     (RESIDENT_B, "resident", "B居民", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _seed_issues(tenant: str, reporter: int, n: int, resolved: bool, hours: float = 4.0):
    """造 n 条工单；`resolved=True` 时把 `resolved_at` 设为 reported_at + hours。"""
    with db_core.get_db() as conn:
        for i in range(n):
            if resolved:
                conn.execute(
                    "INSERT INTO community_issues (title, category, location, description, status, "
                    "reporter_id, reported_at, resolved_at, tenant_id) VALUES (?,?,?,?,?,?, "
                    "datetime('now','-1 days'), datetime('now','-1 days',?), ?)",
                    (f"工单{i}", "公共设施", "3号楼", "灯不亮", "已解决", reporter, f"+{hours} hours", tenant))
            else:
                conn.execute(
                    "INSERT INTO community_issues (title, category, location, description, status, "
                    "reporter_id, reported_at, tenant_id) VALUES (?,?,?,?,?,?, datetime('now','-1 days'), ?)",
                    (f"工单{i}", "公共设施", "3号楼", "灯不亮", "待审核", reporter, tenant))
        conn.commit()


# ---------------------------------------------------------------- ① 算不出来就不给数字

def test_no_resolved_issues_means_no_workload_numbers(fresh_db):
    """没有已办结工单 → 实测平均时长拿不到 → **工时与人手不给数字**（不许拿 0 冒充）。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=False)
    r = simulate_governance(days=30, growth_pct=20, tenant=A)
    assert r["sample"]["issues"] == 6
    assert r["avg_minutes"]["value"] is None
    assert r["workload"]["total_hours"] is None, r["workload"]
    assert r["workload"]["staffing"] is None
    assert any("不给数字" in n for n in r["notes"]), r["notes"]


def test_measured_avg_hours_is_used_when_available(fresh_db):
    """有已办结工单 → 平均时长取**实测办结耗时**，并标明来源 + 说明它不等于人工投入。

    ⚠️ 这条提醒是实测后补的：demo 库 34 条已办结工单的平均办结耗时 20.78 小时，
    302 单 × 20.78h ÷ 8h ≈ 784 人——算术没错，**口径错了**：
    "从反映到办结"是墙钟时间（含等待），不是"这条诉求占用了多少人工"。
    所以必须把偏差写在结果里，而不是给一个看着像样、其实离谱的数。
    """
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    r = simulate_governance(days=30, growth_pct=0, tenant=A, available_hours=8.0)
    assert r["sample"]["resolved"] == 6
    assert r["sample"]["measured_avg_hours"] == pytest.approx(4.0, abs=0.05)
    assert r["avg_minutes"]["value"] == pytest.approx(240.0, abs=3)
    assert "实测办结耗时" in r["avg_minutes"]["source"], r["avg_minutes"]
    assert any("不等于人工实际投入" in n and "高估" in n for n in r["notes"]), r["notes"]
    # 预计总量 = 6 + 0 = 6；总工时 = 6 × 4h = 24h；人手 = 24 ÷ 8 = 3
    assert r["projected"]["total"] == 6
    assert r["workload"]["total_hours"] == pytest.approx(24.0, abs=0.5)
    assert r["workload"]["staffing"] == pytest.approx(3.0, abs=0.1)


def test_caveat_disappears_when_labor_time_is_configured(fresh_db):
    """填了"人工时长"配置项 → 不再出现"办结耗时≠人工投入"的提醒（提醒不能变成常驻噪音）。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    r = simulate_governance(days=30, growth_pct=0, tenant=A, avg_minutes=30, available_hours=8)
    assert r["avg_minutes"]["source"] == "本次输入"
    assert not any("办结耗时" in n for n in r["notes"]), r["notes"]


def test_explicit_avg_minutes_overrides_measurement(fresh_db):
    """调用方给了平均处理时长就用调用方的，并把来源标成"本次输入"（不冒充实测）。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    r = simulate_governance(days=30, growth_pct=0, tenant=A, avg_minutes=30, available_hours=8)
    assert r["avg_minutes"]["value"] == 30
    assert r["avg_minutes"]["source"] == "本次输入"
    assert r["workload"]["total_hours"] == pytest.approx(3.0, abs=0.1)   # 6 × 0.5h
    assert r["workload"]["staffing"] == pytest.approx(0.38, abs=0.05)    # 3 ÷ 8


# ---------------------------------------------------------------- ② 未配置就明说

def test_missing_available_hours_says_so_and_gives_no_headcount(fresh_db):
    """「人均可用工时」未配置 → 必须**明确说**"未配置，无法折算人手"，且不给人手数。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    r = simulate_governance(days=30, growth_pct=10, tenant=A)
    assert r["available_hours"]["value"] is None
    assert r["workload"]["staffing"] is None
    assert "人均可用工时未配置，无法折算人手" in r["workload"]["staffing_unavailable_reason"]
    assert any("未配置，无法折算人手" in n for n in r["notes"]), r["notes"]
    # 但工时是能算的（时长有了），所以不许把工时也一起吞掉
    assert r["workload"]["total_hours"] is not None


def test_settings_roundtrip_and_scope(fresh_db):
    """配置项按**社区分键**：A 填了，B 不受影响；单传一项不动另一项。"""
    from data.db_governance_sim import (get_sim_settings, set_sim_settings,
                                       simulate_governance)
    set_sim_settings(available_hours=8, actor="A网格", tenant=A)
    assert get_sim_settings(tenant=A)["available_hours"] == 8
    assert get_sim_settings(tenant=B)["available_hours"] is None, "配置串社区了"
    set_sim_settings(avg_minutes=45, actor="A网格", tenant=A)
    cfg = get_sim_settings(tenant=A)
    assert cfg["available_hours"] == 8, "只改一项时另一项不该被清掉"
    assert cfg["avg_minutes"] == 45
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    r = simulate_governance(days=30, growth_pct=0, tenant=A)
    assert r["avg_minutes"]["value"] == 45, "配置项优先于实测"
    assert r["workload"]["staffing"] == pytest.approx(6 * 0.75 / 8, abs=0.05)


def test_settings_reject_non_positive(fresh_db):
    """非法值（0 / 负数 / 非数字）一律拒绝，**不许**静默写成 0 再算出一个 0 人手的假结论。"""
    from data.db_governance_sim import set_sim_settings
    for bad in (0, -3, "abc"):
        with pytest.raises(ValueError):
            set_sim_settings(available_hours=bad, actor="A网格", tenant=A)


# ---------------------------------------------------------------- ③ 样本不足要标

def test_small_sample_is_flagged(fresh_db):
    """样本 < 5 条 → `sufficient=False` + 「样本不足」文案（别拿 2 条记录下结论）。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 2, resolved=True, hours=4.0)
    r = simulate_governance(days=30, growth_pct=50, tenant=A)
    assert r["sample"]["sufficient"] is False
    assert any("样本不足" in n for n in r["notes"]), r["notes"]
    _seed_issues(A, RESIDENT_A, 4, resolved=True, hours=4.0)   # 累计 6 条
    r2 = simulate_governance(days=30, growth_pct=50, tenant=A)
    assert r2["sample"]["issues"] == 6 and r2["sample"]["sufficient"] is True
    assert not any("样本不足" in n for n in r2["notes"])


# ---------------------------------------------------------------- ④ 租户 fail-closed

def test_missing_tenant_is_not_reported_as_zero_issues(fresh_db):
    """不传社区 → 空结构 + **"缺少社区归属"**（不能让人误读成"这个社区真没工单"）。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True)
    r = simulate_governance(days=30, growth_pct=10, tenant="")
    assert r["tenant_valid"] is False
    assert r["sample"]["issues"] == 0
    assert any("缺少社区归属" in n for n in r["notes"]), r["notes"]
    assert not any("样本不足" in n for n in r["notes"]), \
        "缺少归属与样本不足是两件事，不能混成一句"


def test_other_community_data_is_invisible(fresh_db):
    """A 社区的样本不能算进 B 社区的情景（派生指标跨社区汇总就是错数据）。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    assert simulate_governance(days=30, growth_pct=0, tenant=A)["sample"]["issues"] == 6
    rb = simulate_governance(days=30, growth_pct=0, tenant=B)
    assert rb["sample"]["issues"] == 0 and rb["sample"]["resolved"] == 0


# ---------------------------------------------------------------- ⑤ 增长率是假设，且要有边界

def test_growth_rate_is_clamped_and_labelled_as_assumption(fresh_db):
    """增长率是**情景假设**（文案要标），且钳在 -90% ~ +500%（别算出负数或天文数字）。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 10, resolved=True, hours=2.0)
    r = simulate_governance(days=30, growth_pct=50, tenant=A)
    assert r["projected"]["new"] == 5 and r["projected"]["total"] == 15
    assert "假设" in r["scenario"]["source"] and "不是" in r["scenario"]["source"]
    r_low = simulate_governance(days=30, growth_pct=-500, tenant=A)
    assert r_low["scenario"]["growth_pct"] == -90.0
    assert r_low["projected"]["new"] >= -9, "钳位后不该出现负增长把量算成负数"
    r_high = simulate_governance(days=30, growth_pct=9999, tenant=A)
    assert r_high["scenario"]["growth_pct"] == 500.0


def test_growth_negative_scenario_is_explained(fresh_db):
    """负增长要给一句人话解释（"诉求下降"情景），别让人以为算错了。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 10, resolved=True, hours=2.0)
    r = simulate_governance(days=30, growth_pct=-30, tenant=A)
    assert r["projected"]["new"] == -3 and r["projected"]["total"] == 7
    assert any("诉求下降" in n or "负" in n for n in r["notes"]), r["notes"]


# ---------------------------------------------------------------- ⑥ 只读 + ⑦ 标签

def test_simulation_is_read_only(fresh_db):
    """跑模拟不许动业务数据：工单数、状态、`resolved_at` 都得原样。"""
    from data.db_governance_sim import simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    with db_core.get_db() as conn:
        before = conn.execute(
            "SELECT COUNT(*) c, SUM(status='已解决') s, SUM(resolved_at IS NOT NULL) r "
            "FROM community_issues").fetchone()
    for g in (-30, 0, 25, 200):
        simulate_governance(days=30, growth_pct=g, tenant=A, available_hours=8)
    with db_core.get_db() as conn:
        after = conn.execute(
            "SELECT COUNT(*) c, SUM(status='已解决') s, SUM(resolved_at IS NOT NULL) r "
            "FROM community_issues").fetchone()
    assert dict(before) == dict(after), "模拟器动了业务数据（它必须是只读的）"


def test_result_carries_estimate_label_and_formulas(fresh_db):
    """标签纪律：必须带「情景估算」+ 四条公式原文 + "不是预测/承诺"的口径。

    这条守的是**对外口径**：模拟结果是"按公式算的情景估算"，
    一旦被写成"系统预测需求将增长 X%"，就变成编数字了。
    """
    from data.db_governance_sim import LABEL, simulate_governance
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    r = simulate_governance(days=30, growth_pct=20, tenant=A, available_hours=8)
    assert r["label"] == LABEL == "情景估算"
    assert len(r["formulas"]) == 4
    assert any("预计新增" in f and "样本量" in f for f in r["formulas"])
    assert any("折算人手" in f and "人均可用工时" in f for f in r["formulas"])
    assert "不是预测" in r["disclaimer"] and "不构成承诺" in r["disclaimer"]


def test_days_are_clamped(fresh_db):
    """窗口期钳在 1–365 天（口径与其它指标接口一致）。

    ⚠️ 这条用例是**写测试时抓到的真 bug**：最初写成 `max(1, min(int(days or 30), 365))`，
    `days=0` 会被 `or` 悄悄换成 30（"没给"和"给了 0"被混成一件事），
    调用方以为按 1 天算、实际按 30 天算。修法：**只把 None 当没给**。
    """
    from data.db_governance_sim import simulate_governance
    assert simulate_governance(days=0, tenant=A)["days"] == 1, \
        "days=0 必须钳到 1 天，不能被静默换成默认 30 天"
    assert simulate_governance(days=1, tenant=A)["days"] == 1
    assert simulate_governance(days=99999, tenant=A)["days"] == 365
    assert simulate_governance(days=None, tenant=A)["days"] == 30, "None 才按默认 30 天"


# ---------------------------------------------------------------- 接口层：角色 / 租户 / 留痕

def _req(uid, role="grid", com=A):
    from types import SimpleNamespace
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"n{uid}", "community": com,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


def _code(r) -> int:
    if isinstance(r, dict):
        return int(r.get("code", -1))
    try:
        import json
        return int(json.loads(r.body.decode("utf-8")).get("code", -1))
    except Exception:  # noqa: BLE001
        return -1


def _msg(r) -> str:
    if isinstance(r, dict):
        return str(r.get("message") or "")
    try:
        import json
        return str(json.loads(r.body.decode("utf-8")).get("message") or "")
    except Exception:  # noqa: BLE001
        return ""


def test_route_requires_grid_role(fresh_db):
    """模拟器是网格员侧工具：居民/老人调不到（含配置写入）。"""
    from api_routes.agent import (SimSettings, agent_governance_simulation,
                                 agent_governance_simulation_settings)
    assert _code(agent_governance_simulation(_req(RESIDENT_A, "resident"))) != 0
    assert _code(agent_governance_simulation_settings(
        SimSettings(available_hours=8), _req(RESIDENT_A, "resident"))) != 0


def test_route_simulates_for_the_callers_community_only(fresh_db):
    """接口按调用者身份取社区：A 网格员看到 A 的样本，B 网格员一条也看不到。"""
    from api_routes.agent import agent_governance_simulation
    _seed_issues(A, RESIDENT_A, 6, resolved=True, hours=4.0)
    ra = agent_governance_simulation(_req(99701), days=30, growth_pct=25)
    assert ra["code"] == 0 and ra["data"]["sample"]["issues"] == 6
    assert ra["data"]["tenant_valid"] is True
    rb = agent_governance_simulation(_req(99702, com=B), days=30, growth_pct=25)
    assert rb["code"] == 0 and rb["data"]["sample"]["issues"] == 0, "跨社区看到样本了"


def test_settings_write_refuses_without_community(fresh_db):
    """拿不到社区 → **拒绝写入**（否则会落进全局键，把别的社区一起改掉）。

    注意这里要造一个**真没有社区**的网格员（库内 `community` 为空）：
    光把 JWT 里的 community 置空是拦不住的——`_tenant()` 会按 uid 回落到库内记录
    （这正是"租户只从服务端身份来"的设计，不是漏洞）。
    """
    from api_routes.agent import SimSettings, agent_governance_simulation_settings
    from data.db_settings import list_setting_keys
    with db_core.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
            "VALUES (99703, 'u99703', 'grid', '无社区网格', 1, '')")
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    r = agent_governance_simulation_settings(SimSettings(available_hours=8), _req(99703, com=""))
    assert _code(r) != 0, "没有社区归属竟然写进去了"
    assert not [k for k in list_setting_keys() if "人均可用工时" in k], \
        "被拒的写入不能留下全局键"
    # 顺带确认：JWT 空但有库内社区 → 按库内社区写（服务端身份优先，不是漏洞）
    ok = agent_governance_simulation_settings(SimSettings(available_hours=6), _req(99701, com=""))
    assert ok["code"] == 0 and f"人均可用工时@{A}" in list_setting_keys()
    # 空请求（两项都没填）也要拒绝，不能静默成功
    assert _code(agent_governance_simulation_settings(SimSettings(), _req(99701))) != 0


def test_settings_write_is_scoped_and_audited(fresh_db):
    """写入只影响本社区 + 留痕（`activity_log` 里有这条配置）。"""
    from api_routes.agent import SimSettings, agent_governance_simulation_settings
    from data.db_settings import list_setting_keys
    r = agent_governance_simulation_settings(SimSettings(available_hours=8, avg_minutes=40),
                                            _req(99701))
    assert r["code"] == 0 and r["data"]["available_hours"] == 8
    keys = list_setting_keys()
    assert f"人均可用工时@{A}" in keys, f"应按社区分键写入：{keys}"
    assert "人均可用工时" not in keys, "不许写全局键（会串到别的社区）"
    with db_core.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM activity_log "
                         "WHERE action LIKE '%治理情景参数%'").fetchone()["c"]
    assert n >= 1, "配置即留痕"
    # 非法值走接口也要明确报错，不能静默成功
    bad = agent_governance_simulation_settings(SimSettings(available_hours=-5), _req(99701))
    assert _code(bad) != 0 and _msg(bad)
