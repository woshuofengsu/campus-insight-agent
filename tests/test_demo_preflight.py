# -*- coding: utf-8 -*-
"""U5 演示前自检测试：检查项可跑通、能检出问题、输出含修复指令。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import demo_preflight as P


def test_fast_checks_all_run():
    """fast 模式各检查项都能返回结构化结果（不抛异常）。"""
    checks = [P.check_schema(), P.check_env(), P.check_frontend(), P.check_server(),
              P.check_accounts(), P.check_ruff(True), P.check_tests(True)]
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
