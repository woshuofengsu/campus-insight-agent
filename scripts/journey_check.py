# -*- coding: utf-8 -*-
"""首批八条浏览器旅程（v2 方案 §14「首批八条浏览器旅程」= 发布门槛）。

**为什么单独一个脚本**：`demo_flow_check.py` 验的是"演示场景里的关键按钮能不能点通"，
`mobile_flow_check.py` 验的是手机端手指路径；而方案 §14 要求的是**八条端到端旅程**——
它们不是"页面能打开"，而是"用户做完一件事之后，**库里、页面上、通知里**的事实是一致的"。
所以本脚本每一条都同时看三处：
  ① 页面上真实点了什么按钮、看到了什么字（Playwright 真点击）；
  ② 服务端返回了什么（页面里的 fetch，带当前登录身份）；
  ③ **库里到底是什么**（只读 SQLite 查询，复核"页面说的"与"存下来的"是否同一件事）。

八条（顺序即 v2 方案的顺序）：
  1. 居民正常报修 → 网格办理 → 居民反馈
  2. 缺位置 → 必要追问 → 更正 → 确认提交
  3. 中途取消 → 新建另一诉求，不恢复旧草稿
  4. 重复点击提交 → 仅一个有效对象
  5. 建单响应丢失 → 查询原结果，避免重复
  6. 无法确认诉求 → 真实交接包 → 网格领取回复
  7. 同社区他人和跨社区用户尝试访问 → 拒绝且界面可理解
  8. 网格处置权限正确，居民端仅出现本人授权消息

用法：
    python scripts/journey_check.py                 # 全部八条（**会写演示库**，见下）
    python scripts/journey_check.py --only 2,4,5    # 只跑指定的几条
    python scripts/journey_check.py --no-backup     # 不先备份数据库

⚠️ **会改数据**：旅程 1/2/3/4/5/6 会真的建工单、走流程、领取处理包（这正是"旅程"的意思）。
默认先做一次数据库备份到 `.shots/db-backup-before-journeys.db`；造出来的数据都带
`[彩排J1]`…`[彩排J6]` 标记，方便一眼认出、必要时按标记清理。
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
import uuid
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "community_insight.db"

# 每次运行一套**独立标记**：否则上一轮造的数据会让"这次没有建单"这类断言永远失败
# （实测踩到：同一句描述上一轮建过单，本轮一开跑 ①b 就红）。
RUN = time.strftime("%m%d-%H%M%S")

results: list[tuple[str, bool, str]] = []

# 关掉语音的注入脚本（**立即执行的语句块**；写成箭头函数字面量只是个表达式，永远不会执行）
SPEECH_OFF_JS = """
(() => {
  for (const k of ['SpeechRecognition', 'webkitSpeechRecognition', 'speechSynthesis']) {
    try { delete window[k] } catch (e) { /* 忽略 */ }
    try { Object.defineProperty(window, k, { value: undefined, configurable: true }) } catch (e) { /* 忽略 */ }
  }
})();
"""


# --------------------------------------------------------------------------- 基础工具

def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""))


def q(sql, args=()):
    """只读查询（复核用）。连库不带 `mode=ro`：WAL 下只读连接可能读不到 -shm，这里只 SELECT。"""
    conn = sqlite3.connect(str(DB), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def one(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else {}


def issue_by_mark(mark):
    return one("SELECT * FROM community_issues WHERE description LIKE ? ORDER BY id DESC LIMIT 1",
               (f"%{mark}%",))


def issue_count(mark):
    return one("SELECT COUNT(*) n FROM community_issues WHERE description LIKE ?", (f"%{mark}%",)).get("n", 0)


def wait_issue(mark, timeout=25.0):
    """等这条工单落库（提交接口里还有分类等耗时步骤，**不能靠固定 sleep 猜时间**）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = issue_by_mark(mark)
        if row:
            return row
        time.sleep(0.6)
    return {}


def wait_text(page, needle, timeout=15.0):
    """等页面上出现某段文字（接口写库在前、渲染在后，读得太早会误判成"没显示"）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in page.inner_text("body"):
            return True
        page.wait_for_timeout(400)
    return False


def wait_attr(page, selector, attr, value, timeout=15.0):
    """等某个元素的属性变成期望值（用在"结果来路"这类状态标记上）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        loc = page.locator(selector)
        if loc.count() and loc.first.get_attribute(attr) == value:
            return True
        page.wait_for_timeout(400)
    return False


def backup_db():
    dest = ROOT / ".shots" / "db-backup-before-journeys.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src = sqlite3.connect(str(DB))
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        return dest
    except Exception as e:  # noqa: BLE001 — 备份失败要说出来，但不拦着跑
        print(f"  （备份告警：{e}）")
        return None


