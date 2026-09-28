# -*- coding: utf-8 -*-
"""修复历史遗留的"废单"与占位假号（v3 卡1 的**数据侧**收尾）。

背景（在演示库实测到，不是假设）：
  1. **位置退化成社区名的工单**：老年端旧代码在位置提取失败时回落成 `profile.community` /
     字面量"社区"，照样建单 → 库里留下 `location='社区'` 的记录。这类工单**网格员没法去修**
     （不知道哪栋楼），老人却以为报上去了。
  2. **占位假手机号**：旧代码在资料无手机号时写死 `"13800000000"` 加密入库
     —— 工单里躺着一个打不通的号码，属于**编造数据**。

本脚本的两种处理，都遵守"不编造"：
  · 位置：先用**工单标题**重新抽取（`utils.elderly_report`）；抽取不到就用**报修人登记资料**里的
    楼栋/单元（有记录、可追溯）；两者都没有 → **不改**，仅列出来让人工处理。
  · 假号：**清空** `reporter_phone_enc`（我们并不知道老人的真实号码，不能编一个填上），
    并在 `activity_log` 留一条明确的修复留痕。

用法：
  python scripts/fix_legacy_elderly_reports.py            # 只体检（dry-run，默认）
  python scripts/fix_legacy_elderly_reports.py --apply    # 真正修复（先自动备份库文件）
"""
import argparse
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from data import db_core  # noqa: E402
from data.db_repair import _dec_phone  # noqa: E402
from utils.elderly_report import extract_report_fields  # noqa: E402

FAKE_PHONE = "13800000000"
DEGENERATE_LOCATIONS = ("社区", "小区", "")
UNKNOWN_LOCATION = "（位置待核实）"


