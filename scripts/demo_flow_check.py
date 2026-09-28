# -*- coding: utf-8 -*-
"""桌面端真点击彩排（场景 3 提案详情 / 场景 4 网格员工单全流程）。

为什么单独有它：`mobile_flow_check.py` 验的是**手机端手指点击**；而现场主屏是桌面浏览器，
场景 3/4 要按**真实按钮**一步步点。之前只做了数据级与页面加载级验证，
"点了按钮会发生什么"没验过——实测发现工单真实路径是 **5 步**（展开→审核通过→派单(填两人)→
开始处理→提交处理结果），而演示脚本原来写的是 2 步（待处理→处理中→已解决），现场会找不到按钮。

用法：
    python scripts/demo_flow_check.py              # 只读彩排（提案详情 + 页面可达）
    python scripts/demo_flow_check.py --mutate     # 额外把最新一条待审核工单走到「已解决」
"""
import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from playwright.sync_api import sync_playwright  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""))


def clear_session(page, base: str) -> None:
    """清登录态再回登录页——否则路由守卫会直接放回已登录的首页，**点不到角色卡**。
    （第一版就是漏了这步，在"切到网格员"时超时失败。）"""
    try:
        page.context.clear_cookies()
        page.goto(f"{base}/login", wait_until="domcontentloaded")
        page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
        page.goto(f"{base}/login", wait_until="networkidle")
        page.wait_for_timeout(1300)
    except Exception as e:  # noqa: BLE001
        print(f"  （清会话告警：{str(e)[:60]}）")


def _btn(page, text: str, exact: bool = True):
    """按**精确可访问名**取按钮。

    为什么不用 `button:has-text('派单')`：它是子串匹配，会同时命中「🔧 批量派单」
    （批量派单的输入框是空的，点了会失败并误导彩排结论）。第一版就是栽在这上面。
    """
    return page.get_by_role("button", name=text, exact=exact)


def _has_btn(page, text: str) -> int:
    return _btn(page, text).count()


