# -*- coding: utf-8 -*-
"""U5 演示前自检测试：检查项可跑通、能检出问题、输出含修复指令。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import demo_preflight as P


def test_fast_checks_all_run():
    """fast 模式各检查项都能返回结构化结果（不抛异常）。"""
    checks = [P.check_schema(), P.check_env(), P.check_frontend(), P.check_server(),
              P.check_accounts(), P.check_brand_metrics(True), P.check_ruff(True), P.check_tests(True)]
    for c in checks:
        assert set(c) >= {"name", "passed", "detail", "fix"}, c
        assert isinstance(c["passed"], bool)
    # schema 版本是确定性检查（库与代码应一致）
    assert P.check_schema()["passed"], P.check_schema()
    # 前端检查是**状态相关**（源码改了未 build 就会失败）——只断言行为契约：
    # 未通过时必须给出 npm run build 指令（不把「仓库当前已构建」写死进测试）
    fe = P.check_frontend()
    if not fe["passed"]:
        assert "npm run build" in fe["fix"], fe


def test_server_down_is_detected_with_fix():
    """服务不可达必须被判失败，并给出可执行的修复命令（负向用例）。"""
    orig = P.API
    try:
        P.API = "http://127.0.0.1:59999"  # 无服务端口
        r = P.check_server()
        assert r["passed"] is False
        assert "uvicorn" in r["fix"], "必须给出启动命令"
    finally:
        P.API = orig


def test_env_pose_never_leaks_secret():
    """.env 姿态检查不得回显密钥内容（只报有无）。"""
    r = P.check_env()
    assert r["passed"], r
    d = r["detail"]
    import config
    for name in ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "ZHIPU_API_KEY"):
        v = getattr(config, name, "")
        if v:
            assert v not in d, f"姿态详情泄露了 {name} 的值"
    assert "LLM=" in d and "向量=" in d


def test_accounts_check_reports_each_role():
    """账号检查在服务不可达时应报失败（不静默通过）。"""
    orig = P.API
    try:
        P.API = "http://127.0.0.1:59999"
        r = P.check_accounts()
        assert r["passed"] is False
        assert r["fix"], "应给出修复提示"
    finally:
        P.API = orig


def test_utf8_stdout_guard_never_raises():
    """回归：Windows 中文控制台（GBK）打印 ✅ 会 UnicodeEncodeError 直接崩。

    自检脚本崩在答辩现场是最糟的失败模式，所以 _force_utf8_stdout 必须在
    任何流形态下都不抛异常（含缺少 reconfigure 的对象 / reconfigure 报错的流），
    并且在真实可重配的流上确实把编码切到 UTF-8。
    """
    import io

    class _NoReconfigure:
        pass

    class _RaisesOnReconfigure:
        def reconfigure(self, **_kw):
            raise ValueError("stream is closed")

    orig_out, orig_err = sys.stdout, sys.stderr
    try:
        # 1) 缺 reconfigure 的流：跳过，不抛
        sys.stdout = _NoReconfigure()
        P._force_utf8_stdout()
        # 2) reconfigure 抛异常的流：吞掉异常，不抛
        sys.stderr = _RaisesOnReconfigure()
        P._force_utf8_stdout()
        # 3) 真实文本流（GBK 模拟中文控制台）：确实切到 UTF-8
        buf = io.BytesIO()
        gbk = io.TextIOWrapper(buf, encoding="gbk")
        sys.stdout = gbk
        P._force_utf8_stdout()
        assert gbk.encoding.lower().replace("-", "") == "utf8"
        gbk.write("✅")  # 修复前这里会 UnicodeEncodeError
        gbk.flush()
    finally:
        sys.stdout, sys.stderr = orig_out, orig_err


def test_brand_metrics_match_backend():
    """登录页品牌指标（meta.js）必须与后端/仓库实测一致（外部评审 P2 的一致性门禁）。

    防的是「登录页写 62%、大屏实测 90.9%」这类数字打架——那会直接削弱「数据可验证」的卖点。
    """
    declared = P.parse_brand_metrics()
    assert declared, "meta.js 应至少声明一项指标"
    assert set(declared) >= {"tests", "rag_golden", "rag_hit1", "agents"}, declared

    # golden 集条数：必须与 rag_eval 的真实 loader 同口径（文件里有 9 行 # 注释，按行数会误判）
    from scripts.rag_eval import load_golden
    assert P.count_rag_golden() == len(load_golden()), "count_rag_golden 与 rag_eval.load_golden 口径不一致"
    assert declared["rag_golden"] == len(load_golden()), \
        f"登录页写 {declared['rag_golden']} 条，实测 {len(load_golden())} 条"

    # 智能体角色数：以 AGENT_CLASSES 为准
    from agent.roles import AGENT_CLASSES
    assert declared["agents"] == len(AGENT_CLASSES), \
        f"登录页写 {declared['agents']} 个角色，实测 {len(AGENT_CLASSES)} 个"

    # fast 模式不跑 --collect-only，但仍要返回结构化的通过结果
    r = P.check_brand_metrics(True)
    assert r["passed"], r


def test_brand_metrics_detects_drift(tmp_path):
    """负向用例：meta.js 被改歪（数字与实测不符）时，检查必须判失败并给出修复指引。"""
    src = P.parse_brand_metrics()
    fake = tmp_path / "meta.js"
    lines = ["export const BRAND_METRICS = ["]
    for k, v in src.items():
        bumped = v + 1 if k in ("rag_golden", "agents") else v
        lines.append(f"  {{ key: '{k}', value: {bumped} }},")
    lines.append("]")
    fake.write_text("\n".join(lines), encoding="utf-8")

    orig = P.META_JS
    try:
        P.META_JS = str(fake)
        r = P.check_brand_metrics(True)
        assert r["passed"] is False, "数字与实测不符时必须判失败"
        assert "rag_golden" in r["detail"] and "agents" in r["detail"]
        assert "meta.js" in r["fix"]
    finally:
        P.META_JS = orig
