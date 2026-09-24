# -*- coding: utf-8 -*-
"""P4 老年健康记录（血压/血糖）测试。

三层：
1. 纯逻辑层 `data/_vitals_logic.py`：分级阈值 + **文案不得含诊断句式**（这是本模块最容易越界处）；
2. 数据层 `data/db_vitals.py`：录入校验（荒谬值/缺值）、排序、趋势、回填幂等；
3. 迁移 v47：表结构存在 + 历史血压能搬进来 + 可重复执行。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UID = 95001

# 诊断句式黑名单（与 agent/verifier.py 的口径对齐：只提醒、不下结论）
FORBIDDEN = ["确诊", "您是", "患了", "得了", "诊断为", "属于高血压", "属于糖尿病", "病人"]


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    _tmp = tempfile.mkdtemp(prefix="vitals_")
    _path = os.path.join(_tmp, "vitals.db")
    db_core._DB_PATH = ""
    if os.path.exists(_path):
        os.unlink(_path)
    db_core.init_db(_path)
    with db_core.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active) "
                     "VALUES (?, 'elder95001', 'elderly', '张大爷', 1)", (UID,))
        conn.commit()
    yield
    db_core._DB_PATH = _orig


# ---------------- 1. 纯逻辑层 ----------------

def test_bp_levels_thresholds():
    from data._vitals_logic import classify_bp
    assert classify_bp(120, 80)[0] == "normal"
    assert classify_bp(140, 85)[0] == "attention"      # 收缩压达标线
    assert classify_bp(130, 90)[0] == "attention"      # 舒张压达标线
    assert classify_bp(85, 55)[0] == "attention"       # 偏低
    assert classify_bp(185, 95)[0] == "alert"          # 明显偏高
    assert classify_bp(130, 115)[0] == "alert"


def test_glucose_levels_thresholds():
    from data._vitals_logic import classify_glucose
    assert classify_glucose(5.2, "fasting")[0] == "normal"
    assert classify_glucose(7.2, "fasting")[0] == "attention"
    assert classify_glucose(11.5, "postprandial")[0] == "attention"
    assert classify_glucose(3.5, "fasting")[0] == "alert"   # 低血糖更急
    assert classify_glucose(6.5, "postprandial")[0] == "normal"


def test_missing_values_do_not_guess():
    from data._vitals_logic import classify, classify_bp
    assert classify_bp(None, None)[0] == "normal"
    assert classify_bp("abc", None)[0] == "normal"
    assert classify("unknown_kind", 200, 120)[0] == "normal", "未知类型不准乱判"


def test_hint_copy_has_no_diagnosis_wording():
    """文案是固定出口，绝不能出现诊断句式（这是老年健康内容的红线）。"""
    from data._vitals_logic import hint_of
    for level in ("normal", "attention", "alert"):
        text = hint_of(level)
        if level == "normal":
            assert "保持" in text or "范围" in text
        else:
            assert "建议" in text and ("社区医生" in text or "家属" in text), \
                f"{level} 的文案必须给出该找谁的出口：{text}"
        for bad in FORBIDDEN:
            assert bad not in text, f"文案出现诊断句式「{bad}」：{text}"


def test_every_classified_hint_is_clean():
    """所有分级结果的文案都要过黑名单（防止以后加新分支漏审）。"""
    from data._vitals_logic import classify_bp, classify_glucose
    samples = [(classify_bp(120, 80)), (classify_bp(190, 120)), (classify_bp(85, 55)),
               (classify_glucose(5.0, "fasting")), (classify_glucose(12.0, "postprandial")),
               (classify_glucose(3.0, "fasting"))]
    for _level, hint in samples:
        for bad in FORBIDDEN:
            assert bad not in hint


# ---------------- 2. 数据层 ----------------

def test_add_and_list_bp_desc():
    from data.db_vitals import add_vital, list_vitals
    for i, (s, d) in enumerate([(130, 85), (145, 92), (138, 88)]):
        vid, level, meta = add_vital(UID, "bp", sys_=s, dia=d,
                                     measured_at=f"2026-09-{10 + i:02d} 08:00:00")
        assert vid > 0
    rows = list_vitals(UID, "bp", limit=7)
    assert len(rows) == 3
    assert rows[0]["sys"] == 138, "必须按 measured_at 倒序（最新在前）"
    assert rows[0]["level"] in ("normal", "attention", "alert")
    assert rows[0]["level_hint"]


def test_trend_returns_at_most_limit():
    from data.db_vitals import add_vital, list_vitals
    for i in range(8):
        add_vital(UID, "glucose", glucose=5.0 + i * 0.1,
                  measured_at=f"2026-09-{10 + i:02d} 07:00:00")
    assert len(list_vitals(UID, "glucose", limit=7)) == 7


def test_absurd_values_rejected():
    from data.db_vitals import add_vital
    assert add_vital(UID, "bp", sys_=900, dia=80)[0] == 0
    assert add_vital(UID, "bp")[0] == 0, "血压不给值必须拒绝"
    assert add_vital(UID, "glucose")[0] == 0
    assert add_vital(UID, "glucose", glucose=99)[0] == 0
    assert add_vital(UID, "weight", glucose=5)[0] == 0, "不支持的类型必须拒绝"
    assert add_vital(0, "bp", sys_=120, dia=80)[0] == 0


def test_summary_shape_and_labels():
    from data.db_vitals import add_vital, vitals_summary
    add_vital(UID, "bp", sys_=150, dia=95, measured_at="2026-09-20 08:00:00")
    add_vital(UID, "bp", sys_=135, dia=85, measured_at="2026-09-21 08:00:00")
    s = vitals_summary(UID)
    assert s["latest_bp"]["sys"] == 135
    assert len(s["bp_trend"]) >= 2
    assert "偏高" in s["bp_trend_label"] or "偏低" in s["bp_trend_label"] or "平稳" in s["bp_trend_label"]


# ---------------- 3. 迁移与回填 ----------------

def test_v47_table_and_backfill():
    """v47 把 elderly_profile.health_info 里的历史血压搬进新表（幂等）。"""
    from data.db_vitals import backfill_from_profile, list_vitals
    with db_core.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO elderly_profile (user_id, health_info) VALUES (?, ?)",
                     (UID, '{"blood_pressure": [{"date": "2026-08-12", "sys": 152, "dia": 92}]}'))
        conn.commit()
    first = backfill_from_profile()
    second = backfill_from_profile()
    assert first >= 1 and second == 0, "回填必须幂等"
    rows = [r for r in list_vitals(UID, "bp", limit=50) if r["source"] == "backfill"]
    assert rows and rows[0]["sys"] == 152 and rows[0]["dia"] == 92


def test_schema_version_is_47():
    with db_core.get_db() as conn:
        v = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert v >= 47, f"schema 版本应至少 v47（健康记录），实际 {v}"
