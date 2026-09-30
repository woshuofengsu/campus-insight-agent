# -*- coding: utf-8 -*-
"""本轮三项"计划内工程活"的门禁（v4 §6 B 栏 → 逐条落地）：

  ① 升级通知名单（`senior_manager_ids`）**有前端入口了**：接口可读可写、**只收本社区负责人**、
     空名单如实说明、写入留痕；跨社区 id 一律拒绝（否则天气超时告警会发到隔壁社区）。
  ② 通知类写操作**接上幂等键**：通知是"一对多"写操作（发一次 = 全社区各收一条），
     同一次意图重复/并发提交只能发一条；占位失败 = **fail-closed**（不许"状态未知还发一遍"）。
  ③ 治理指标：**重复报修率**（同人同分类跨天再报）+ **转人工原因分布**（按库里已有的原因字段分桶，
     先判安全红线/无依据，最后才判"主动要求"——否则"无法自动裁决，转人工处理"会被误归成主动要求）。
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
GRID_A = 99801
GRID_A2 = 99802
GRID_B = 99803
RESIDENT_A = 99810


@pytest.fixture()
def fresh_db():
    orig = db_core._DB_PATH
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tempfile.mkdtemp(prefix="gov_"), "g.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((GRID_A, "grid", "A网格甲", A),
                                     (GRID_A2, "grid", "A网格乙", A),
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


def _code(r) -> int:
    """`_ok` 返回 dict、`_fail` 返回 JSONResponse —— 统一取 code 再断言（少踩一层小坑）。"""
    if isinstance(r, dict):
        return int(r.get("code", -1))
    try:
        import json
        return int(json.loads(r.body.decode("utf-8")).get("code", -1))
    except Exception:  # noqa: BLE001
        return -1


def _data(r) -> dict:
    if isinstance(r, dict):
        return r.get("data") or {}
    try:
        import json
        return (json.loads(r.body.decode("utf-8")).get("data") or {})
    except Exception:  # noqa: BLE001
        return {}


def _msg(r) -> str:
    if isinstance(r, dict):
        return str(r.get("message") or "")
    try:
        import json
        return str(json.loads(r.body.decode("utf-8")).get("message") or "")
    except Exception:  # noqa: BLE001
        return ""


def _req(uid, role="grid", com=A):
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"n{uid}", "community": com,
    }), query_params={}, client=SimpleNamespace(host="127.0.0.1"))


# ------------------------------------------------ 跨层：前端生成的编号必须过得了服务端规则
def test_frontend_tokens_pass_backend_key_rule():
    """前端幂等编号必须满足服务端 `valid_key`（8–64 位 `[A-Za-z0-9_-]`）。

    为什么单列：这条规则**不满足时不会报错**——`begin/remember` 直接当"没带编号"处理，
    于是"带了 token 以为有幂等"变成静默失效（本轮实测就踩到：测试里用了 `tok-1` 这种 5 位编号，
    幂等看着完全没生效）。所以两头都要守：服务端不合规时**告警**（见 `api_routes/notices.py`），
    前端生成的编号**长度必须够**。
    """
    import io
    import os as _os
    import re as _re
    from data.db_idempotency import valid_key

    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                      "web", "src", "utils", "idemToken.js")
    src = io.open(p, encoding="utf-8").read()
    # ① 优先用 crypto.randomUUID（去掉横线后 32 位）② 兜底方案也得够长
    assert "randomUUID" in src, "前端没有优先用 crypto.randomUUID"
    m = _re.search(r"return 't' \+ Date\.now\(\)\.toString\(36\) \+ Math\.random\(\)\.toString\(36\)\.slice\(2, (\d+)\)", src)
    assert m, "找不到前端兜底编号的写法（改了就要同步本用例）"
    tail = int(m.group(1))
    # 't'(1) + base36 时间戳(8) + 随机尾巴 —— 必须 ≥ 8 位才过得了服务端
    assert 1 + 8 + tail >= 8, "前端兜底编号太短，会被服务端当成没带编号"
    assert valid_key("t" + "0" * 8 + "x" * tail), "兜底编号格式过不了服务端 valid_key"
    assert not valid_key("tok-1"), "自检失效：5 位编号竟然算合规"
    assert valid_key("0123456789abcdef0123456789abcdef")


# ---------------------------------------------------------------- ① 升级通知名单

def test_senior_managers_roundtrip_scope_and_audit(fresh_db):
    """写入 → 读回一致；**只对本社区生效**；留痕里有这条配置。"""
    from api_routes.weather import web_weather_senior_managers_get, web_weather_senior_managers_set
    from api_routes.weather import SeniorManagersSet
    from data.db_weather import get_senior_manager_ids

    r = web_weather_senior_managers_get(_req(GRID_A))
    assert r["code"] == 0, r
    assert r["data"]["scope"] == A, r["data"]
    ids = {c["id"] for c in r["data"]["candidates"]}
    assert {GRID_A, GRID_A2} <= ids, f"候选人应是本社区负责人：{r['data']['candidates']}"
    assert GRID_B not in ids, "别的社区的负责人不该出现在候选里"

    # 空名单是合法配置，但返回值要**说清楚后果**（否则"存了个空的还以为配好了"）
    out = web_weather_senior_managers_set(SeniorManagersSet(ids=[GRID_A2]), _req(GRID_A))
    assert out["code"] == 0 and out["data"]["ids"] == [GRID_A2]
    assert get_senior_manager_ids(tenant=A) == [GRID_A2]
    assert get_senior_manager_ids(tenant=B) == [], "配置必须按社区分键，不能串到 B 社区"

    empty = web_weather_senior_managers_set(SeniorManagersSet(ids=[]), _req(GRID_A))
    assert empty["code"] == 0 and empty["data"]["ids"] == []
    assert "无法升级" in empty["message"], f"空名单要说清后果：{empty}"
    with db_core.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM activity_log WHERE action LIKE '%更高级负责人%'"
                         ).fetchone()["c"]
    assert n >= 1, "配置即留痕：activity_log 里要有记录"


def test_senior_managers_rejects_cross_community_ids(fresh_db):
    """把隔壁社区的人塞进名单 = 天气超时告警会发错社区 → 必须拒绝（fail-closed）。"""
    from api_routes.weather import web_weather_senior_managers_set, SeniorManagersSet
    from data.db_weather import get_senior_manager_ids
    r = web_weather_senior_managers_set(SeniorManagersSet(ids=[GRID_A, GRID_B]), _req(GRID_A))
    assert _code(r) != 0, "跨社区名单竟然写进去了"
    assert str(GRID_B) in _msg(r), _msg(r)
    assert get_senior_manager_ids(tenant=A) == [], "被拒的写入不能留下半截数据"


def test_senior_managers_requires_grid_role(fresh_db):
    from api_routes.weather import web_weather_senior_managers_get, web_weather_senior_managers_set
    from api_routes.weather import SeniorManagersSet
    assert _code(web_weather_senior_managers_get(_req(RESIDENT_A, "resident"))) != 0
    assert _code(web_weather_senior_managers_set(
        SeniorManagersSet(ids=[GRID_A]), _req(RESIDENT_A, "resident"))) != 0


# ---------------------------------------------------------------- ② 通知写操作幂等

def _notice_body(**kw):
    from api_routes.notices import NoticeCreate
    base = dict(title="测试通知", notice_type="社区公告", publish_scope="全体居民",
                body="这是正文", is_urgent=0)
    base.update(kw)
    return NoticeCreate(**base)


def test_notice_create_is_idempotent_by_token(fresh_db):
    """同一次意图（同 token）连提交两次 → **只发一条通知**；第二次明确告诉调用方是重复。"""
    from api_routes.notices import web_notice_create
    from data.db_notice import get_notices_with_stats

    with db_core.get_db() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM notices").fetchone()["c"]
    r1 = web_notice_create(_notice_body(client_token="tok-notice-0001"), _req(GRID_A))
    assert _code(r1) == 0, r1
    nid = _data(r1)["notice_id"]
    r2 = web_notice_create(_notice_body(client_token="tok-notice-0001"), _req(GRID_A))
    assert _code(r2) == 0 and _data(r2).get("duplicate") is True, r2
    assert _data(r2)["notice_id"] == nid
    with db_core.get_db() as conn:
        after = conn.execute("SELECT COUNT(*) c FROM notices").fetchone()["c"]
    assert after == before + 1, f"连点两下建出了多条通知：{before} → {after}"
    assert get_notices_with_stats(limit=5, tenant=A) is not None


def test_notice_create_without_token_still_works(fresh_db):
    """不带 token 的旧调用方式照旧可用（幂等是加分项，不是新门槛）。"""
    from api_routes.notices import web_notice_create
    r = web_notice_create(_notice_body(), _req(GRID_A))
    assert _code(r) == 0 and _data(r)["notice_id"] > 0, r


def test_too_short_token_is_not_silently_ignored(fresh_db):
    """编号格式不合规时**不能静默当没带**（否则"以为有幂等、其实没有"）——至少要告警、且不报错。"""
    import logging

    from api_routes.notices import web_notice_create

    records: list[str] = []

    class _H(logging.Handler):
        def emit(self, rec):
            records.append(rec.getMessage())

    h = _H()
    lg = logging.getLogger("api_routes.notices")
    lg.addHandler(h)
    try:
        r = web_notice_create(_notice_body(title="短编号", client_token="tok-1"), _req(GRID_A))
    finally:
        lg.removeHandler(h)
    assert _code(r) == 0, "格式不合规不该直接失败（旧客户端照旧可用）"
    assert any("不合规" in m for m in records), f"短编号被静默忽略了：{records}"


def test_notice_publish_action_is_idempotent_by_token(fresh_db):
    """**发布**动作按 token 挡一层：同一次点击重试不会把同一条通知发两遍。"""
    from api_routes.notices import web_notice_action, NoticeAction
    from data.db_notice import create_notice

    nid = create_notice(title="待发布", notice_type="社区公告", publish_scope="全体居民",
                        body="正文", elderly_summary="", publisher="A网格甲", actor="A网格甲",
                        publisher_id=GRID_A)
    assert nid > 0
    a1 = web_notice_action(nid, NoticeAction(action="publish", client_token="tok-publish-001"),
                           _req(GRID_A))
    assert _code(a1) == 0, _msg(a1)
    a2 = web_notice_action(nid, NoticeAction(action="publish", client_token="tok-publish-001"),
                           _req(GRID_A))
    assert _code(a2) == 0 and _data(a2).get("duplicate") is True, a2
    assert "已经做过" in _msg(a2), _msg(a2)


def test_notice_idempotency_is_fail_closed_when_reservation_breaks(fresh_db):
    """**占位失败 = 不办**（fail-closed）：通知发出去收不回来，不能"状态未知还发一遍"。

    两条路都要守：① `begin` 返回 `unknown`（库忙/锁 → 框架层面的正常信号）→ 必须拒绝且**不建通知**；
    ② `begin` 直接抛异常（更严重的故障）→ 异常可以冒出去（FastAPI 会兜成 500），
    但**绝不能因此多出一条通知**。这就是"宁可让负责人刷新确认，也不重复发一遍"。
    """
    import data.db_idempotency as idem
    from api_routes.notices import web_notice_create

    # ① unknown 信号
    orig = idem.begin

    def _unknown(*a, **kw):
        return "unknown", None

    idem.begin = _unknown
    try:
        with db_core.get_db() as conn:
            before = conn.execute("SELECT COUNT(*) c FROM notices").fetchone()["c"]
        r = web_notice_create(_notice_body(title="不该发出去", client_token="tok-notice-boom"),
                              _req(GRID_A))
        with db_core.get_db() as conn:
            after = conn.execute("SELECT COUNT(*) c FROM notices").fetchone()["c"]
    finally:
        idem.begin = orig
    assert _code(r) == 2003, r
    assert "无法确认" in _msg(r), _msg(r)
    assert after == before, "占位拿到 unknown 竟然还建了通知（fail-open）"

    # ② 更严重的故障：抛异常也不许留下通知
    def _boom(*a, **kw):
        raise RuntimeError("模拟占位失败（库锁/磁盘错）")

    idem.begin = _boom
    try:
        with db_core.get_db() as conn:
            before2 = conn.execute("SELECT COUNT(*) c FROM notices").fetchone()["c"]
        with pytest.raises(RuntimeError):
            web_notice_create(_notice_body(title="也不该发出去", client_token="tok-notice-boom2"),
                              _req(GRID_A))
        with db_core.get_db() as conn:
            after2 = conn.execute("SELECT COUNT(*) c FROM notices").fetchone()["c"]
    finally:
        idem.begin = orig
    assert after2 == before2, "占位抛异常竟然还建了通知（fail-open）"


# ---------------------------------------------------------------- ③ 治理指标

def test_transfer_reason_buckets_order_matters():
    """分桶顺序：先安全红线、再无依据，最后才是主动要求（否则"无法自动裁决"会被误归）。"""
    from data.db_agent import _transfer_bucket
    assert _transfer_bucket("疑似紧急症状：转人工（停机点）") == "安全红线"
    assert _transfer_bucket("校验拦截：无法自动裁决，转人工处理") == "无依据"
    assert _transfer_bucket("用户主动要求转人工（T6）") == "主动要求"
    assert _transfer_bucket("") == "其它"
    assert _transfer_bucket("今天天气不错") == "其它"


def test_governance_metrics_are_tenant_scoped(fresh_db):
    """重复报修率与转人工分布**只算本社区**（派生指标跨社区汇总就是错数据）。"""
    from data.db_agent import get_governance_metrics, create_handoff

    # A 社区：同一人同一分类、跨两天各报一次 → 算一次重复
    with db_core.get_db() as conn:
        for day in ("-3 days", "-1 days"):
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, status, "
                "reporter_id, reported_at, tenant_id) VALUES (?,?,?,?,?,?, datetime('now',?), ?)",
                ("楼道灯坏了", "公共设施", "3号楼2单元", "灯不亮", "已解决", RESIDENT_A, day, A))
        conn.commit()
    m = get_governance_metrics(days=30, tenant=A)
    assert m["repeat"]["total"] == 2, m["repeat"]
    assert m["repeat"]["repeat_groups"] == 1
    assert m["repeat"]["rate"] == 100.0
    assert m["repeat"]["top"][0]["category"] == "公共设施"
    # B 社区看同一批数据 → 一条也看不到
    mb = get_governance_metrics(days=30, tenant=B)
    assert mb["repeat"]["total"] == 0 and mb["transfer"]["total"] == 0

    # 转人工分布：A 社区的处理包按原因分桶（`create_handoff` 按报告人所属社区自动盖章）
    create_handoff("s1", RESIDENT_A, "resident", "policy", "校验拦截：无法自动裁决，转人工处理",
                   {"original_input": "医保怎么报销"})
    create_handoff("s2", RESIDENT_A, "resident", "health", "疑似紧急症状：转人工（停机点）",
                   {"original_input": "老人一直咳嗽"})
    m2 = get_governance_metrics(days=30, tenant=A)
    assert m2["transfer"]["by_reason"]["无依据"] == 1, m2["transfer"]
    assert m2["transfer"]["by_reason"]["安全红线"] == 1, m2["transfer"]
    assert m2["transfer"]["by_source"]["处理包"] == 2


def test_governance_metrics_rejects_missing_tenant(fresh_db):
    """不传租户 = 不知道怎么收口 → 返回空而不是查全库（与读取侧 fail-closed 一致）。"""
    from data.db_agent import get_governance_metrics
    m = get_governance_metrics(days=30, tenant="")
    assert m["repeat"]["total"] == 0 and m["transfer"]["total"] == 0