def _expand_first_row(page, status: str = "待审核") -> bool:
    """展开第一条指定状态的工单行 —— **操作按钮只在展开后渲染**（脚本原稿漏了这步）。"""
    if not page.locator(f"text={status}").count():
        return False
    # 同一张卡片里点「展开 ▼」
    row = page.locator(f"text={status}").first
    card = row.locator("xpath=ancestor::div[contains(@class,'card')][1]")
    op = card.locator("text=展开 ▼")
    if op.count():
        op.first.click()
        page.wait_for_timeout(1200)
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--mutate", action="store_true", help="真的推进一张工单到已解决")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("=" * 78)
    print(f"桌面端真点击彩排 · {base} · 1440x900" + ("　【会改数据】" if args.mutate else "　【只读】"))
    print("=" * 78)

    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.set_default_timeout(20000)

        # ---------- 场景 3：居民端提案 → 详情（看处理留痕） ----------
        print("\n【场景 3】居民端提案详情")
        page.goto(f"{base}/login", wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.locator("text=居民").first.click()
        page.wait_for_url("**/resident/**")
        page.goto(f"{base}/resident/proposals", wait_until="networkidle")
        page.wait_for_timeout(1800)
        check("提案页打开", page.locator("text=提案").count() > 0)
        # 点第一条提案标题进入详情（脚本里的动作："点开任一提案详情 → 看处理留痕"）
        # 真实 DOM：标题是 <b style="cursor: pointer;">（浏览器会把内联样式规范化成**带空格**的
        # `cursor: pointer;`，所以选择器不能写 `cursor:pointer` —— 第一版就是这么选不中的）
        first = page.locator("b[style*='cursor']").first
        if first.count():
            title = (first.inner_text() or "").strip()[:24]
            first.click()
            page.wait_for_timeout(1800)
            check("点标题能进详情", "/resident/proposals/" in page.url, f"「{title}」→ {page.url}")
            body = page.inner_text("body")
            check("详情页有处理留痕/时间线", ("留痕" in body) or ("时间线" in body) or ("流程" in body))
        else:
            check("提案可点标题", False, "页面没有可点的提案标题")

        # ---------- 场景 4：网格员工单全流程 ----------
        print("\n【场景 4】网格端工单管理（真实按钮路径）")
        clear_session(page, base)
        page.locator("text=网格员").first.click()
        page.wait_for_url("**/grid/**")
        check("网格员免密进入", "/grid" in page.url, page.url)
        page.goto(f"{base}/grid/work-orders", wait_until="networkidle")
        page.wait_for_timeout(2200)
        body = page.inner_text("body")
        check("工单管理页打开（含状态筛选）", "工单" in body)
        n_pending = page.locator("text=待审核").count()
        check("列表里能看到「待审核」工单", n_pending > 0, f"{n_pending} 处")

        if args.mutate:
            print("\n  —— 推进一张工单：**展开** → 审核通过 → 派单 → 开始处理 → 提交处理结果 ——")
            print("     ⚠️ 现场关键：操作按钮**藏在折叠行里**，必须先点这一行展开（脚本原稿漏了这步）")
            opened = _expand_first_row(page, "待审核")
            check("⓪ 点行展开工单（操作按钮才出现）", opened)
            if _has_btn(page, "✅ 审核通过"):
                _btn(page, "✅ 审核通过").first.click()
                page.wait_for_timeout(1800)
            check("① 审核通过", _has_btn(page, "🔧 派单") > 0,
                  "出现「🔧 派单」按钮 = 已进入已审核待派单")
            if page.locator("input[placeholder='维修人员姓名（必填）']").count():
                page.fill("input[placeholder='维修人员姓名（必填）']", "王师傅")
                page.fill("input[placeholder='电话（必填）']", "13800001234")
                _btn(page, "🔧 派单").first.click()
                page.wait_for_timeout(1500)
            check("② 派单（填维修人员与电话）", _has_btn(page, "🔨 开始处理") > 0,
                  "出现「🔨 开始处理」")
            if _has_btn(page, "🔨 开始处理"):
                _btn(page, "🔨 开始处理").first.click()
                page.wait_for_timeout(1500)
            check("③ 开始处理", _has_btn(page, "✅ 提交处理结果") > 0,
                  "出现「✅ 提交处理结果」")
            if page.locator("input[placeholder='处理结果（必填）']").count():
                page.fill("input[placeholder='处理结果（必填）']",
                          "已联系电梯维保单位，故障已排除，运行正常。")
                _btn(page, "✅ 提交处理结果").first.click()
                page.wait_for_timeout(2000)
            text = page.inner_text("body")
            check("④ 提交处理结果 → 状态变为「处理结束」", "处理结束" in text)

            # ---------- 场景 5：老人端「一句话报修」→「我的报修」看可理解进度 ----------
            # 这条同时验两件事：新版两步报修契约（缺什么问什么）与 §6-I9 的进度展示。
            print("\n【场景 5】老人端：一句话报修 → 我的报修（进度可理解）")
            # ⚠️ 必须先**换成老年端会话**：上一段是网格员登录态，直接跳 /elderly/** 会被路由守卫弹回去
            # （第一版就是这么超时在"找不到输入框"上的）
            clear_session(page, base)
            page.locator("text=老年").first.click()
            page.wait_for_url("**/elderly/**")
            page.goto(f"{base}/elderly/report", wait_until="networkidle")
            page.wait_for_timeout(2000)
            page.fill("textarea", "五号楼二层楼道灯坏了")
            _btn(page, "🔍 帮我看看还缺什么").first.click()
            page.wait_for_timeout(2200)
            body_el = page.inner_text("body")
            check("⑥ 报修页给出结构化摘要", ("请您核对这几项" in body_el) or ("入" in body_el and "位置" in body_el))
            if _btn(page, "✅ 确认上报").count():
                _btn(page, "✅ 确认上报").first.click()
                page.wait_for_timeout(2500)
            after = page.inner_text("body")
            ok_result = ("已上报" in after) or ("工单号" in after) or ("还差" in after) or ("手机号" in after)
            check("⑦ 确认后如实反馈结果（成功带工单号 / 缺信息则追问）", ok_result,
                  "不出现伪造的成功提示" if ok_result else
                  "没看到结果文案，页面尾部：" + after.replace("\n", " ")[-160:])

            page.goto(f"{base}/elderly/orders", wait_until="networkidle")
            page.wait_for_timeout(2200)
            el = page.inner_text("body")
            has_progress = ("社区规定" in el) or ("还没" in el) or ("已完成" in el)
            check("⑧ 老人端「我的报修」显示了可理解的进度", has_progress,
                  "能看到「现在到哪一步 / 下一步谁做 / 还要多久」" if has_progress
                  else "页面上没有进度文案")

            # ---------- 场景 6：老年端导航收敛（B4）与「更多服务」可达 ----------
            print("\n【场景 6】老人端导航与紧急求助入口")
            nav = page.locator(".elderly-nav button")
            check("⑨ 顶部导航 ≤ 6 个入口（B4 收敛）", nav.count() <= 6,
                  f"实际 {nav.count()} 个：{nav.all_inner_texts()}")
            check("⑩ 任意页面都有独立紧急求助入口",
                  page.locator("button:has-text('🆘 紧急求助')").count() > 0)
            _btn(page, "🧰 更多服务").first.click()
            page.wait_for_timeout(1500)
            check("⑪ 「更多服务」页可打开并能进用药提醒",
                  "/elderly/more" in page.url, page.url)

        b.close()

    passed = sum(1 for _n, ok, _d in results if ok)
    print("\n" + "=" * 78)
    print(f"结果：{passed}/{len(results)} 项通过")
    bad = [n for n, ok, _d in results if not ok]
    if bad:
        print("未通过：" + "、".join(bad))
    print("=" * 78)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
