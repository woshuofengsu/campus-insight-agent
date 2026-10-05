# -*- coding: utf-8 -*-
"""为「人工修正对照清单」准备**真实**演示数据（收敛方案第 6–7 阶段的现场素材）。

⚠️ 这份脚本做的是"**用真实链路造演示数据**"，不是往库里塞假数：
  ① 老人报修走**真实接口**（`/api/web/elderly/report/submit`）——分类由系统真的判一遍
     （LLM 开了就走 LLM，没配 key 就走关键词兜底），`suggested_category` 由写入侧真的落库；
  ② 人工修正走**真实接口**（`/api/web/issues/{id}/action` 的 `update_category`）——
     网格员身份、状态机、留痕（`activity_log`）全走一遍，不是直接 UPDATE 库。
  因此清单里出现的每一行，都能在库内找到对应的工单行 + 修改留痕，答辩时可直接下钻复算。

用法（**服务必须在跑**）：
    python scripts/seed_category_demo.py            # 造 4 条（其中 2 条被人工改分类）
    python scripts/seed_category_demo.py --dry-run  # 只看会做什么，不写库

幂等：每条报修带固定 `client_token`，重复跑不会重复建单（服务端幂等表挡住）；
修正过一次的分类不会再次修改（同分类会返回"分类未变化"）。
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("CI_BASE", "http://127.0.0.1:8000")

#: 老人原话（要覆盖"系统判对"和"系统判错被人工纠正"两种情形）
#: ⚠️ 两个契约必须一起满足，否则会被**如实拦下、不建单**（那是契约在生效，不是 bug）：
#:   ① 位置要能抽出「楼栋 + 单元」（老人端会逐字追问"哪栋楼的哪一层"）；
#:   ② 分不清是"家里的事"还是"公共地方的事"时，老人端会追问责任范围，
#:      第二步要由老人**点选**一次 —— 所以脚本按"老人点选的结果"把 `scope` 传进去，
#:      等同浏览器里那两次点击（不是替老人编答案，因为选择本身还是要人来点）。
#: 实测踩到：只传一句原话、不传 scope，噪音类会被追问"这个是您家里的事，还是公共地方？"
CASES = [
    # (老人原话, 老人第一步点选的责任范围, 期望人工修正成什么分类 / 不改则留空, 说明)
    ("3号楼2单元楼道灯不亮了，晚上上下楼看不见",
     "室外", "", "普通报修：系统判完就完事，用来体现「一致」的那一格"),
    ("3号楼2单元楼下垃圾桶满了好几天没人清，味道很大",
     "室外", "", "环境卫生类：同样看系统判得准不准"),
    ("2号楼1单元楼道里有人半夜装修电钻响，吵得睡不着",
     "室外", "噪音扰民", "系统可能判成别的（如邻里矛盾/物业服务）→ 网格员按实际情况改一次"),
    ("5号楼1单元门口电动车乱停把消防通道堵了",
     "室外", "安全隐患", "涉及安全隐患 → 网格员改成「安全隐患」并说明理由"),
    ("1号楼3单元电梯里的灯忽明忽暗，看着心里发慌",
     "室外", "", "设施维修类：第五条用来把样本凑到阈值（5 条）以上，否则清单只能标「样本不足」"),
]


def _post(path, body, token=""):
    req = urllib.request.Request(
        BASE + path, method="POST", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {"code": -1, "message": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"code": -1, "message": str(e)}


def _get(path, token=""):
    req = urllib.request.Request(BASE + path, headers=(
        {"Authorization": f"Bearer {token}"} if token else {}))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"code": -1, "message": str(e)}


def _tok(role):
    r = _post("/api/web/auth/demo", {"role": role})
    if r.get("code") != 0:
        raise SystemExit(f"演示登录失败（role={role}）：{r.get('message')}")
    return (r.get("data") or {}).get("token") or ""


def _mark_existing_demo_rows() -> int:
    """把**此前造过**的演示工单补上 `is_demo=1`（v53 之前造的没有标记）。

    为什么需要：`is_demo` 是 v53 才加的列，之前那批演示工单会被当成真实样本混进分母。
    可靠的联系方式是**幂等表**：每次提交都用固定 token（`seedcat…`），
    而 `idempotency_keys.result_json` 里存着 `issue_id` —— 所以能精确定位，不靠标题猜。

    ⚠️ 这是**演示数据维护**（不是业务功能）：只动演示库、只改 `is_demo` 这一列、
    打印改了哪几条、可重复跑（已标的不会重复处理）。
    """
    import sqlite3
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT result_json FROM idempotency_keys "
            "WHERE scope='elderly_report' AND key LIKE 'seedcat%'").fetchall()
        ids = []
        for (rj,) in rows:
            try:
                iid = int((json.loads(rj or "{}") or {}).get("issue_id") or 0)
            except (TypeError, ValueError):
                continue
            if iid:
                ids.append(iid)
        if not ids:
            print("  （没找到此前造的演示工单，无需补标）")
            return 0
        marks = ",".join("?" * len(ids))
        changed = conn.execute(
            f"UPDATE community_issues SET is_demo=1 WHERE id IN ({marks}) "
            f"AND COALESCE(is_demo,0)=0", tuple(ids)).rowcount
        conn.commit()
        total = conn.execute(
            f"SELECT COUNT(*) FROM community_issues WHERE id IN ({marks}) AND is_demo=1",
            tuple(ids)).fetchone()[0]
        print(f"  [补标] 认定为演示数据 {total} 条（本次新标 {changed} 条，其余此前已标）")
        return total
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写库")
    ap.add_argument("--mark-existing", action="store_true",
                    help="只把此前造的演示工单补上 is_demo=1（演示数据维护，不动业务数据）")
    args = ap.parse_args()

    if args.mark_existing:
        if args.dry_run:
            print("--dry-run：未写库（--mark-existing 会打印将补标的条数）")
        else:
            _mark_existing_demo_rows()
        return 0

    print("=" * 74)
    print("为「人工修正对照清单」准备真实演示数据")
    print("=" * 74)
    for text, scope, fix_to, why in CASES:
        print(f"  老人原话：{text}（第一步点选：{scope}）")
        print(f"    → 人工修正为：{fix_to or '（不修改，保持系统分类）'}　【{why}】")
    if args.dry_run:
        print("\n--dry-run：未写库。")
        return 0

    elderly_tok = _tok("elderly")
    grid_tok = _tok("grid")
    print(f"\n老人/网格员演示 token 就绪（长度 {len(elderly_tok)} / {len(grid_tok)}）")

    made = []
    for i, (text, scope, fix_to, _why) in enumerate(CASES):
        # 固定 token：重复跑不会重复建单（服务端幂等）
        tok = "seedcat" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        r = _post("/api/web/elderly/report/submit",
                  {"text": text, "scope": scope, "client_token": tok,
                   # v53：**明确标记成演示数据**——它们会和真实工单进同一张统计表，
                   # 不标记就等于把自造样本算成真实样本（面板会对演示部分固定显示免责说明）。
                   # 该标记只在 DEMO_MODE 生效；生产姿态下服务端会告警并忽略。
                   "mark_as_demo": True}, token=elderly_tok)
        if r.get("code") != 0:
            print(f"  [跳过] 提交失败：{r.get('message')}")
            continue
        d = r.get("data") or {}
        iid = d.get("issue_id")
        dup = "（幂等命中，已有单）" if d.get("duplicate") else ""
        print(f"  [建单] #{iid} 系统建议分类「{d.get('category')}」{dup}")
        made.append((iid, fix_to))

    # 人工修正：走受控入口（状态机 + 留痕），不是直接改库
    for iid, fix_to in made:
        if not fix_to:
            continue
        r = _post(f"/api/web/issues/{iid}/action",
                  {"action": "update_category", "category": fix_to}, token=grid_tok)
        if r.get("code") == 0:
            print(f"  [人工修正] #{iid} → 「{fix_to}」（走受控入口，已留痕）")
        else:
            print(f"  [人工修正未生效] #{iid} → 「{fix_to}」：{r.get('message')}")

    # 回读口径：覆盖率 / 一致率 / 被改过几条
    r = _get("/api/web/issues/category-corrections?days=180&limit=50", token=grid_tok)
    d = r.get("data") or {}
    print("\n" + "-" * 74)
    print(f"对照清单口径：近 {d.get('days')} 天共 {d.get('total')} 单 · "
          f"有系统建议 {d.get('with_suggestion')} 单 · 覆盖率 {d.get('coverage')}%")
    print(f"  一致 {d.get('agreed')} 单（{d.get('agreement_rate')}%） · "
          f"被人工改过 {d.get('corrected')} 单（{d.get('corrected_rate')}%）")
    if d.get("pairs"):
        print("  改动配对：" + "；".join(
            f"{p['suggested']} → {p['final']}（{p['count']}）" for p in d["pairs"]))
    if d.get("unlogged_changes"):
        print(f"  ⚠️ {d['unlogged_changes']} 条分类变了却没留痕（需排查）")
    if d.get("note"):
        print(f"  note：{d['note']}")
    print("\n提醒：以上是**演示数据**（通过真实链路提交），不是真实居民诉求，"
          "对外材料里不要当成用户量/准确率来引用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