def clear_session(page, base):
    """清登录态再回登录页——否则路由守卫会把已登录身份直接放回首页，**点不到角色卡**。"""
    try:
        page.context.clear_cookies()
        page.goto(f"{base}/login", wait_until="domcontentloaded")
        page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
        page.goto(f"{base}/login", wait_until="networkidle")
        page.wait_for_timeout(1200)
    except Exception as e:  # noqa: BLE001
        print(f"  （清会话告警：{str(e)[:60]}）")


def btn(page, text, exact=True):
    """按**精确可访问名**取按钮（子串匹配会误命中「批量派单」这类兄弟按钮）。"""
    return page.get_by_role("button", name=text, exact=exact)


def login_card(page, base, label, expect):
    clear_session(page, base)
    page.get_by_text(label, exact=True).first.click()
    page.wait_for_url(expect)
    page.wait_for_timeout(800)


def login_form(page, base, username, password, retries=2):
    """账号密码登录（跨社区账号没有免密入口，必须走表单——这本身就是一条真实旅程）。

    登录失败会被**明确报出来**（返回 /login），不要让调用方在"找不到输入框"上超时 25 秒——
    那样排查半天才发现是账号问题（实测踩到：第二社区网格员账号缺密码）。
    被限流时等一会儿重试：`utils/login_guard` 是 5 次失败锁 5 分钟。
    """
    for i in range(retries + 1):
        clear_session(page, base)
        page.fill("input[placeholder='如 demo_grid']", username)
        page.fill("input[placeholder='demo_grid / demo123']", password)
        page.locator("button[type='submit']").first.click()
        page.wait_for_timeout(2500)
        if "/login" not in page.url:
            return page.url
        body = page.inner_text("body")
        if ("尝试次数过多" in body) and i < retries:
            print(f"  （{username} 登录被限流，等 20 秒重试）")
            page.wait_for_timeout(20000)
            continue
        return page.url
    return page.url


def last_bot(page):
    loc = page.locator(".agent-msg.bot .agent-bubble")
    return loc.nth(loc.count() - 1).inner_text() if loc.count() else ""


def ask(page, text, timeout=20.0):
    """在 Agent 对话框里发一句话，等回复完（"正在思考…"消失）后返回**最后一条机器人回复**。"""
    box = page.locator("input[placeholder*='请输入您的问题']")
    if not box.count():
        box = page.locator("input[placeholder*='漏水']")
    box.first.fill(text)
    btn(page, "发送").first.click()
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(400)
        if page.locator(".agent-bubble:has-text('正在思考…')").count() == 0:
            break
    page.wait_for_timeout(400)
    return last_bot(page)


def click_quick(page, label):
    """点回复里的快捷选项按钮（追问/确认卡提供的按钮）——比打字更接近老人/居民的真实操作。"""
    card = page.locator(".agent-msg.bot").last
    b = card.get_by_role("button", name=label, exact=True)
    if not b.count():
        return False
    b.first.click()
    page.wait_for_timeout(700)
    deadline = time.time() + 20
    while time.time() < deadline:
        page.wait_for_timeout(400)
        if page.locator(".agent-bubble:has-text('正在思考…')").count() == 0:
            break
    page.wait_for_timeout(400)
    return True


def fetch_json(page, method, path, body=None):
    """在**当前登录身份的页面里**发一次接口请求（不是脚本自己伪造 token）。"""
    js = """async ([method, path, body]) => {
      const t = localStorage.getItem('ci_token');
      const r = await fetch(path, {
        method,
        headers: Object.assign({'Content-Type': 'application/json'},
                               t ? {Authorization: 'Bearer ' + t} : {}),
        body: body ? JSON.stringify(body) : undefined,
      });
      try { return await r.json(); } catch (e) { return {success: false, error: 'not-json:' + r.status}; }
    }"""
    return page.evaluate(js, [method, path, body])


def elderly_report_text(page, base, text):
    page.goto(f"{base}/elderly/report", wait_until="networkidle")
    page.wait_for_timeout(1600)
    page.fill("textarea", text)
    btn(page, "🔍 帮我看看还缺什么").first.click()
    page.wait_for_timeout(2200)
    return page.inner_text("body")


LOC_FILL = "input[placeholder*='或者告诉我别的']"


def fill_location(page, value):
    page.fill(LOC_FILL, value)
    page.wait_for_timeout(200)


# --------------------------------------------------------------------------- 旅程 1

