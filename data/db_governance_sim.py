# -*- coding: utf-8 -*-
"""治理情景模拟器（v4 收敛方案第 5 阶段）："诉求量要是涨了 X%，我们还扛不扛得住？"

为什么做这个：网格员现场最常问的一句是"你说的这套东西，人还是这么几个人，
量涨上来怎么办"。以前只能靠感觉答，或者现场口算。这一版把口算过程**固化成公式**，
并且**只用库里的真实数字**（窗口期工单量、已办结工单的实测处理时长），
把"假设"和"实测"分开放，谁都不许把假设当结论。

三条纪律（对外口径照抄这段）：

  ① **只读**：本模块不写任何业务表、不改工单状态。唯一的写操作是**配置项**
     （`人均可用工时` / `平均处理时长`，走 `data.db_settings`，按社区分键 + 留痕），
     那是"人给人算账用的参数"，不是业务数据。
  ② **公式透明**（页面上原样写出来，不做黑箱）：
     · 预计新增 = 样本量 × 增长率
     · 预计总量 = 样本量 + 预计新增
     · 预计总工时 = 预计总量 × 平均处理时长
     · 折算人手 = 预计总工时 ÷ 人均可用工时
  ③ **算不出来就说算不出来**（本项目最忌讳"做了但不生效/算了但没数字"）：
     · 样本 < 5 条 → 标「样本不足」；
     · 没有已办结工单 → 得不到实测平均处理时长 → 工时与人手**不给数字**，并说明原因；
     · 「人均可用工时」未配置 → 明确显示**"人均可用工时未配置，无法折算人手"**，
       **不许**拿一个默认值硬算出来糊弄人；
     · 结果一律标「**情景估算**」——不是预测、不是承诺、不是考核指标。

租户：`tenant_clause` fail-closed（空租户 → 返回空结构，绝不查全库）；
增长率/参数只能是"调用方给的情景假设"，页面上标清来源。
"""
import logging
from datetime import datetime, timedelta

from data.db_core import get_db
from data.db_settings import get_setting, set_setting
from utils.tenant import normalize_tenant, tenant_clause

_log = logging.getLogger(__name__)

MODULE = "治理模拟器"
#: 低于这个样本量就标"样本不足"（与 `data.db_issue_knowledge.MIN_SAMPLE` 同口径）
MIN_SAMPLE = 5
#: 配置键（按社区分键：`键@社区` → 全局 → 未配置）
KEY_AVAILABLE_HOURS = "人均可用工时"
KEY_AVG_MINUTES = "平均处理时长"
#: 增长率合法区间（百分数）：-90% ~ +500%
GROWTH_MIN, GROWTH_MAX = -90.0, 500.0
#: 所有对外文案里必须出现的标签——别让人把估算读成预测
LABEL = "情景估算"
DISCLAIMER = ("这是按下面四条公式做的**情景估算**，输入是「窗口期真实工单量」和"
              "「已办结工单的实测平均时长」，**不是预测**、不构成承诺，也不作为考核依据。")


def _f(v, default=None):
    """把配置/入参转成正数（非法值返回 default，并 warning——不静默当 0 用）。"""
    if v is None or v == "":
        return default
    try:
        x = float(v)
    except (TypeError, ValueError) as e:
        _log.warning("%s 配置不是数字（按未配置处理）：%r %s", MODULE, v, e)
        return default
    if x <= 0:
        _log.warning("%s 配置不是正数（按未配置处理）：%r", MODULE, x)
        return default
    return x


def get_sim_settings(tenant: str = "") -> dict:
    """读本社区的情景参数（配置项，按社区分键；读不到就是 None，不猜）。"""
    t = normalize_tenant(tenant) or None
    return {
        "available_hours": _f(get_setting(KEY_AVAILABLE_HOURS, tenant=t)),
        "avg_minutes": _f(get_setting(KEY_AVG_MINUTES, tenant=t)),
        "scope": t or "全局",
    }


