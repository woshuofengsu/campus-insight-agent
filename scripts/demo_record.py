# scripts/demo_record.py — 答辩备用录屏：Playwright 逐场景录制真实动效 + 关键帧静帧
# -*- coding: utf-8 -*-
"""为什么需要它：现场设备可能带不动动效（低端投影笔记本 / 强制 reduced-motion），
录屏是答辩的兜底素材。全部用真实浏览器录制，不剪辑、不合成。

产物（默认 `.recordings/`）：
  <场景>.webm      真实录屏（VP8，Chrome/Edge/VLC/Windows「媒体播放器」可直接播）
  <场景>-NN.png    该场景的关键帧静帧（可直接拖进 PPT）
  index.md         场景清单 + 时长 + 文件大小（自动生成）

用法：
  python scripts/demo_record.py                 # 录制全部场景
  python scripts/demo_record.py --only login resident
  python scripts/demo_record.py --out D:\\答辩素材

注意：需要服务已在 :8000 运行（DEMO_MODE=true）；本脚本只读页面、只写视频/图片，
      唯一的写操作是网格端点开「满意度下钻」（只读接口）与老年端点「取消」，
      不会真正发出 SOS / 报修。
"""
import argparse
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLE_BTN = {"resident": "居民", "elderly": "老年", "grid": "网格员"}


# ---------------------------------------------------------------- 场景定义
def scene_login(ctx, page, still):
    """登录页：星光粒子 + 数字滚动 + 按钮流光 + 角色卡 → 进居民端。"""
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.wait_for_timeout(2800)          # 粒子上升 + CountUp 1600ms 走完
    still("01-登录-数字滚动")
    box = page.get_by_text("登 录", exact=False).first.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25)
        page.wait_for_timeout(1200)      # 按钮流光
        still("02-登录-按钮流光")
    card = page.get_by_text("居民", exact=True).first.bounding_box()
    if card:
        page.mouse.move(card["x"] + card["width"] / 2, card["y"] + card["height"] / 2, steps=25)
    page.wait_for_timeout(900)
    page.get_by_text("居民", exact=True).first.click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
    page.wait_for_timeout(1400)          # 路由过渡 + 首页入场
    page.wait_for_timeout(3000)          # 收尾停留（凑够 ~15s 素材时长）


def scene_resident(ctx, page, still):
    """居民端首页：渐变横幅 + 天气胶囊 + 6 个彩色磁贴依次悬停。"""
    _login(page, "resident")
    page.wait_for_timeout(2000)
    still("01-居民-首页")
    tiles = page.locator(".entry-tile")
    n = tiles.count()
    for i in range(n):
        try:
            b = tiles.nth(i).bounding_box()
        except Exception:  # noqa: BLE001
            continue
        if not b:
            continue
        page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=18)
        page.wait_for_timeout(420)       # 图标弹跳 + 卡片上浮
        if i == 2:
            still("02-居民-磁贴悬停")
    page.mouse.wheel(0, 420)
    page.wait_for_timeout(1200)
    still("03-居民-滚动")
    page.mouse.wheel(0, -420)
    page.wait_for_timeout(900)
    page.wait_for_timeout(2500)          # 收尾停留（凑够 ~15s）


def scene_grid(ctx, page, still):
    """网格员工作台：真实统计数字滚动 + 红黑榜悬停 + 满意度下钻抽屉。"""
    _login(page, "grid")
    page.wait_for_timeout(2600)          # 4 张统计卡 CountUp 900ms
    still("01-工作台-统计卡")
    page.mouse.wheel(0, 520)
    page.wait_for_timeout(1000)
    still("02-工作台-红黑榜")
    try:
        page.get_by_text("近期满意工单").first.click(timeout=5000)
        page.wait_for_timeout(2200)      # 下钻抽屉
        still("03-工作台-满意度下钻")
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
    except Exception:  # noqa: BLE001
        pass
    page.mouse.wheel(0, -520)
    page.wait_for_timeout(800)
    page.wait_for_timeout(3200)          # 收尾停留（凑够 ~15s）


def scene_elderly(ctx, page, still):
    """老年端首页：大字 + 暖色面板 + SOS 长按 3 秒（弹确认框后点「取消」，不产生真实求助）。"""
    _login(page, "elderly")
    page.wait_for_timeout(2400)
    still("01-老年-大字首页")
    page.mouse.wheel(0, 700)
    page.wait_for_timeout(1400)
    still("02-老年-大按钮")
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(1200)
    sos = page.locator(".sos-breathe").first.bounding_box()
    if sos:
        page.mouse.move(sos["x"] + sos["width"] / 2, sos["y"] + sos["height"] / 2, steps=20)
        page.mouse.down()
        page.wait_for_timeout(3400)      # 长按 3 秒触发确认框
        page.mouse.up()
        page.wait_for_timeout(1600)      # 倒计时数字
        still("03-老年-SOS长按确认")
        try:
            page.get_by_text("取消", exact=True).first.click(timeout=4000)
        except Exception:  # noqa: BLE001
            page.keyboard.press("Escape")
    page.wait_for_timeout(1000)


def scene_screen(ctx, page, still):
    """治理大屏：8 张卡数字差值滚动 + 背景呼吸 + 标题扫光。"""
    _login(page, "grid")
    page.goto(f"{BASE}/screen", wait_until="networkidle")
    page.wait_for_timeout(2600)          # CountUp 1500ms
    still("01-大屏-八卡")
    page.wait_for_timeout(2400)          # 呼吸光环 / 扫光 / 刷新点
    still("02-大屏-呼吸与扫光")
    page.wait_for_timeout(1800)          # 收尾（总长约 17s，作为开场素材）