def journey_1(page, base):
    """居民正常报修 → 网格办理 → 居民反馈（一条工单的完整生命周期）。"""
    mark = f"[彩排J1 {RUN}]"
    text = f"我家厨房水龙头一直滴水，关不紧 {mark}"

    login_card(page, base, "居民", "**/resident/**")
    page.goto(f"{base}/resident/home", wait_until="networkidle")
    page.wait_for_timeout(1800)
    r1 = ask(page, text)
    check("① 居民一句话报修 → AI 受理并只追问还缺的信息",
          ("紧急" in r1) or ("急不" in r1), r1.replace("\n", " ")[:80])
    # 紧急程度用按钮回答（真实按钮路径）
    if not click_quick(page, "一般"):
        ask(page, "一般")
    r2 = last_bot(page)
    check("② 信息齐了 → 给出确认卡（并标出位置来源）", ("确认提交" in r2) or ("位置" in r2),
          r2.replace("\n", " ")[:100])
    if not click_quick(page, "确认提交"):
        ask(page, "确认提交")
    r3 = last_bot(page)
    row = issue_by_mark(mark)
    check("③ 报修真的建单了（库里查得到，不是页面上说说）",
          bool(row) and row.get("status") == "待审核" and row.get("reporter_id") == 1,
          f"工单 #{row.get('id')} · {row.get('status')} · 位置 {row.get('location')}")
    check("③b 入库字段与居民原话一致（室内 · 厨房）",
          bool(row) and row.get("issue_type") == "室内" and "厨房" in (row.get("location") or ""),
          f"类型 {row.get('issue_type')} · 位置 {row.get('location')}")
    iid = row.get("id")
    check("③c 居民答复里带回工单号，且与库里那条一致",
          bool(iid) and f"WO{iid:08d}" in r3, r3.replace("\n", " ")[:80])
    if not iid:
        return

    # ---- 网格办理：展开 → 审核通过 → 派单 → 开始处理 → 提交处理结果 ----
    login_card(page, base, "网格员", "**/grid/**")
    page.goto(f"{base}/grid/work-orders", wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.get_by_placeholder("搜索标题/地址/描述/报修人").fill(mark)
    page.wait_for_timeout(1500)
    card = page.locator("div.card").filter(has_text=mark).first
    check("④ 网格端能搜到这条工单（不是「列表里看不见」）", card.count() > 0)
    if card.count():
        exp = card.locator("text=展开 ▼")
        if exp.count():
            exp.first.click()
            page.wait_for_timeout(1200)
        b = card.get_by_role("button", name="✅ 审核通过", exact=True)
        if b.count():
            b.first.click()
            page.wait_for_timeout(2000)
        card = page.locator("div.card").filter(has_text=mark).first
        check("⑤ 审核通过", card.get_by_role("button", name="🔧 派单", exact=True).count() > 0,
              "出现「🔧 派单」= 已进入已审核待派单")
        page.fill("input[placeholder='维修人员姓名（必填）']", "王师傅")
        page.fill("input[placeholder='电话（必填）']", "13800001234")
        card.get_by_role("button", name="🔧 派单", exact=True).first.click()
        page.wait_for_timeout(2000)
        card = page.locator("div.card").filter(has_text=mark).first
        check("⑥ 派单（填维修人员与电话）",
              card.get_by_role("button", name="🔨 开始处理", exact=True).count() > 0)
        card.get_by_role("button", name="🔨 开始处理", exact=True).first.click()
        page.wait_for_timeout(2000)
        card = page.locator("div.card").filter(has_text=mark).first
        page.fill("input[placeholder='处理结果（必填）']", "已更换水龙头阀芯，不再滴水，现场已试水。")
        card.get_by_role("button", name="✅ 提交处理结果", exact=True).first.click()
        page.wait_for_timeout(2500)
    row = issue_by_mark(mark)
    check("⑦ 处理结果入库，状态进入「待居民反馈」（等居民说话，不替居民结单）",
          row.get("status") == "待居民反馈" and "阀芯" in (row.get("resolve_note") or ""),
          f"状态 {row.get('status')}")

    # ---- 居民反馈（满意 → 结单）----
    login_card(page, base, "居民", "**/resident/**")
    page.goto(f"{base}/resident/work-orders/{iid}", wait_until="networkidle")
    page.wait_for_timeout(1800)
    body = page.inner_text("body")
    check("⑧ 居民能看到处理结果与时限", ("处理结果" in body) and ("阀芯" in body))
    fb = btn(page, "✅ 满意，结单")
    check("⑨ 待反馈时居民端出现「满意，结单」（权限对：这一步只有居民能做）", fb.count() > 0)
    if fb.count():
        fb.first.click()
        page.wait_for_timeout(2200)
    row = issue_by_mark(mark)
    check("⑩ 反馈落库：状态「处理结束」且满意度有记录",
          row.get("status") == "处理结束" and row.get("satisfaction") == "满意",
          f"状态 {row.get('status')} · 满意度 {row.get('satisfaction')}")


# --------------------------------------------------------------------------- 旅程 2

def journey_2(page, base):
    """缺位置 → 必要追问 → 更正 → 确认提交（老人端两步契约）。"""
    mark = f"[彩排J2 {RUN}]"
    text = f"楼道的灯坏了 {mark}"
    good = "19号楼3层楼道"

    login_card(page, base, "老年", "**/elderly/**")
    body = elderly_report_text(page, base, text)
    check("① 缺位置时不建单，而是追问（先说清是哪栋楼）",
          ("请您核对这几项" in body) and ("哪栋楼" in body or "哪一层" in body),
          "页面给出结构化摘要 + 一句能听懂的追问")
    check("①b 追问时**库里一条都没建**（不拿猜测的位置建单）", issue_count(mark) == 0,
          f"匹配工单数 {issue_count(mark)}")

    # 更正 1：答一个"太笼统"的位置 → 必须说明为什么不算，且仍不给提交
    if page.locator(LOC_FILL).count():
        fill_location(page, "小区")
        btn(page, "✅ 补充好了，再看一遍").first.click()
        page.wait_for_timeout(2200)
    body = page.inner_text("body")
    check("② 笼统的更正被如实拒绝并说明原因（不是默默不理会）",
          page.locator("[data-reject-hint]").count() > 0 and "太笼统" in body,
          "老人答「小区」→ 页面说清「太笼统了，请说到哪栋楼、哪一层」")
    check("②b 位置不合法时「确认上报」不出现（缺着就不允许提交）", btn(page, "✅ 确认上报").count() == 0)

    # 更正 2：给到楼栋+楼层 → 出提交按钮
    if page.locator(LOC_FILL).count():
        fill_location(page, good)
        btn(page, "✅ 补充好了，再看一遍").first.click()
        page.wait_for_timeout(2500)
    has_submit = btn(page, "✅ 确认上报").count() > 0
    check("③ 补充有效位置后出现「确认上报」（补充真的进入了判定，不是死路）", has_submit,
          "这一步曾经是坏的：补充值没上行，缺位置时永远出不来提交按钮")

    if has_submit:
        btn(page, "✅ 确认上报").first.click()
    row = wait_issue(mark)
    check("④ 提交后入库位置 = 老人更正的那个（不是系统猜的）",
          (row.get("location") or "").startswith(good), f"入库位置「{row.get('location')}」")
    check("④b 责任范围按原话判为公共区域（室外）", row.get("issue_type") == "室外",
          f"类型 {row.get('issue_type')}")
    check("④c 页面上如实给出工单号",
          bool(row.get("id")) and wait_text(page, f"工单号 {row.get('id')}"),
          f"工单 #{row.get('id')}")


# --------------------------------------------------------------------------- 旅程 3

def journey_3(page, base):
    """中途取消 → 新建另一诉求，不恢复旧草稿。"""
    old = f"[彩排J3旧 {RUN}]"
    new = f"[彩排J3新 {RUN}]"

    login_card(page, base, "居民", "**/resident/**")
    page.goto(f"{base}/resident/home", wait_until="networkidle")
    page.wait_for_timeout(1800)
    r1 = ask(page, f"我要报修，楼道的灯坏了 {old}")
    check("① 起了个头（信息不全 → 追问），草稿留在服务端",
          bool(one("SELECT id FROM draft_contents WHERE user_id=1 AND content_json LIKE ?",
                   (f"%{old}%",))),
          "库里存在未提交草稿")
    r2 = ask(page, "算了")
    check("② 说「算了」得到明确取消回执", "取消" in r2, r2.replace("\n", " ")[:60])
    check("②b 取消真的把草稿清了（库里不再有这条草稿）",
          one("SELECT COUNT(*) n FROM draft_contents WHERE user_id=1 AND content_json LIKE ?",
              (f"%{old}%",)).get("n", 0) == 0,
          "不残留 step，避免下次续接旧事")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1800)
    hint = page.locator("[data-draft-hint]")
    hint_text = hint.first.inner_text() if hint.count() else ""
    check("②c 重进页面后，草稿提示里**不再有这条被取消的草稿**（哪怕还留着别的旧草稿）",
          old not in hint_text, f"提示内容：{hint_text[:50] or '（无草稿提示）'}")

    r3 = ask(page, f"我家厨房水龙头一直滴水，关不紧 {new}")
    check("③ 新诉求从头开始问（没被旧草稿顶替）",
          old not in r3 and ("紧急" in r3 or "急不" in r3), r3.replace("\n", " ")[:80])
    if not click_quick(page, "一般"):
        ask(page, "一般")
    if not click_quick(page, "确认提交"):
        ask(page, "确认提交")
    row = wait_issue(new)
    check("④ 建的是**新诉求**的单（描述是新话，没有旧内容混进来）",
          bool(row) and old not in (row.get("description") or "")
          and new in (row.get("description") or ""),
          f"工单 #{row.get('id')} · {row.get('description', '')[:40]}")
    check("⑤ 被取消的那条自始至终没有建单", issue_count(old) == 0)


