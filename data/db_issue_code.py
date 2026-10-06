# -*- coding: utf-8 -*-
"""对外事项编号 + 工作人员查询（阶段 2 · 服务台线的地基）。

两件事，都是为了回答真实社区里最常出现的一句话："**刚才那位老人的事，办到哪了？**"

## 一、对外事项编号（`issue_code`）

- 格式：`A` + `年月` + `4 位当月序号`，例如 `A26090001`（2026 年 9 月第 1 单）。
- **为什么不用自增 id**：`WO00000012` 这种写法虽然换了前缀，但**数字就是主键**——
  任何人拿两个编号一比就能数出"你们一共多少单"，还能顺序枚举别人的工单。
  对外编号与内部主键**彻底解耦**，这是"编号可以给外人看"的前提。
- **老人不需要记住它**：编号是给**工作人员**查的（姓名 / 手机后四位 / 楼栋 / 时间 / 编号 五选一）。
  这条写进材料，避免做成"让老人背编号"的反适老设计。
- 唯一性由**唯一索引**兜底；并发下靠"分配→插入失败→重试"保证不重号。

## 二、工作人员查询（`staff_search`）

三条硬规矩（对应 AGENTS 的多租户与隐私口径）：

1. **自动带当前社区**（`tenant_clause`，fail-closed：空社区返回空、不传租户抛错）；
2. **手机号只按后四位查**，且**结果里手机号一律脱敏**——绝不允许"前端传完整手机号来查"，
   那等于把手机号变成了查询凭据；
3. **多条命中要求进一步确认**：命中 > 1 条时不猜是哪一条，把候选列出来让工作人员确认。
"""
import logging
import re
from datetime import datetime

from data.db_core import get_db
from utils.tenant import tenant_clause

_log = logging.getLogger(__name__)

MODULE = "事项编号"

#: 渠道取值（**与材料口径一致**，改这里要同步 docs/eval/社区试点方案-v1.md）
CHANNELS = {
    "elderly_self": "老人自助",
    "resident_self": "居民自助",
    "family_assisted": "家属代办",
    "grid_recorded": "网格员代录",
    "service_desk_tablet": "服务站平板",
    "phone_manual": "电话人工",
}
#: 这些渠道下"操作人 ≠ 问题所属人"，试点指标必须把两者分开算
ASSISTED_CHANNELS = {"family_assisted", "grid_recorded", "service_desk_tablet", "phone_manual"}

#: 对外编号：A + YYMM（4 位）+ 4 位序号，共 9 个字符，例如 A26100001
#: ⚠️ 第一版写成 `A\d{6}\d{4}`（6+4）是错的——`%y%m` 只有 4 位。**是我自己的用例抓出来的**：
#: 生成的号是 `A26100001`，正则却说它"格式不对"。判据与实现必须对齐，否则校验会把正确的号拒掉。
_CODE_RE = re.compile(r"^A\d{4}\d{4}$")
#: 手机号后四位（只允许这一种手机号查询方式）
_TAIL_RE = re.compile(r"^\d{4}$")


