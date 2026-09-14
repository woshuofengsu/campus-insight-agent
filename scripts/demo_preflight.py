# scripts/demo_preflight.py — 答辩/演示前自检（U5）
# -*- coding: utf-8 -*-
"""演示前 10 分钟一键自检：7 项串行检查，任一失败给出**明确修复指令**。

用法：
  python scripts/demo_preflight.py              # 全量检查（含跑测试与构建，约 4 分钟）
  python scripts/demo_preflight.py --fast       # 跳过测试与构建（约 10 秒，现场快速体检）
  python scripts/demo_preflight.py --json       # 机器可读输出

检查项：
  1. 单元测试全绿（pytest，--fast 跳过）
  2. 代码规范（ruff check = 0，--fast 跳过）
  3. 前端产物存在且新于源码（web/dist/index.html vs web/src 最新 mtime）
  4. 数据库 schema 版本与代码一致（schema_version vs db_core 迁移表最大版本）
  5. .env 关键配置姿态（有无 LLM/向量 key → 决定走哪套演示姿态）
  6. 服务端口可达（8000 健康检查；未启动则给出启动命令）
  7. 三个演示账号可登录（居民/老年/网格员）
  8. 手机号加密覆盖度（所有 phone 列都有 *_enc 且明文计数为 0）
  9. 登录页品牌指标一致性（web/src/config/meta.js vs 实测；防「登录页数字 vs 大屏实时值」打架）
退出码：0 = 全部通过；1 = 有失败项（按输出提示修复即可）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8000"


def _run(cmd: list[str], timeout: int = 400) -> tuple[int, str]:
    """跑子进程并返回 (退出码, 输出尾部)。"""
    try:
        p = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip().splitlines()[-1] if out.strip() else ""
    except Exception as e:  # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


def _http(path: str, timeout: int = 6) -> tuple[int, dict | None]:
    """GET；把 HTTPError 的状态码原样返回（401 等是预期结果，不能当成异常）。"""
    import urllib.error
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def _post(path: str, body: dict, token: str = "") -> tuple[int, dict | None]:
    import urllib.error
    try:
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode(),
                                     headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def check_tests(fast: bool) -> dict:
    if fast:
        return {"name": "单元测试", "passed": True, "detail": "已跳过（--fast）", "fix": ""}
    code, tail = _run([sys.executable, "-m", "pytest", "-q"])
    ok = code == 0
    return {"name": "单元测试全绿", "passed": ok, "detail": tail if not ok else tail,
            "fix": "" if ok else "先修失败用例：python -m pytest -q"}


# ---------------- 登录页品牌指标 vs 后端实测（外部评审 P2） ----------------
META_JS = os.path.join(BASE, "web", "src", "config", "meta.js")
RAG_GOLDEN = os.path.join(BASE, "tests", "llm_eval", "rag_golden.jsonl")

_META_RE = re.compile(r"key:\s*'([a-z_0-9]+)',\s*value:\s*(\d+)")


def parse_brand_metrics(path: str | None = None) -> dict[str, int]:
    """从 web/src/config/meta.js 解析 {key: value}（登录页数字的唯一来源）。"""
    with open(path or META_JS, encoding="utf-8") as f:
        return {k: int(v) for k, v in _META_RE.findall(f.read())}


def count_rag_golden(path: str | None = None) -> int:
    """golden 集条数：与 scripts/rag_eval.load_golden 同口径（跳过 # 注释行与空行）。

    注意别用「文件行数」——文件里有 9 行注释，原样计数会得出 51 而误判不一致。
    """
    with open(path or RAG_GOLDEN, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip() and not line.lstrip().startswith("#"))


def check_phone_encryption() -> dict:
    """手机号加密覆盖度（第七轮复审 P2-A 沉淀成的门禁）。

    体检所有含 phone 的表：必须「有 *_enc 兄弟列」且「明文列计数为 0」。
    这条把「敏感数据全加密」从口号变成可断言的事实——提案表曾漏掉加密（生产库 181 条明文）。
    """
    try:
        from scripts.audit_phone_encryption import scan_gaps
    except Exception as e:  # noqa: BLE001
        return {"name": "手机号加密覆盖", "passed": False, "detail": f"无法导入体检脚本：{e}",
                "fix": "确认 scripts/audit_phone_encryption.py 存在"}
    db = os.path.join(BASE, "data", "community_insight.db")
    try:
        gaps, lines = scan_gaps(db)
    except Exception as e:  # noqa: BLE001
        return {"name": "手机号加密覆盖", "passed": False, "detail": f"体检失败：{e}",
                "fix": "检查数据库文件是否存在/可读"}
    if gaps:
        return {"name": "手机号加密覆盖", "passed": False, "detail": "；".join(gaps[:4]),
                "fix": "跑 data/db_core 的 v46 迁移（python -c \"from config import DB_PATH;"
                       "from data.db_core import init_db; init_db(DB_PATH)\"），"
                       "或检查新表是否漏建 *_enc 列"}
    return {"name": "手机号加密覆盖", "passed": True,
            "detail": f"{len(lines)} 张含手机号表：全部有加密列且明文计数为 0", "fix": ""}


def check_brand_metrics(fast: bool) -> dict:
    """登录页展示的数字必须能被后端/仓库实测复算（防止「登录页 62% vs 大屏 90.9%」式打架）。"""
    try:
        declared = parse_brand_metrics()
    except Exception as e:  # noqa: BLE001
        return {"name": "登录页指标一致性", "passed": False, "detail": f"读取 meta.js 失败：{e}",
                "fix": "确认 web/src/config/meta.js 存在且键值格式为 key: 'x', value: N"}

    actual: dict[str, int] = {}
    try:
        actual["rag_golden"] = count_rag_golden()
    except Exception as e:  # noqa: BLE001
        actual["rag_golden"] = -1
        _ = e
    try:
        from agent.roles import AGENT_CLASSES
        actual["agents"] = len(AGENT_CLASSES)
    except Exception:  # noqa: BLE001
        actual["agents"] = -1

    bad = []
    for key, want in declared.items():
        if key in actual and actual[key] != want:
            bad.append(f"{key}: 登录页 {want} ≠ 实测 {actual[key]}")

    # 全量模式顺带核对用例数（--collect-only 很快，2~3 秒）
    tests_collected = None
    if not fast and "tests" in declared:
        code, tail = _run([sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"], timeout=300)
        m = re.search(r"(\d+)/\d+ tests collected", tail) or re.search(r"(\d+) tests collected", tail)
        if code == 0 and m:
            tests_collected = int(m.group(1))
            if tests_collected != declared["tests"]:
                bad.append(f"tests: 登录页 {declared['tests']} ≠ pytest 收集 {tests_collected}")

    detail = f"meta.js 声明 {len(declared)} 项；已核对 " + \
             "、".join(f"{k}={v}" for k, v in actual.items() if v >= 0)
    if tests_collected is not None:
        detail += f"、tests={tests_collected}"
    if fast:
        detail += "（--fast：用例数未核对）"
    if bad:
        return {"name": "登录页指标一致性", "passed": False, "detail": "；".join(bad),
                "fix": "改 web/src/config/meta.js 的 value 使其等于实测值（或改后端口径），"
                       "不要在两处各写一个数；用例数变了直接跑 "
                       "`python scripts/sync_test_count.py`（自动同步 meta.js 与各文档）"}
    return {"name": "登录页指标一致性", "passed": True,
            "detail": detail + "；rag_hit1 由 CI 的 rag_eval 门禁核对", "fix": ""}


def check_ruff(fast: bool) -> dict:
    if fast:
        return {"name": "代码规范", "passed": True, "detail": "已跳过（--fast）", "fix": ""}
    code, tail = _run([sys.executable, "-m", "ruff", "check", "."])
    ok = code == 0
    return {"name": "代码规范 ruff=0", "passed": ok, "detail": tail,
            "fix": "" if ok else "python -m ruff check . --fix（或手工修）"}


def check_frontend() -> dict:
    dist = os.path.join(BASE, "web", "dist", "index.html")
    src_dir = os.path.join(BASE, "web", "src")
    if not os.path.isfile(dist):
        return {"name": "前端产物", "passed": False, "detail": "web/dist/index.html 不存在",
                "fix": "cd web && npm run build"}
    dist_m = os.path.getmtime(dist)
    newest, newest_f = 0.0, ""
    for root, _dirs, files in os.walk(src_dir):
        for f in files:
            p = os.path.join(root, f)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > newest:
                newest, newest_f = m, os.path.relpath(p, BASE)
    if newest > dist_m:
        return {"name": "前端产物", "passed": False,
                "detail": f"源码比产物新：{newest_f}",
                "fix": "cd web && npm run build（源码已改但未重新构建）"}
    age_h = (time.time() - dist_m) / 3600
    return {"name": "前端产物", "passed": True,
            "detail": f"web/dist 最新（{age_h:.1f} 小时前构建）", "fix": ""}


def check_schema() -> dict:
    try:
        from config import DB_PATH
        from data.db_core import init_db, get_db
        init_db(DB_PATH)
        with get_db() as conn:
            row = conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
            db_v = row["v"] if row else 0
        import re
        src = open(os.path.join(BASE, "data", "db_core.py"), encoding="utf-8").read()
        code_v = max(int(m) for m in re.findall(r"^\s*\((\d+),\s*\"", src, re.M))
        ok = db_v == code_v
        return {"name": "数据库 schema 版本", "passed": ok,
                "detail": f"库 v{db_v} / 代码 v{code_v}",
                "fix": "" if ok else "库未迁移到最新：python -c \"from config import DB_PATH;from data.db_core import init_db;init_db(DB_PATH)\""}
    except Exception as e:  # noqa: BLE001
        return {"name": "数据库 schema 版本", "passed": False, "detail": str(e)[:120],
                "fix": "检查 data/community_insight.db 是否存在且可读"}


def check_env() -> dict:
    """检查演示姿态：有无 LLM key / 向量 key，决定演示话术（不打印密钥值）。"""
    try:
        import config
        llm = bool(config.DEEPSEEK_API_KEY)
        emb_on = getattr(config, "EMBEDDING_PROVIDER", "none")
        emb_key = bool(getattr(config, "DASHSCOPE_API_KEY", "") or getattr(config, "ZHIPU_API_KEY", ""))
        rag_llm = bool(getattr(config, "POLICY_LLM_RAG", False))
        pose = []
        pose.append("LLM=真实" if llm else "LLM=规则引擎（无 key 自动降级）")
        pose.append(f"向量={emb_on}" + ("（已配 key）" if emb_key else "（无 key，词法模式）"))
        pose.append(f"政策LLM生成={'开' if rag_llm else '关'}")
        # 密钥姿态（不打印密钥值）：只是提示，不新增检查项（保持 9 项口径不变）
        import os as _os
        _INSECURE = {"", "dev-crypto-key-change-me", "demo-please-set-a-crypto-key", "demo-please-set-a-production-secret"}
        crypto_ok = _os.environ.get("CRYPTO_KEY", "").strip() not in _INSECURE
        pose.append("加密密钥=" + ("自定义" if crypto_ok else "默认/占位（仅演示，生产会拒绝启动）"))
        return {"name": ".env 演示姿态", "passed": True, "detail": " | ".join(pose), "fix": ""}
    except Exception as e:  # noqa: BLE001
        return {"name": ".env 演示姿态", "passed": False, "detail": str(e)[:120],
                "fix": "检查 .env（可由 .env.example / .env.demo.example 复制）"}


def check_server() -> dict:
    """服务可达性 + **身份校验**（端口被别的进程占用时会静默劫走请求，必须区分）。

    实测踩坑：另一个程序的 mock 服务绑在 127.0.0.1:8000（比我们的 0.0.0.0 更具体），
    健康检查返回 200 但响应体不是本服务的 JSON —— 若只判「200 即通过」，演示会当场翻车。
    这里额外校验响应形状（success + data.service），不是本服务就明确报「端口被其它进程占用」。
    """
    st, body = _http("/api/web/health")
    if st == 0:
        return {"name": "服务可达（:8000）", "passed": False,
                "detail": "无响应：服务未启动或端口未监听",
                "fix": "python -m uvicorn api_web:app --host 0.0.0.0 --port 8000"}
    if st == 200 and isinstance(body, dict) and body.get("success"):
        svc = (body.get("data") or {}).get("service", "")
        if svc:
            return {"name": "服务可达（:8000）", "passed": True, "detail": svc, "fix": ""}
    # 200 但响应不是本服务（端口被别的进程占用 / 代理劫持）
    snippet = str(body)[:80] if body is not None else "(空响应)"
    return {"name": "服务可达（:8000）", "passed": False,
            "detail": f"端口被其它进程占用：响应不是本服务（{snippet}）",
            "fix": ("先查看占用者并结束它，再启动本服务：\n"
                    "      Get-NetTCPConnection -LocalPort 8000 -State Listen | "
                    "ForEach-Object { Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.OwningProcess)\" | "
                    "Select-Object ProcessId,CommandLine }\n"
                    "      python -m uvicorn api_web:app --host 0.0.0.0 --port 8000")}


def check_accounts() -> dict:
    """三个演示账号可登录 + 鉴权中间件在跑（无 token → 401）。"""
    roles = [("resident", "居民端"), ("elderly", "老年端"), ("grid", "网格员端")]
    bad = []
    for role, label in roles:
        st, body = _post("/api/web/auth/demo", {"role": role})
        token = ((body or {}).get("data") or {}).get("token") if isinstance(body, dict) and st == 200 else None
        if not token:
            bad.append(label)
            continue
        st2, _me = _http("/api/web/auth/me")  # 无 token 应 401（顺带验证鉴权中间件在跑）
        if st2 != 401:
            bad.append(f"{label}(鉴权异常)")
    if bad:
        return {"name": "演示账号可登录", "passed": False, "detail": f"异常：{'、'.join(bad)}",
                "fix": ("若「服务可达」已失败，先解决端口占用/服务未启动；"
                        "否则确认 DEMO_MODE=true 且演示账号存在："
                        "python -c \"from config import DB_PATH;from data.seed import seed_all;seed_all(DB_PATH)\"")}
    return {"name": "演示账号可登录", "passed": True,
            "detail": "居民/老年/网格员三角色均可登录，鉴权中间件正常（无 token → 401）", "fix": ""}


def _force_utf8_stdout() -> None:
    """Windows 中文控制台默认 GBK，会因 ✅/❌ 触发 UnicodeEncodeError 直接崩。

    答辩前现场跑这个脚本时崩溃是最糟的失败模式，因此这里主动把 stdout/stderr
    切到 UTF-8；老终端不支持时降级为 errors='replace'（图标变 ?，检查结果仍可读）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main() -> int:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="答辩/演示前自检（U5）")
    ap.add_argument("--fast", action="store_true", help="跳过测试与构建（现场快速体检）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    checks = [
        check_schema(), check_env(), check_frontend(), check_server(), check_accounts(),
        check_phone_encryption(), check_brand_metrics(args.fast),
        check_ruff(args.fast), check_tests(args.fast),
    ]
    failed = [c for c in checks if not c["passed"]]
    result = {"passed": len(checks) - len(failed), "total": len(checks),
              "failed": len(failed), "checks": checks}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=== 演示前自检（U5）" + (" · fast 模式" if args.fast else "") + " ===")
        for c in checks:
            mark = "✅" if c["passed"] else "❌"
            print(f"{mark} {c['name']}：{c['detail']}")
            if not c["passed"] and c.get("fix"):
                print(f"    → 修复：{c['fix']}")
        print(f"\n结果：{result['passed']}/{result['total']} 通过" +
              ("（全部就绪，可以开始演示）" if not failed else f"，{len(failed)} 项待修复"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