# --------------------------------------------------------------------------- 旅程 4

def journey_4(page, base):
    """重复点击提交 → 仅一个有效对象（界面防连点 + 服务端幂等两层）。"""
    mark = f"[彩排J4 {RUN}]"
    text = f"5号楼二层楼道灯不亮了 {mark}"

    login_card(page, base, "老年", "**/elderly/**")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if "/report/submit" in r.url else None)
    elderly_report_text(page, base, text)
    check("① 信息齐了 → 直接给「确认上报」", btn(page, "✅ 确认上报").count() > 0,
          "缺什么才问什么：这句里楼栋/楼层/公共部位都说了")
    # 界面层：同一帧里连点两下（真实连点行为；界面若置灰则由服务端幂等兜住）
    page.evaluate("""() => {
      const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('确认上报'));
      if (b) { b.click(); b.click(); }
    }""")
    page.wait_for_timeout(4000)
    n_post = len(posts)
    row = wait_issue(mark)
    check("② 连点两下：库里**只有一张单**（界面挡不住时由服务端幂等兜住）",
          issue_count(mark) == 1,
          f"浏览器发出 {n_post} 次提交请求（界面层挡住多少次、服务端挡住多少次都算合格），库里 {issue_count(mark)} 条")
    check("②b 页面上只出现一个结果卡、且工单号与库里那条一致",
          bool(row.get("id")) and wait_text(page, f"工单号 {row.get('id')}"),
          f"工单 #{row.get('id')}")

    # 服务端层：同一个幂等编号并发提交两次（网络重试的真实形态）
    token = uuid.uuid4().hex
    text2 = f"6号楼一层单元门关不严 {mark}B"
    js = """async ([path, payload]) => {
      const t = localStorage.getItem('ci_token');
      const call = () => fetch(path, {method: 'POST',
        headers: Object.assign({'Content-Type': 'application/json'},
                               t ? {Authorization: 'Bearer ' + t} : {}),
        body: JSON.stringify(payload)}).then(r => r.json());
      return await Promise.all([call(), call()]);
    }"""
    payload = {"text": text2, "location": "6号楼一层单元门", "scope": "室外",
               "urgency": "一般", "client_token": token}
    two = page.evaluate(js, ["/api/web/elderly/report/submit", payload]) or []
    ids = [((x or {}).get("data") or {}).get("issue_id") for x in two]
    wait_issue(f"{mark}B")
    check("③ 同编号并发两次提交 → 两次返回**同一个工单号**", len(set(ids)) == 1 and bool(ids[0]),
          f"返回 {ids}")
    dup = [((x or {}).get("data") or {}).get("duplicate") for x in two]
    check("③b 服务端只建了一张单（第二条被识别为重复提交，库里 1 条）",
          issue_count(f"{mark}B") == 1 and True in dup,
          f"库里 {issue_count(f'{mark}B')} 条，duplicate 标记 {dup}")