def set_sim_settings(available_hours=None, avg_minutes=None, actor: str = "负责人",
                     tenant: str = "") -> dict:
    """写情景参数（**只对本社区生效**；单传一项时另一项不动）。写入即留痕。

    留痕里只记"谁把哪个参数改成了多少"，不含任何个人信息。
    """
    from data.db_notifications import log_activity
    t = normalize_tenant(tenant) or None
    scope = t or "全局"
    changed = {}
    if available_hours is not None:
        v = _f(available_hours)
        if v is None:
            raise ValueError("人均可用工时必须是正数（小时）")
        set_setting(KEY_AVAILABLE_HOURS, str(v), tenant=t)
        changed[KEY_AVAILABLE_HOURS] = v
    if avg_minutes is not None:
        v = _f(avg_minutes)
        if v is None:
            raise ValueError("平均处理时长必须是正数（分钟）")
        set_setting(KEY_AVG_MINUTES, str(v), tenant=t)
        changed[KEY_AVG_MINUTES] = v
    if changed:
        log_activity(actor, "配置治理情景参数", "settings", module=MODULE,
                     after_value="; ".join(f"{k}={v}" for k, v in changed.items()),
                     detail=f"[{scope}]治理情景模拟器参数：" +
                            "、".join(f"{k} {v}" for k, v in changed.items()))
    return get_sim_settings(tenant=tenant)


def _measured(days: int, tenant: str) -> tuple[int, float | None, int]:
    """窗口期内的真实数字：`(工单数, 实测平均处理小时, 已办结条数)`（全部来自本社区）。"""
    since = (datetime.now() - timedelta(days=max(1, min(days, 365)))).strftime("%Y-%m-%d %H:%M:%S")
    args: list = [since]
    tc = tenant_clause(tenant, args)
    if tc is None:
        return 0, None, 0
    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) c FROM community_issues WHERE reported_at>=?{tc}",
            tuple(args)).fetchone()["c"]
        rows = conn.execute(
            f"SELECT reported_at, resolved_at FROM community_issues "
            f"WHERE reported_at>=?{tc} AND resolved_at IS NOT NULL AND resolved_at<>''",
            tuple(args)).fetchall()
    hours = []
    for r in rows:
        try:
            a = datetime.fromisoformat(str(r["reported_at"]).replace("Z", ""))
            b = datetime.fromisoformat(str(r["resolved_at"]).replace("Z", ""))
            h = (b - a).total_seconds() / 3600
            if h >= 0:
                hours.append(h)
        except (TypeError, ValueError) as e:  # 时间戳脏数据：跳过并留痕，不当 0 用
            _log.warning("%s 跳过时间戳异常的工单（reported=%r resolved=%r）：%s",
                         MODULE, r["reported_at"], r["resolved_at"], e)
            continue
    avg = round(sum(hours) / len(hours), 2) if hours else None
    return int(total or 0), avg, len(hours)


