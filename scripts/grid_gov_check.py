# -*- coding: utf-8 -*-
"""治理侧两项 · 页面/接口/库内三处对账（v4 收敛方案第 5、7 阶段）。

  第 5 阶段：**治理情景模拟器**（诉求量涨 X% 要多少工时、折算几个人）
  第 7 阶段：**人工修正对照清单**（系统建议分类 vs 人工最终分类，含覆盖率）

为什么单写一个脚本而不是只留单测：单测只能证明"函数算得对"，
**证明不了"网格员真的看得见、算不出来的地方页面上真写了原因"**。
本项目踩过"带了防护 ≠ 防护生效"的坑，所以这一段一律用真浏览器点。

对账方式（三条都要）：
  ① 页面：`[data-gov-sim]` 存在，且五个数字块 + 注意事项 + 公式都渲染出来；
  ② 接口：`/agent/governance-simulation` 的返回与页面显示一致（样本量/预计新增/总量）；
  ③ 库内：样本量 == 库里本社区窗口期工单数（页面/接口/库三处同一个数）。

另外验"算不出来就说算不出来"：
  · 未配置人均可用工时 → 页面上出现「未配置，无法折算人手」，且折算人手显示 `—`（不是 0）。
对照清单那条额外验**覆盖率必须出现在页面上**（只报一致率就是口径造假）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8000"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [OK] " if ok else "  [FAIL] ") + name + (f"  —— {detail}" if detail else ""))


def _api(path, token=None, method="GET", body=None):
    import urllib.request
    req = urllib.request.Request(BASE + path, method=method,
                                data=json.dumps(body).encode() if body else None,
                                headers={"Content-Type": "application/json",
                                         **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"_err": str(e)}


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        page = br.new_page(viewport={"width": 1440, "height": 1000})
        # 网格员登录：**走表单**（网格员没有免密入口，这本身就是一条真实路径）
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        page.fill("input[placeholder='如 demo_grid']", "demo_grid")
        page.fill("input[placeholder='demo_grid / demo123']", "demo123")
        page.locator("button[type='submit']").first.click()
        page.wait_for_timeout(2500)
        check("① 网格员登录成功", "/login" not in page.url, page.url)
        page.goto(f"{BASE}/grid/dashboard", wait_until="domcontentloaded")
        page.wait_for_selector("[data-gov-sim]", timeout=25000)
        check("① 工作台有「治理情景模拟器」卡片", True)

        page.wait_for_timeout(1500)
        card = page.locator("[data-gov-sim]")
        txt = card.inner_text()
        check("① 卡片标了「情景估算」（不是预测）", "情景估算" in txt, txt[:60])
        check("① 公式可展开（四条公式在页面上）", "预计新增 = 样本量" in txt and "折算人手" in txt)

        shown = {
            "sample": page.locator("[data-sim-sample]").inner_text().strip(),
            "new": page.locator("[data-sim-new]").inner_text().strip(),
            "total": page.locator("[data-sim-total]").inner_text().strip(),
            "hours": page.locator("[data-sim-hours]").inner_text().strip(),
            "staffing": page.locator("[data-sim-staffing]").inner_text().strip(),
        }
        print("     页面数字：", shown)

        # ② 接口对账（同一口径：网格员 token）
        tok = page.evaluate("() => localStorage.getItem('ci_token') || ''")
        check("② 页面上确实拿到了登录态", bool(tok))
        api = _api("/api/web/agent/governance-simulation?days=30&growth_pct=20", token=tok)
        if api.get("_err"):
            check("② 接口可调（网格员）", False, api["_err"])
        else:
            d = api.get("data") or {}
            check("② 接口返回样本量/预计新增/总量", all(k in d for k in ("sample", "projected", "workload")),
                  json.dumps({k: d.get(k) for k in ("sample", "projected")}, ensure_ascii=False)[:120])
            check("② 页面样本量与接口一致",
                  str(d["sample"]["issues"]) == shown["sample"],
                  f"页面 {shown['sample']} / 接口 {d['sample']['issues']}")
            check("② 页面预计新增与接口一致",
                  shown["new"].lstrip("+") == str(d["projected"]["new"]),
                  f"页面 {shown['new']} / 接口 {d['projected']['new']}")
            # ③ 库内对账
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from data.db_core import get_db, init_db
            from config import DB_PATH
            init_db(DB_PATH)
            with get_db() as conn:
                n = conn.execute(
                    "SELECT COUNT(*) c FROM community_issues WHERE tenant_id=? "
                    "AND reported_at>=datetime('now','-30 days')", ("海淀小区",)).fetchone()["c"]
            check("③ 样本量 == 库里本社区近 30 天工单数", int(n) == d["sample"]["issues"],
                  f"库 {n} / 接口 {d['sample']['issues']}")

        # ④ 未配置人均可用工时 → 明确说明 + 不给人手数（而不是 0）
        if "—" in shown["staffing"]:
            check("④ 未配置时折算人手显示「—」（不是 0）", True)
            check("④ 页面上写清原因", "未配置" in txt and "无法折算人手" in txt,
                  [n for n in txt.split("\n") if "未配置" in n][:1])
        else:
            check("④ 已配置人均可用工时 → 给了折算人手", shown["staffing"].endswith("人"), shown["staffing"])

        # ⑤ 参数抽屉能开、能存（只对本社区生效）
        page.click("[data-sim-config]")
        page.wait_for_timeout(600)
        has_cfg = page.locator("[data-sim-cfg-hours]").count() > 0
        check("⑤ 参数抽屉可打开（人均可用工时 / 平均处理时长）", has_cfg)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # ⑥ 增长率改动会重算（点「计算」）
        page.fill("[data-sim-growth] input", "50")
        page.click("[data-sim-run]")
        page.wait_for_timeout(1800)
        new_after = page.locator("[data-sim-new]").inner_text().strip()
        check("⑥ 改增长率后重算（数字跟着变）", new_after != shown["new"] or shown["new"] == "+0",
              f"{shown['new']} → {new_after}")

        # ⑦ 配置 → 真的生效（"做了但不生效"是本项目最忌讳的）：
        #    填了人均可用工时 → 折算人手给出数字；清掉 → 又回到"未配置"提示。
        #    ⚠️ 最后**必须清干净**：演示口径要停在"未配置就明说"这条诚实路径上。
        from data.db_core import get_db, init_db
        from config import DB_PATH
        init_db(DB_PATH)
        hours_before = _api("/api/web/agent/governance-simulation?days=30&growth_pct=20",
                            token=tok)["data"]["workload"]["total_hours"]
        saved = _api("/api/web/agent/governance-simulation/settings", token=tok, method="POST",
                     body={"available_hours": 8})
        check("⑦ 参数保存成功（只对本社区生效）", saved.get("code") == 0, str(saved)[:120])
        after = _api("/api/web/agent/governance-simulation?days=30&growth_pct=20", token=tok)["data"]
        expect_staff = round(hours_before / 8, 2)
        check("⑦ 配了人均可用工时后**折算人手真的算出来了**",
              after["workload"]["staffing"] is not None
              and abs(after["workload"]["staffing"] - expect_staff) < 0.05,
              f"页/接口 {after['workload']['staffing']} · 期望 {expect_staff}（{hours_before}h ÷ 8h）")

        # 清干净（直接删设置行 + 清租户缓存），确认又回到"未配置"
        with get_db() as conn:
            conn.execute("DELETE FROM settings WHERE key LIKE '人均可用工时%'")
            conn.commit()
        from utils.tenant import clear_cache
        clear_cache()
        back = _api("/api/web/agent/governance-simulation?days=30&growth_pct=20", token=tok)["data"]
        check("⑦ 清掉配置后回到「未配置，无法折算人手」（演示口径复位）",
              back["workload"]["staffing"] is None
              and "无法折算人手" in back["workload"]["staffing_unavailable_reason"],
              back["workload"]["staffing_unavailable_reason"])

        # ---------------------------------------------------------------- 第 7 阶段：人工修正对照清单
        page.goto(f"{BASE}/grid/qa", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        # 清单在「知识图谱」标签页里（默认标签是「知识库」，要点一下才看得见）
        try:
            page.get_by_role("tab", name="知识图谱").click()
        except Exception:  # noqa: BLE001
            page.click("text=知识图谱")
        page.wait_for_selector("[data-cat-corrections]", timeout=20000)
        check("⑧ 「人工修正对照清单」卡片可见（知识图谱标签页内）", True)
        page.wait_for_timeout(1200)
        ctxt = page.locator("[data-cat-corrections]").inner_text()
        check("⑧ 页面上有「覆盖率」（只报一致率就是口径造假）",
              "覆盖率" in ctxt, ctxt[:80].replace("\n", " "))

        corr_api = _api("/api/web/issues/category-corrections?days=180&limit=50", token=tok)
        check("⑧ 接口可调（网格员）", not corr_api.get("_err"), str(corr_api)[:100])
        if not corr_api.get("_err"):
            d = corr_api.get("data") or {}
            shown_cov = page.locator("[data-corr-coverage]").inner_text().strip()
            shown_agree = page.locator("[data-corr-agreement]").inner_text().strip()
            shown_corr = page.locator("[data-corr-corrected]").inner_text().strip()
            # ⚠️ 比**数值**不比字符串：接口 `0.0` 经 JSON→JS 会显示成 `0`，
            # 直接和第 string 比会把"数字一致"误判成不一致（本轮实测踩到）。
            def _num(s):
                try:
                    return float(str(s).replace("%", "").strip())
                except ValueError:
                    return None

            def _close(a, b, tol=0.05):
                return a is not None and abs(a - float(b)) <= tol
            check("⑧ 页面覆盖率/一致率与接口一致",
                  _close(_num(shown_cov), d["coverage"])
                  and _close(_num(shown_agree), d["agreement_rate"])
                  and _close(_num(shown_corr), d["corrected"]),
                  f"页 {shown_cov}/{shown_agree}/{shown_corr} · 接口 {d['coverage']}%/{d['agreement_rate']}%/{d['corrected']}")
            check("⑧ 口径写明「不用于模型训练」",
                  "不用于模型训练" in ctxt or "不用于模型训练" in str(d.get("disclaimer")),
                  str(d.get("disclaimer"))[:80])
            check("⑧ 空清单有解释（不是一句冷冰冰的 0）",
                  d["with_suggestion"] > 0 or "预期" in (d.get("note") or ""), d.get("note", ""))
            # 有"被改过"的条目时：配对行与明细表都要真的渲染出来（不能只是数字好看）
            if d["corrected"] > 0:
                check("⑧ 有改动时页面上出现「常见改动」配对行",
                      page.locator("[data-corr-pairs]").count() > 0
                      and "→" in page.locator("[data-corr-pairs]").inner_text(),
                      page.locator("[data-corr-pairs]").inner_text().replace("\n", " ")[:90] if
                      page.locator("[data-corr-pairs]").count() else "元素不存在")
                rows = page.locator("[data-cat-corrections] tbody tr").count()
                check("⑧ 明细表行数与接口条目数一致（页面/接口对账）",
                      rows == len(d["items"]), f"页面 {rows} 行 · 接口 {len(d['items'])} 条")
                # 留痕异常必须为 0（我们是通过受控入口改的）
                check("⑧ 受控入口改的分类都能查到留痕（unlogged_changes=0）",
                      d["unlogged_changes"] == 0, str(d["unlogged_changes"]))

        br.close()

    print("\n" + "=" * 70)
    print(f"检查项：{len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    if FAIL:
        print("未通过：" + "；".join(FAIL))
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