def scene_chat(ctx, page, still):
    """居民端 AI 对话：真多智能体协作（报修意图 → 状态机追问）。"""
    _login(page, "resident")
    page.wait_for_timeout(1500)
    try:
        page.get_by_text("社区小助手", exact=False).first.click(timeout=5000)
        page.wait_for_timeout(1200)
        inp = page.locator("textarea, input[type=text]").last
        inp.click()
        inp.type("我家阳台水管漏水了，水都流到楼下了", delay=45)
        page.wait_for_timeout(600)
        still("01-对话-输入")
        page.keyboard.press("Enter")
        page.wait_for_timeout(4200)      # 规则链 + 双层防线
        still("02-对话-智能体回复")
    except Exception as e:  # noqa: BLE001
        print(f"      （对话场景降级：{type(e).__name__}）")
    page.wait_for_timeout(2600)          # 收尾停留（凑够 ~15s）


SCENES = [
    ("01-login", "登录页 · 粒子/数字滚动/流光", "1440x900", 14, scene_login),
    ("02-resident", "居民端 · 横幅/磁贴悬停", "390x844", 16, scene_resident),
    ("03-grid", "网格员端 · 真实统计/下钻", "1440x900", 15, scene_grid),
    ("04-elderly", "老年端 · 大字/SOS 长按", "390x844", 17, scene_elderly),
    ("05-screen", "治理大屏 · 八卡滚动/呼吸", "1920x1080", 15, scene_screen),
    ("06-agent-chat", "居民端 · 多智能体对话", "390x844", 15, scene_chat),
]


def _login(page, role):
    """从登录页用演示账号进入指定端（与人工演示路径一致）。"""
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.wait_for_timeout(700)
    page.get_by_text(ROLE_BTN[role], exact=True).first.click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
    page.wait_for_timeout(700)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, ".recordings"))
    ap.add_argument("--only", nargs="*", default=None, help="只录指定场景前缀，如 01-login")
    ap.add_argument("--stills", action="store_true", default=True, help="同时存关键帧静帧（默认开）")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    from playwright.sync_api import sync_playwright

    picked = [s for s in SCENES if not args.only or any(s[0].startswith(o) for o in args.only)]
    rows = []
    problems = []
    # 清掉上一轮遗留的 Playwright 原始录像（page@xxxx.webm）与 0 字节残片
    for fn in os.listdir(args.out):
        if fn.startswith("page@") and fn.endswith(".webm"):
            try:
                os.remove(os.path.join(args.out, fn))
            except OSError:
                pass
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for key, title, vps, secs, fn in picked:
            w, h = (int(x) for x in vps.split("x"))
            ctx = browser.new_context(
                viewport={"width": w, "height": h},
                record_video_dir=args.out,
                record_video_size={"width": w, "height": h},
            )
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e, box=errs: box.append(str(e)[:120]))
            shots = []

            def still(name, _page=page, _key=key, _shots=shots):
                # 循环变量必须用默认参数绑定（ruff B023：闭包晚绑定会在循环下一轮指到新对象）
                tag = name.split("-", 1)[0]
                path = os.path.join(args.out, f"{_key}-{tag}.png")
                try:
                    _page.screenshot(path=path)
                    _shots.append(os.path.basename(path))
                except Exception:  # noqa: BLE001
                    pass

            t0 = time.time()
            try:
                fn(ctx, page, still if args.stills else (lambda *_a: None))
                status = "ok"
            except Exception as e:  # noqa: BLE001
                status = f"err:{type(e).__name__}"
                problems.append(f"{key}: {type(e).__name__}: {e}")
            dur = time.time() - t0
            video = page.video
            ctx.close()                      # 关闭后才写出视频
            target = os.path.join(args.out, f"{key}.webm")
            try:
                video.save_as(target)
                # save_as 是「复制」：原始 page@<hash>.webm 会留在目录里，删掉它保持目录干净
                try:
                    os.remove(video.path())
                except OSError:
                    pass
            except Exception as e:  # noqa: BLE001
                problems.append(f"{key}: 保存视频失败 {e}")
                target = ""
            size = os.path.getsize(target) / 1024 if target and os.path.exists(target) else 0
            rows.append((key, title, vps, f"{dur:.1f}s", f"{size:.0f} KB", status, len(shots)))
            print(f"[rec] {key:14s} {dur:5.1f}s  {size:6.0f} KB  {status}  静帧 {len(shots)} 张")
            if errs:
                print(f"      ⚠ 页面 JS 报错：{errs[:2]}")
        browser.close()

    idx = os.path.join(args.out, "index.md")
    with open(idx, "w", encoding="utf-8") as f:
        f.write("# 答辩备用录屏清单（自动生成，勿手改）\n\n")
        f.write("| 场景 | 内容 | 分辨率 | 实际时长 | 文件大小 | 状态 | 静帧 |\n|---|---|---|---|---|---|---|\n")
        for k, t, v, d, s, st, nsh in rows:
            f.write(f"| `{k}.webm` | {t} | {v} | {d} | {s} | {st} | {nsh} |\n")
        f.write("\n> 说明：webm 用 Chrome/Edge/VLC/Windows「媒体播放器」可直接播放；"
                "转 mp4 见 `docs/competition/答辩录屏分镜.md`。\n")
    print(f"\n清单：{idx}")
    if problems:
        print("问题：")
        for x in problems:
            print("  -", x)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