def simulate_governance(days: int = 30, growth_pct: float = 0.0,
                        avg_minutes=None, available_hours=None,
                        tenant: str = "") -> dict:
    """算一次治理情景（**只读**）。

    参数
    ----
    days          : 观察窗口（1–365 天），决定"样本量"取哪段时间的工单
    growth_pct    : **情景假设**的增长率（百分数，-90 ~ +500）
    avg_minutes   : 平均处理时长（分钟）；不给就用「配置项 → 已办结实测均值 → 无」
    available_hours: 人均可用工时（小时/人/窗口期）；不给就用配置项，**再没有就是没有**
    tenant        : 社区（服务端身份传入，fail-closed）

    返回结构里 `sample` 是实测、`scenario` 是假设、`projected`/`workload` 是估算，
    三者**分开摆**，并在 `notes` 里逐条说明"数字怎么来的 / 为什么没有数字"。
    """
    # 窗口期：**只把 None 当"没给"**，不能写 `days or 30`——那会把 `days=0` 悄悄换成 30
    # （自己写测试时实测踩到：传 0 期望钳到 1 天，结果拿到 30 天，等于静默改了口径）
    if days is None:
        days = 30
    try:
        days = int(days)
    except (TypeError, ValueError):
        _log.warning("%s 窗口期不是整数（按 30 天处理）：%r", MODULE, days)
        days = 30
    days = max(1, min(days, 365))
    try:
        g = float(growth_pct or 0.0)
    except (TypeError, ValueError):
        _log.warning("%s 增长率不是数字（按 0 处理）：%r", MODULE, growth_pct)
        g = 0.0
    g = max(GROWTH_MIN, min(g, GROWTH_MAX))

    sample_n, measured_hours, resolved_n = _measured(days, tenant)
    cfg = get_sim_settings(tenant=tenant)

    # 平均处理时长：入参 → 配置项 → 实测均值；三者来源要标清楚，别混
    arg_avg = _f(avg_minutes)
    if arg_avg is not None:
        avg_min = arg_avg
        avg_src = "本次输入"
    elif cfg["avg_minutes"] is not None:
        avg_min = cfg["avg_minutes"]
        avg_src = f"配置项（{KEY_AVG_MINUTES}）"
    elif measured_hours is not None:
        avg_min = round(measured_hours * 60, 1)
        avg_src = f"实测办结耗时：{resolved_n} 条已办结工单从反映到办结的平均墙钟时间"
    else:
        avg_min, avg_src = None, ""

    arg_avail = _f(available_hours)
    if arg_avail is not None:
        avail, avail_src = arg_avail, "本次输入"
    elif cfg["available_hours"] is not None:
        avail, avail_src = cfg["available_hours"], f"配置项（{KEY_AVAILABLE_HOURS}）"
    else:
        avail, avail_src = None, ""

    new_n = int(round(sample_n * g / 100.0))
    total_n = sample_n + new_n

    total_hours = round(total_n * avg_min / 60.0, 1) if avg_min is not None else None
    staffing = (round(total_hours / avail, 2)
                if (total_hours is not None and avail is not None) else None)

    notes = []
    sample_enough = sample_n >= MIN_SAMPLE
    tenant_valid = bool(normalize_tenant(tenant))
    if not tenant_valid:
        # 没有社区归属 → 读取侧 fail-closed（返回空、绝不查全库）。这不是"样本不足"，
        # 是"不知道算哪个社区"，必须分开说，否则会让人以为"这个社区真的没有工单"。
        notes.append("缺少社区归属：已按空返回（绝不汇总全库数据），请用网格员账号登录后再看")
    elif not sample_enough:
        notes.append(f"样本不足（{sample_n} 条 < {MIN_SAMPLE} 条）：估算只作参考，别当结论")
    if avg_min is None:
        notes.append("没有已办结工单，算不出实测平均处理时长："
                     f"预计总工时与折算人手**不给数字**（请先在配置里填「{KEY_AVG_MINUTES}」）")
    elif avg_src.startswith("实测办结耗时"):
        # ⚠️ 这条提醒是实测后补的：demo 库里 34 条已办结工单的平均办结耗时 20.78 小时，
        # 302 单 × 20.78h ÷ 8h ≈ 784 人 —— 算术没错，但**口径错了**：
        # "从反映到办结"是墙钟时间（含等待、含休息、含别人手上的时间），
        # 不是"这条诉求实际占用了多少人工"。拿它乘会严重高估工时。
        # 所以这里必须把偏差说出来，而不是让页面给一个看着像样、其实离谱的数。
        notes.append("注意：当前平均处理时长取的是**办结耗时**（从反映到办结的墙钟时间，含等待），"
                     f"**不等于人工实际投入**，直接相乘会显著高估工时；"
                     f"要算人力请填「{KEY_AVG_MINUTES}」（每条诉求平均占用的人工分钟数）")
    if total_hours is not None and avail is None:
        notes.append(f"{KEY_AVAILABLE_HOURS}未配置，无法折算人手"
                     f"（请在配置里填「{KEY_AVAILABLE_HOURS}」，单位：小时/人/窗口期）")
    if new_n < 0:
        notes.append("增长率为负：预计总量低于样本量，属于「诉求下降」情景")

    return {
        "days": days,
        "label": LABEL,
        "disclaimer": DISCLAIMER,
        "tenant_valid": tenant_valid,
        "formulas": [
            "预计新增 = 样本量 × 增长率",
            "预计总量 = 样本量 + 预计新增",
            "预计总工时 = 预计总量 × 平均处理时长",
            "折算人手 = 预计总工时 ÷ 人均可用工时",
        ],
        "sample": {
            "issues": sample_n,
            "resolved": resolved_n,
            "measured_avg_hours": measured_hours,
            "min_sample": MIN_SAMPLE,
            "sufficient": sample_enough,
        },
        "scenario": {
            "growth_pct": round(g, 1),
            "source": "调用方给定的情景假设（**不是**预测值）",
        },
        "avg_minutes": {"value": avg_min, "source": avg_src},
        "available_hours": {"value": avail, "source": avail_src},
        "projected": {"new": new_n, "total": total_n},
        "workload": {"total_hours": total_hours, "staffing": staffing,
                     "staffing_unavailable_reason": (
                         "" if staffing is not None else
                         f"{KEY_AVAILABLE_HOURS}未配置，无法折算人手")},
        "notes": notes,
    }
