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
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from playwright.sync_api import sync_playwright  # noqa: E402

results: list[tuple[str, bool, str]] = []

# 关掉语音的注入脚本（**立即执行的语句块**，不要写成箭头函数字面量——那只是个表达式，不会被执行）
SPEECH_OFF_JS = """
(() => {
  const kill = ['SpeechRecognition', 'webkitSpeechRecognition', 'speechSynthesis'];
  for (const k of kill) {
    try { delete window[k] } catch (e) { /* 忽略 */ }
    try { Object.defineProperty(window, k, { value: undefined, configurable: true }) } catch (e) { /* 忽略 */ }
  }
})();
"""


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


def _fault_drills(page, base: str) -> None:
    """故障注入（卡12 的"故障集"）：**接口坏了的时候，页面有没有说实话**。

    为什么必须有这一组：本项目最忌讳"失败却显示成功"。前面所有诚实化改造
    （缺信息不建单、结果未知可查询、播报失败要说出来）都只在**正常路径**上被验过；
    这里把接口打断/打 500，直接看页面的反应。
    """
    print("\n【故障注入】接口失败时的页面行为（不许出现「假成功」）")

    # 故障注入针对**老人端**，所以先切到老年端会话（--faults 可能单独跑，此时仍是网格员登录态）
    clear_session(page, base)
    page.locator("text=老年").first.click()
    page.wait_for_url("**/elderly/**")

    # ① 报修提交接口超时 → 必须说"结果还不确定 + 可核对"，**不能**说"已上报"
    page.route("**/api/web/elderly/report/submit", lambda route: route.abort("timedout"))
    page.goto(f"{base}/elderly/report", wait_until="networkidle")
    page.wait_for_timeout(1800)
    page.fill("textarea", "五号楼二层楼道灯坏了")
    _btn(page, "帮我看看还缺什么").first.click()
    page.wait_for_timeout(2200)
    if _btn(page, "确认上报").count():
        _btn(page, "确认上报").first.click()
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    check("故障① 提交超时**不谎报成功**", "已上报" not in body and "工单号" not in body,
          "页面上没有「已上报/工单号」")
    check("故障① 给出「结果未知/核对」的出口",
          ("核对" in body) or ("查一下是否已经提交" in body) or ("网络" in body),
          "显示正在核对/网络没回话，而不是静默失败")
    page.unroute("**/api/web/elderly/report/submit")

    # ② 工单列表接口 500 → 必须给出错误提示，不能显示"没有数据"假装正常
    page.route("**/api/web/elderly/orders**",
               lambda route: route.fulfill(status=500, content_type="application/json",
                                           body='{"success":false,"error":"服务器开小差"}'))
    page.goto(f"{base}/elderly/orders", wait_until="networkidle")
    page.wait_for_timeout(2200)
    body2 = page.inner_text("body")
    check("故障② 列表接口 500 时有明确反馈",
          ("服务器开小差" in body2) or ("失败" in body2) or ("错误" in body2) or ("重试" in body2),
          "不能只显示空白/没有记录")
    page.unroute("**/api/web/elderly/orders**")

    # ③ 语音不可用（删掉 Web Speech）→ 必须明说"打字就行"（老年端降级路径）
    # ⚠️ 注入脚本必须写成**立即执行的语句块**：写成 `() => {...}` 字面量的话它只是个表达式，
    #    永远不会被调用，"删语音"根本没生效（`scripts/mobile_audit.py` 里已记录过这个坑）。
    page.context.add_init_script(SPEECH_OFF_JS)
    page.goto(f"{base}/elderly/report", wait_until="networkidle")
    page.wait_for_timeout(2200)
    body3 = page.inner_text("body")
    check("故障③ 关掉语音后页面显式降级（打字路径可用）",
          ("打字" in body3) or ("不支持语音" in body3) or ("念不出来" in body3), "降级提示条出现")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--mutate", action="store_true", help="真的推进一张工单到已解决")
    ap.add_argument("--faults", action="store_true",
                    help="额外做故障注入（接口超时/500/关掉语音），验「失败时不谎报成功」")
    ap.add_argument("--handoff", action="store_true",
                    help="额外走一遍「AI 转人工 → 人工待办 领取/回复/关闭」（会改数据）")
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
            if _has_btn(page, "审核通过"):
                _btn(page, "审核通过").first.click()
                page.wait_for_timeout(1800)
            check("① 审核通过", _has_btn(page, "派单") > 0,
                  "出现「🔧 派单」按钮 = 已进入已审核待派单")
            if page.locator("input[placeholder='维修人员姓名（必填）']").count():
                page.fill("input[placeholder='维修人员姓名（必填）']", "王师傅")
                page.fill("input[placeholder='电话（必填）']", "13800001234")
                _btn(page, "派单").first.click()
                page.wait_for_timeout(1500)
            check("② 派单（填维修人员与电话）", _has_btn(page, "开始处理") > 0,
                  "出现「🔨 开始处理」")
            if _has_btn(page, "开始处理"):
                _btn(page, "开始处理").first.click()
                page.wait_for_timeout(1500)
            check("③ 开始处理", _has_btn(page, "提交处理结果") > 0,
                  "出现「✅ 提交处理结果」")
            if page.locator("input[placeholder='处理结果（必填）']").count():
                page.fill("input[placeholder='处理结果（必填）']",
                          "已联系电梯维保单位，故障已排除，运行正常。")
                _btn(page, "提交处理结果").first.click()
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
            _btn(page, "帮我看看还缺什么").first.click()
            page.wait_for_timeout(2200)
            body_el = page.inner_text("body")
            check("⑥ 报修页给出结构化摘要", ("请您核对这几项" in body_el) or ("入" in body_el and "位置" in body_el))
            if _btn(page, "确认上报").count():
                _btn(page, "确认上报").first.click()
                # ⚠️ 别用固定 sleep 等结果：提交里有分类等耗时步骤（LLM 姿态全开时更慢），
                #    固定 2.5s 会**偶发**读到"还没有结果"而误报失败（实测踩到一次 25/26）。
                #    这里改成轮询等结果文案出现。
                deadline = time.time() + 20
                after = ""
                while time.time() < deadline:
                    page.wait_for_timeout(500)
                    after = page.inner_text("body")
                    if ("已上报" in after) or ("工单号" in after) or ("还差" in after) \
                            or ("手机号" in after) or ("没有提交成功" in after):
                        break
            else:
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
                  page.locator("button:has-text('紧急求助')").count() > 0)
            _btn(page, "更多服务").first.click()
            page.wait_for_timeout(1500)
            check("⑪ 「更多服务」页可打开并能进用药提醒",
                  "/elderly/more" in page.url, page.url)

        if args.handoff:
            # ---------- 场景 7：AI 转人工 → 网格端工作台办结（卡11 / v3 卡7） ----------
            # 走**真实链路**：居民对 AI 说"转人工" → 生成处理包 → 网格员在「人工待办」领取/回复/关闭。
            print("\n【场景 7】AI 转人工 → 网格端「人工待办」办结（领取 → 回复 → 关闭）")
            clear_session(page, base)
            page.locator("text=居民").first.click()
            page.wait_for_url("**/resident/**")
            page.goto(f"{base}/resident/home", wait_until="networkidle")
            page.wait_for_timeout(2000)
            # AgentChat 的输入是 n-input（渲染成 <input>，不是 textarea），回车或点「发送」都能提交
            box = page.locator("input[placeholder*='请输入您的问题']")
            if not box.count():
                box = page.locator("input[placeholder*='漏水']")
            if box.count():
                box.first.fill("我要转人工，请人工客服帮我查一下医保报销")
                _btn(page, "发送").first.click()
                page.wait_for_timeout(4000)
            else:
                check("⓪ 找到对话框输入框", False, "首页找不到 Agent 对话框输入框")
            res_text = page.inner_text("body")
            check("⓪ 居民要求转人工得到回应", ("人工" in res_text) or ("转接" in res_text),
                  "AI 走转人工链路")

            clear_session(page, base)
            page.locator("text=网格员").first.click()
            page.wait_for_url("**/grid/**")
            page.goto(f"{base}/grid/handoffs", wait_until="networkidle")
            page.wait_for_timeout(2500)
            check("① 打开「人工待办」工作台", "人工待办" in page.inner_text("body"), page.url)

            if _has_btn(page, "领取"):
                _btn(page, "领取").first.click()
                page.wait_for_timeout(2000)
                body_h = page.inner_text("body")
                # 判据要**看状态**，不能看"待处理还在不在"（列表里还有别人的待处理包）
                check("② 领取成功（记录谁领的）",
                      ("已领取" in body_h) and ("办理中" in body_h), "状态变为已领取")
                if page.locator("input[placeholder='回复内容（会通知居民）']").count():
                    page.fill("input[placeholder='回复内容（会通知居民）']",
                              "已帮您核实：带身份证与医保卡到社区服务站即可办理。")
                    _btn(page, "回复").first.click()
                    page.wait_for_timeout(2000)
                check("③ 回复居民成功", "已回复" in page.inner_text("body"),
                      "回复内容已记录并通知居民")
                if page.locator("input[placeholder='关闭说明（居民看得到的处理结果）']").count():
                    page.fill("input[placeholder='关闭说明（居民看得到的处理结果）']",
                              "已电话告知居民办理流程，居民确认理解。")
                    _btn(page, "关闭").first.click()
                    page.wait_for_timeout(2200)
                check("④ 关闭办结（带说明）", "已办结" in page.inner_text("body"),
                      "关闭说明会成为居民看到的处理结果")
            else:
                check("② 有可领取的待办包", False, "工作台里没有「待处理」的处理包")

        if args.faults:
            _fault_drills(page, base)

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