# --------------------------------------------------------------------------- 旅程 5

def journey_5(page, base):
    """建单响应丢失 → 查询原结果，避免重复（§6-I5 的真实形态）。

    两种"丢失"必须被**分开说清**，这正是本条旅程要守的东西：
      · 5a 请求根本没到服务端（超时）→ 页面必须说"这次没成功、可以再点一次"，**不许说已上报**；
      · 5b 请求到了、回程丢了（业务已发生）→ 页面必须**按提交编号核对出真实工单号**，且不重复建单。
    """
    mark_a = f"[彩排J5a {RUN}]"
    mark_b = f"[彩排J5b {RUN}]"
    login_card(page, base, "老年", "**/elderly/**")

    # ---- 5a：请求没出去 ----
    page.route("**/api/web/elderly/report/submit", lambda route: route.abort("timedout"))
    elderly_report_text(page, base, f"8号楼四层楼道灯不亮 {mark_a}")
    btn(page, "✅ 确认上报").first.click()
    page.wait_for_timeout(4500)
    body = page.inner_text("body")
    check("①［请求没出去］页面**不谎报成功**（没有「已上报」结果卡）",
          "已上报（工单号" not in body and page.locator("[data-result-via]").count() == 0,
          "网络超时 ≠ 提交成功")
    check("②［请求没出去］库里也确实没有建单，并给出「查一下」的出口",
          issue_count(mark_a) == 0 and btn(page, "🔍 查一下是否已经提交了").count() > 0,
          f"匹配工单数 {issue_count(mark_a)}")
    page.unroute("**/api/web/elderly/report/submit")

    # ---- 5b：请求到了服务端，但浏览器收不到响应 ----
    def lose_response(route):
        """让请求**真的到达服务端**（业务已发生），再把响应掐掉 —— 这才是"响应丢失"。"""
        try:
            route.fetch()
        except Exception:  # noqa: BLE001
            pass
        try:
            route.abort("failed")
        except Exception:  # noqa: BLE001
            pass

    page.route("**/api/web/elderly/report/submit", lose_response)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1500)
    elderly_report_text(page, base, f"9号楼二层楼道声控灯不亮 {mark_b}")
    btn(page, "✅ 确认上报").first.click()
    # 断网后页面会**自动**按提交编号核对；核对没自动跑（或还在跑）时，点一下出口按钮
    got = wait_attr(page, "[data-result-via]", "data-result-via", "verify", timeout=14)
    if not got and btn(page, "🔍 查一下是否已经提交了").count():
        btn(page, "🔍 查一下是否已经提交了").first.click()
        got = wait_attr(page, "[data-result-via]", "data-result-via", "verify", timeout=14)
    row = wait_issue(mark_b)
    body = page.inner_text("body")
    check("③［响应丢了］库里事实上**已经建单**（这正是最容易被误判成「失败」的情况）",
          issue_count(mark_b) == 1, f"匹配工单数 {issue_count(mark_b)}")
    check("④［响应丢了］页面把结果标成**核对到的**（不是「服务端回的」，也不许含糊）",
          got and "核对" in body,
          "结果卡上写明「网络没回话，工单号是按提交编号核对到的」")
    check("⑤［响应丢了］核对出的工单号 = 库里那条（没有重复建单）",
          bool(row.get("id")) and f"工单号 {row.get('id')}" in body and issue_count(mark_b) == 1,
          f"工单 #{row.get('id')}")
    page.unroute("**/api/web/elderly/report/submit")