def _period(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%y%m")


def format_code(period: str, seq: int) -> str:
    return f"A{period}{seq:04d}"


def is_valid_code(code: str) -> bool:
    return bool(_CODE_RE.match((code or "").strip()))


def next_issue_code(conn, now: datetime | None = None) -> str:
    """在当前连接上分配下一个对外编号（**原子自增**）。

    用 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` 一步拿到新序号，避免"先查后写"的竞态
    （两个并发提交拿到同一个号 → 唯一索引报错 → 工单建不出来）。
    这条 SQL 在 SQLite 3.35+ 与 PostgreSQL 上都可用（见 `PG迁移盘点与计划.md`）。
    """
    period = _period(now)
    row = conn.execute(
        "INSERT INTO issue_code_seq (period, seq, updated_at) "
        "VALUES (?, 1, CURRENT_TIMESTAMP) "
        "ON CONFLICT(period) DO UPDATE SET seq = seq + 1, updated_at = CURRENT_TIMESTAMP "
        "RETURNING seq", (period,)).fetchone()
    seq = int(row[0] if not isinstance(row, dict) else row["seq"])
    return format_code(period, seq)


def ensure_issue_code(conn, issue_id: int, now: datetime | None = None) -> str:
    """给一条**还没有编号**的工单补一个（幂等：已有则原样返回）。

    为什么要这个函数：历史工单（v54 之前建的）没有编号，而工作人员查询依赖它。
    补号是**幂等**的，重复调用不会换号——编号一旦给出就必须稳定，否则工作人员手里的号会失效。
    """
    row = conn.execute("SELECT issue_code FROM community_issues WHERE id=?",
                       (issue_id,)).fetchone()
    if row is None:
        return ""
    cur = (row["issue_code"] if not isinstance(row, tuple) else row[0]) or ""
    if cur:
        return cur
    for _ in range(5):                      # 极少数并发下换号重试
        code = next_issue_code(conn, now=now)
        try:
            conn.execute("UPDATE community_issues SET issue_code=? WHERE id=? AND COALESCE(issue_code,'')=''",
                         (code, issue_id))
            conn.commit()
        except Exception as e:  # noqa: BLE001 — 撞唯一索引就换一个号再试
            _log.warning("%s 分配编号撞车（重试）：issue=%s code=%s err=%s", MODULE, issue_id, code, e)
            continue
        row2 = conn.execute("SELECT issue_code FROM community_issues WHERE id=?",
                            (issue_id,)).fetchone()
        got = (row2["issue_code"] if not isinstance(row2, tuple) else row2[0]) or ""
        if got:
            return got
    _log.warning("%s 多次分配失败：issue=%s（保持无编号，由工作人员按姓名/楼栋查）", MODULE, issue_id)
    return ""


def _mask_phone(row: dict) -> str:
    """结果里手机号一律脱敏（明文列在库里本就为空，这里兜住密文/回显）。"""
    enc = (row.get("reporter_phone_enc") or "")
    plain = (row.get("reporter_phone") or "")
    if plain:
        try:
            from data.db_repair import _mask_phone as _m
            return _m(plain)
        except Exception:  # noqa: BLE001
            return "***"
    if enc:
        try:
            from data.db_repair import _dec_phone, _mask_phone as _m
            return _m(_dec_phone(enc, "")) or "***"
        except Exception as e:  # noqa: BLE001
            _log.warning("%s 解密手机号失败（按掩码返回）：%s", MODULE, e)
            return "***"
    return ""


def staff_search(tenant: str, *, code: str = "", name: str = "", phone_tail: str = "",
                 building: str = "", date: str = "", limit: int = 20) -> dict:
    """工作人员查询：**编号 / 姓名 / 手机后四位 / 楼栋 / 提交日期** 五选一（可组合）。

    返回 `{"items": [...], "count": n, "need_confirm": bool, "note": str}`。

    - 全部按**当前社区**收口（`tenant_clause`，空社区返回空、不传租户抛 ValueError）；
    - 手机号**只接受后四位**（传别的格式直接拒绝，不是"尽力匹配"）；
    - 命中多条时 `need_confirm=True`，**不替工作人员猜是哪一条**；
    - 结果脱敏（手机号掩码、不含密文）。
    """
    args: list = []
    qargs: list = []
    targs: list = []
    tc = tenant_clause(tenant, targs)
    empty = {"items": [], "count": 0, "need_confirm": False,
             "note": "缺少社区归属或没有匹配（不会跨社区查询）"}
    if tc is None:
        return empty

    # 手机号只允许后四位：给了别的格式就明确报错，不"尽力匹配"
    tail = (phone_tail or "").strip()
    if tail and not _TAIL_RE.match(tail):
        return {"items": [], "count": 0, "need_confirm": False,
                "note": "手机号只支持**后四位**查询（不要输入完整号码）"}

    where = ["1=1"]
    if code:
        if not is_valid_code(code):
            return {"items": [], "count": 0, "need_confirm": False,
                    "note": "事项编号格式应为 A+年月+4 位序号，例如 A26100001"}
        where.append("issue_code = ?")
        qargs.append(code.strip())
    if name:
        where.append("reporter_name LIKE ?")
        qargs.append(f"%{name.strip()}%")
    if building:
        where.append("location LIKE ?")
        qargs.append(f"%{building.strip()}%")
    if date:
        # ⚠️ 用 `substr` 而不是 `date(reported_at)`：`date()` 是 **SQLite 专属**
        # （Postgres 要 `CAST(col AS date)`），`reported_at` 存的就是 'YYYY-MM-DD HH:MM:SS'，
        # 取前 10 位两边都能跑。刚写完 `PG迁移盘点与计划.md` 就别再新增方言依赖了。
        where.append("substr(reported_at, 1, 10) = ?")
        qargs.append(date.strip())

    # ⚠️ `tenant_clause` 返回的片段**自带 `AND`**（形如 ` AND tenant_id=?`），
    # 不能再拼一个 `AND` 上去 —— 实测踩到：拼成 `1=1 AND  AND tenant_id=?` 直接语法错。
    w = " AND ".join(where) + (tc or "")
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT id, issue_code, title, category, status, reporter_name, location, "
            f"reported_at, submission_channel, operator_user_id, is_demo, "
            f"reporter_phone, reporter_phone_enc "
            f"FROM community_issues WHERE {w} ORDER BY id DESC LIMIT ?",
            (*qargs, *targs, max(1, min(limit, 100)))).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        tail_match = True
        if tail:
            # 后四位比对在应用层做（避免把完整手机号塞进 SQL 比较）
            masked = _mask_phone(d)
            tail_match = masked.replace("*", "").endswith(tail) or masked.endswith(tail)
        if not tail_match:
            continue
        items.append({
            "issue_id": d["id"],
            "issue_code": d.get("issue_code") or "",
            "title": (d.get("title") or "")[:40],
            "category": d.get("category") or "",
            "status": d.get("status") or "",
            "reporter_name": d.get("reporter_name") or "",
            "reporter_phone_masked": _mask_phone(d),
            "location": d.get("location") or "",
            "reported_at": (d.get("reported_at") or "")[:16],
            "channel": d.get("submission_channel") or "",
            "channel_label": CHANNELS.get(d.get("submission_channel") or "", "未记录"),
            "operator_user_id": int(d.get("operator_user_id") or 0),
            "is_demo": int(d.get("is_demo") or 0),
        })
    note = ""
    if not items:
        note = "没有匹配。可换一种方式查（姓名 / 手机后四位 / 楼栋 / 提交日期 / 事项编号）。"
    elif len(items) > 1:
        note = f"命中 {len(items)} 条，请让居民再确认一下（别替他猜是哪一条）。"
    return {"items": items, "count": len(items),
            "need_confirm": len(items) > 1, "note": note}


__all__ = ["CHANNELS", "ASSISTED_CHANNELS", "format_code", "is_valid_code",
           "next_issue_code", "ensure_issue_code", "staff_search"]