def _profile_of(conn, uid):
    if not uid:
        return {}
    row = conn.execute(
        "SELECT building, unit, community, name FROM user_profile WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else {}


def scan() -> dict:
    """体检：返回需要处理的工单（不改任何数据）。"""
    db_core.init_db(config.DB_PATH)
    degenerate, fake_phone = [], []
    with db_core.get_db() as conn:
        for r in conn.execute(
            "SELECT id, title, location, reporter_id, reporter_name, status, reporter_phone_enc "
            "FROM community_issues ORDER BY id").fetchall():
            row = dict(r)
            if (row.get("location") or "") in DEGENERATE_LOCATIONS:
                prof = _profile_of(conn, row.get("reporter_id"))
                fields = extract_report_fields(row.get("title") or "", prof)
                row["_profile"] = prof
                row["_suggested"] = fields["fields"]["location"]
                row["_suggested_src"] = fields["sources"]["location"]
                degenerate.append(row)
            plain = _dec_phone(row.get("reporter_phone_enc") or "", "")
            if plain == FAKE_PHONE:
                fake_phone.append(row)
    return {"degenerate_location": degenerate, "fake_phone": fake_phone}


def _backup() -> str:
    src = config.DB_PATH
    dst = os.path.join(os.path.dirname(src),
                       f"db-backup-before-location-fix-{datetime.now():%Y%m%d-%H%M%S}.db")
    shutil.copy2(src, dst)
    return dst


def apply(found: dict) -> dict:
    """修复：位置能补的补上，假号清空；补不了的如实列出来（不猜）。"""
    dst = _backup()
    print(f"已备份：{dst}")
    fixed_loc, unfixable, cleared = [], [], []
    with db_core.get_db() as conn:
        for row in found["degenerate_location"]:
            new_loc = row.get("_suggested") or ""
            if new_loc and new_loc not in DEGENERATE_LOCATIONS:
                conn.execute("UPDATE community_issues SET location=? WHERE id=?",
                             (new_loc, row["id"]))
                conn.execute(
                    "INSERT INTO activity_log (actor, action, target_type, target_id, "
                    "target_title, module, before_value, after_value, detail) "
                    "VALUES ('系统', '修复废单位置', 'issue', ?, ?, '报修', ?, ?, ?)",
                    (row["id"], row["title"], row.get("location") or "", new_loc,
                     f"v3 卡1 数据修复：位置由「{row.get('location') or '空'}」补为「{new_loc}」"
                     f"（来源：{row.get('_suggested_src')}）；原工单无法派单，网格员看不到具体地点"))
                fixed_loc.append((row["id"], row.get("location") or "", new_loc))
            else:
                # 抽不出来就**不猜**：但也不能让它挂着"社区"这种看起来像真实地点的值
                # （网格员会以为已经有位置了）。改成明确的"待核实"标记 + 留痕。
                conn.execute("UPDATE community_issues SET location=? WHERE id=?",
                             (UNKNOWN_LOCATION, row["id"]))
                conn.execute(
                    "INSERT INTO activity_log (actor, action, target_type, target_id, "
                    "target_title, module, before_value, after_value, detail) "
                    "VALUES ('系统', '标记位置待核实', 'issue', ?, ?, '报修', ?, ?, ?)",
                    (row["id"], row["title"], row.get("location") or "", UNKNOWN_LOCATION,
                     "v3 卡1 数据修复：标题与报修人资料里都问不出地点，**不猜**；"
                     "改为显式待核实标记，需网格员电话/上门核实后补录"))
                unfixable.append((row["id"], row.get("title") or "", row.get("location") or ""))
        for row in found["fake_phone"]:
            conn.execute("UPDATE community_issues SET reporter_phone_enc='' WHERE id=?", (row["id"],))
            conn.execute(
                "INSERT INTO activity_log (actor, action, target_type, target_id, "
                "target_title, module, before_value, after_value, detail) "
                "VALUES ('系统', '清除占位假手机号', 'issue', ?, ?, '报修', ?, '', ?)",
                (row["id"], row["title"], "13800000000（占位假号）",
                 "旧代码在用户无手机号时写死 13800000000；我们没有真实号码，故清空并留痕，"
                 "由网格员上门/电话补录，不编造"))
            cleared.append(row["id"])
        conn.commit()
    return {"fixed_location": fixed_loc, "unfixable": unfixable, "cleared_fake_phone": cleared,
            "backup": dst}


def main() -> int:
    ap = argparse.ArgumentParser(description="修复历史遗留的废单位置与占位假号（默认只体检）")
    ap.add_argument("--apply", action="store_true", help="真正写库（会先自动备份）")
    args = ap.parse_args()

    found = scan()
    deg, fake = found["degenerate_location"], found["fake_phone"]
    print("=" * 72)
    print(f"位置退化成社区名/空的工单：{len(deg)} 条")
    for r in deg:
        print(f"  #{r['id']} 「{(r['title'] or '')[:28]}」 location={r.get('location')!r}"
              f" → 可补为 {r.get('_suggested')!r}（来源 {r.get('_suggested_src')}）")
    print(f"占位假手机号（13800000000）的工单：{len(fake)} 条")
    for r in fake:
        print(f"  #{r['id']} 「{(r['title'] or '')[:28]}」 reporter={r.get('reporter_name')}")
    print("=" * 72)

    if not args.apply:
        print("（dry-run，未改动任何数据；加 --apply 执行修复）")
        return 0

    res = apply(found)
    print(f"已补位置：{len(res['fixed_location'])} 条")
    for iid, old, new in res["fixed_location"]:
        print(f"  #{iid}: {old!r} → {new!r}")
    if res["unfixable"]:
        print(f"⚠️ 补不了的（标题与资料里都问不出地点，需人工核实，**未擅自改动**）：{len(res['unfixable'])} 条")
        for iid, title, loc in res["unfixable"]:
            print(f"  #{iid} 「{title[:30]}」 location={loc!r}")
    print(f"已清空占位假号：{len(res['cleared_fake_phone'])} 条 {res['cleared_fake_phone']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