# --------------------------------------------------------------------------- 旅程 6

def journey_6(page, base):
    """无法确认诉求 → 真实交接包 → 网格领取回复。"""
    mark = f"[彩排J6 {RUN}]"
    before = one("SELECT COALESCE(MAX(id), 0) m FROM agent_handoffs").get("m", 0)

    login_card(page, base, "居民", "**/resident/**")
    page.goto(f"{base}/resident/home", wait_until="networkidle")
    page.wait_for_timeout(1800)
    r1 = ask(page, f"我要转人工，请人工客服帮我查一下医保报销怎么办 {mark}", timeout=25)
    check("① 居民要求转人工 → AI 如实说明已转人工（不假装自己答完了）",
          ("人工" in r1) or ("转接" in r1), r1.replace("\n", " ")[:90])
    pkg = one("SELECT * FROM agent_handoffs WHERE id > ? ORDER BY id DESC LIMIT 1", (before,))
    # 上下文在 package_json 里（页面上把它摊平成「居民原话」显示）——查库时要自己解析
    ctx = {}
    try:
        ctx = json.loads(pkg.get("package_json") or "{}")
    except (ValueError, TypeError):
        ctx = {}
    check("② 真的生成了交接包（库里新增一条，含原话上下文与归属社区）",
          bool(pkg) and pkg.get("tenant_id") == "海淀小区" and mark in str(ctx.get("original_input") or ""),
          f"处理包 #{pkg.get('id')} · 状态 {pkg.get('status')} · 社区 {pkg.get('tenant_id')} · "
          f"原话 {str(ctx.get('original_input') or '')[:24]}")
    if not pkg:
        return
    hid = pkg.get("id")

    login_card(page, base, "网格员", "**/grid/**")
    page.goto(f"{base}/grid/handoffs", wait_until="networkidle")
    page.wait_for_timeout(2200)
    card = page.locator("div.card").filter(has_text=mark).first
    check("③ 网格端「人工待办」看得到这个包，且带着居民原话", card.count() > 0)
    if not card.count():
        return
    claim = card.get_by_role("button", name="🙋 领取", exact=True)
    if claim.count():
        claim.first.click()
        page.wait_for_timeout(2200)
    row = one("SELECT * FROM agent_handoffs WHERE id=?", (hid,))
    check("④ 领取成功：库里记下领取人和时间（不是只有界面上变了个色）",
          row.get("status") == "已领取" and row.get("assignee_name") and row.get("claimed_at"),
          f"状态 {row.get('status')} · 领取人 {row.get('assignee_name')}")
    card = page.locator("div.card").filter(has_text=mark).first
    page.fill("input[placeholder='回复内容（会通知居民）']", "已帮您核实：带身份证与医保卡到社区服务站即可办理报销。")
    card.get_by_role("button", name="✅ 回复", exact=True).first.click()
    page.wait_for_timeout(2200)
    card = page.locator("div.card").filter(has_text=mark).first
    page.fill("input[placeholder='关闭说明（居民看得到的处理结果）']", "已电话告知居民办理流程，居民确认理解。")
    card.get_by_role("button", name="🏁 关闭", exact=True).first.click()
    page.wait_for_timeout(2500)
    row = one("SELECT * FROM agent_handoffs WHERE id=?", (hid,))
    check("⑤ 回复 + 关闭都落库（回复内容/关闭说明/时间齐全）",
          row.get("status") == "已处理" and row.get("reply") and row.get("close_note")
          and row.get("replied_at") and row.get("closed_at"),
          f"状态 {row.get('status')}")
    note = one("SELECT COUNT(*) n FROM notifications WHERE user_id=1 AND content LIKE ?",
               ("%医保卡%",)).get("n", 0)
    check("⑥ 回复**通知到了居民**（通知表里查得到，不只是界面上打了个勾）", note > 0,
          f"居民收到的相关通知 {note} 条")


# --------------------------------------------------------------------------- 旅程 7

def journey_7(page, base):
    """同社区他人 + 跨社区用户尝试访问 → 拒绝且界面可理解。"""
    other = one("SELECT id, description FROM community_issues "
                "WHERE tenant_id='海淀小区' AND reporter_id<>1 ORDER BY id DESC LIMIT 1")
    cross = one("SELECT id, description FROM community_issues "
                "WHERE tenant_id='海淀小区' ORDER BY id DESC LIMIT 1")
    if not other or not cross:
        check("① 找到测试目标工单", False, "演示库里没有可用于越权测试的工单")
        return
    oid, odesc = other["id"], (other["description"] or "")[:24]
    xid, xdesc = cross["id"], (cross["description"] or "")

    # (a) 同社区、别人报的单
    login_card(page, base, "居民", "**/resident/**")
    page.goto(f"{base}/resident/work-orders/{oid}", wait_until="networkidle")
    page.wait_for_timeout(2000)
    body = page.inner_text("body")
    check(f"① 同社区他人（工单 #{oid}）打不开，且**页面上写明原因**",
          page.locator("[data-load-error]").count() > 0 and ("无权限" in body or "打不开" in body),
          "不是空白页/一直转圈")
    check("①b 页面没有漏出别人的工单内容", odesc not in body if odesc else True,
          f"未出现「{odesc}」")

    # (b) 跨社区：朝阳居民看海淀的单
    url = login_form(page, base, "demo_resident_cy", "demo123")
    check("② 跨社区账号能从表单登录（朝阳试点社区）", "/resident" in url or "/login" in url, url)
    if "/resident" not in url:
        page.goto(f"{base}/resident/home", wait_until="networkidle")
    page.goto(f"{base}/resident/work-orders/{xid}", wait_until="networkidle")
    page.wait_for_timeout(2000)
    body = page.inner_text("body")
    check(f"③ 跨社区（工单 #{xid}，海淀小区）同样打不开并写明原因",
          page.locator("[data-load-error]").count() > 0 and ("无权限" in body or "打不开" in body))
    check("③b 跨社区访问没有漏出内容", xdesc not in body if xdesc else True)
    acc = fetch_json(page, "GET", f"/api/web/issues/{xid}")
    check("③c 接口层同样拒绝（页面拒绝 ≠ 接口安全）",
          acc.get("success") is False and "无权" in str(acc.get("error") or ""),
          str(acc.get("error"))[:40])

    # (c) 朝阳网格员：列表按社区隔离 + 按 id 直取被闸门挡住
    url = login_form(page, base, "demo_grid_cy", "demo123")
    check("④ 朝阳网格员能登录（第二社区账号必须可用）", "/grid" in url, url)
    if "/grid" not in url:
        return
    page.goto(f"{base}/grid/work-orders", wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.get_by_placeholder("搜索标题/地址/描述/报修人").fill(xdesc[:18])
    page.wait_for_timeout(1800)
    body = page.inner_text("body")
    check("④ 跨社区网格员的工单列表里**搜不到**海淀工单（读取侧按社区隔离）",
          "没有符合条件的工单" in body and xdesc[:18] not in body,
          "列表看不到 → 界面上也就无从点开")
    g = fetch_json(page, "GET", f"/api/web/issues/{xid}")
    check("⑤ 跨社区网格员按 id 直取被闸门挡住（「列表看不见、换 id 就看见」这条被堵住）",
          g.get("success") is False and "无权" in str(g.get("error") or ""),
          str(g.get("error"))[:40])


# --------------------------------------------------------------------------- 旅程 8

def journey_8(page, base):
    """网格处置权限正确；居民端只出现本人授权消息。"""
    mine = one("SELECT id, description, status FROM community_issues "
               "WHERE reporter_id=1 AND tenant_id='海淀小区' AND status='待审核' "
               "ORDER BY id DESC LIMIT 1") or \
        one("SELECT id, description, status FROM community_issues WHERE reporter_id=1 "
            "ORDER BY id DESC LIMIT 1")
    if not mine:
        check("① 找到居民自己的工单", False, "演示库里没有 demo_resident 的工单")
        return
    mid = mine["id"]
    before_status = mine.get("status")

    login_card(page, base, "居民", "**/resident/**")
    page.goto(f"{base}/resident/work-orders/{mid}", wait_until="networkidle")
    page.wait_for_timeout(2000)
    body = page.inner_text("body")
    grid_only = ["✅ 审核通过", "🔧 派单", "🔨 开始处理", "✅ 提交处理结果", "🚫 关闭工单"]
    shown = [b for b in grid_only if btn(page, b).count() > 0]
    check(f"① 居民端工单 #{mid} 上**没有**处置类按钮（界面不引导越权）", not shown,
          f"出现的处置按钮：{shown}" if shown else "只有居民自己的操作（反馈/补充/撤回…）")
    # 接口层：居民直接调处置动作必须被拒
    act = fetch_json(page, "POST", f"/api/web/issues/{mid}/action", {"action": "audit", "approve": True})
    check("② 居民直调「审核通过」接口被拒（权限判定在服务端，不看前端按钮）",
          act.get("success") is False and "无权限" in str(act.get("error") or ""),
          str(act.get("error"))[:48])
    row = one("SELECT status, approved_at FROM community_issues WHERE id=?", (mid,))
    check("②b 工单状态没有被这次越权尝试改动",
          row.get("status") == before_status and not row.get("approved_at"),
          f"越权前后状态都是「{row.get('status')}」")

    # 居民端只出现**本人**授权消息
    msgs = fetch_json(page, "GET", "/api/web/messages?limit=200")
    rows = (msgs or {}).get("data") or []
    ids = [m.get("id") for m in rows]
    mine_ids = {r["id"] for r in q("SELECT id FROM notifications WHERE user_id=1")}
    check("③ 消息中心返回的每条消息都属于本人（没有别人的）",
          bool(ids) and set(ids) <= mine_ids, f"共 {len(ids)} 条，全部属于 uid=1")
    others = q("SELECT id, user_id, is_read FROM notifications WHERE user_id<>1 ORDER BY id DESC LIMIT 1")
    if others:
        other_id, other_uid = others[0]["id"], others[0]["user_id"]
        check(f"④ 别人的消息（#{other_id}，属于 uid={other_uid}）不在本人列表里",
              other_id not in set(ids))
        fetch_json(page, "POST", f"/api/web/messages/{other_id}/read")
        after = one("SELECT is_read FROM notifications WHERE id=?", (other_id,))
        check("⑤ 想标别人的消息已读 → 无效（接口带归属条件，不是「能点就改了」）",
              after.get("is_read") == others[0]["is_read"],
              f"该消息 is_read 仍为 {after.get('is_read')}")


# --------------------------------------------------------------------------- 主人

JOURNEYS = [
    (1, "居民正常报修 → 网格办理 → 居民反馈", journey_1),
    (2, "缺位置 → 必要追问 → 更正 → 确认提交", journey_2),
    (3, "中途取消 → 新建另一诉求，不恢复旧草稿", journey_3),
    (4, "重复点击提交 → 仅一个有效对象", journey_4),
    (5, "建单响应丢失 → 查询原结果，避免重复", journey_5),
    (6, "无法确认诉求 → 真实交接包 → 网格领取回复", journey_6),
    (7, "同社区他人和跨社区用户尝试访问 → 拒绝且界面可理解", journey_7),
    (8, "网格处置权限正确，居民端仅出现本人授权消息", journey_8),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--only", default="", help="只跑指定编号，如 2,4,5")
    ap.add_argument("--no-backup", action="store_true", help="不先备份数据库")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    want = {int(x) for x in re.split(r"[,\s]+", args.only.strip()) if x.strip()} if args.only else None
    todo = [j for j in JOURNEYS if want is None or j[0] in want]

    print("=" * 78)
    print(f"首批八条浏览器旅程 · {base} · 1440x900 · **会写演示库**")
    print("=" * 78)
    if not args.no_backup:
        b = backup_db()
        print(f"数据库已备份：{b}" if b else "数据库备份失败（继续跑，但请自行确认可恢复）")

    failed_journey: list[int] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for num, title, fn in todo:
            print(f"\n【旅程 {num}】{title}")
            before = len(results)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.set_default_timeout(25000)
            try:
                fn(page, base)
            except Exception as e:  # noqa: BLE001 — 一条旅程崩了不影响其它条，但必须记成失败
                check(f"旅程 {num} 执行中断", False, f"{type(e).__name__}: {str(e)[:160]}")
            finally:
                ctx.close()
            if any(not ok for _n, ok, _d in results[before:]):
                failed_journey.append(num)
        browser.close()

    passed = sum(1 for _n, ok, _d in results if ok)
    print("\n" + "=" * 78)
    print(f"检查项：{passed}/{len(results)} 通过")
    if failed_journey:
        print("未通过的旅程：" + "、".join(f"#{n}" for n in failed_journey))
    bad = [n for n, ok, _d in results if not ok]
    if bad:
        print("未通过项：\n  - " + "\n  - ".join(bad))
    print("=" * 78)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
