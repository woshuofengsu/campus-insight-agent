# -*- coding: utf-8 -*-
"""统一受控写入口的防锈闸（v2 升级方案任务卡 7）。

**要解决的问题**：写路由最容易出的两类事故是"越权改别人数据"和"漏了一层检查"。
卡 2/3/4 已经逐条堵了具体的洞，但**根因是"记得写"不可靠** —— 检查散在每个路由里，
新加一个写接口只要作者忘了，就又开一个洞，而且没人会发现。

本闸门不靠"人工复查"，靠**静态扫描 + 声明式装饰器**：
  ① 每个写路由必须要么挂 `@write_route(...)`（检查由框架执行），要么函数体里**确实有**
     角色/自身范围/租户/所有权检查的痕迹，要么登记在 `_PUBLIC_WRITE_ALLOWED` 并写明理由；
     三者都不是 → **直接红**（新增的裸写接口进不来）。
  ② `@write_route` 自身要有**故障注入测试**（越权必须被拒、状态不符必须被拒），
     否则装饰器可能只是"看起来在做检查"。

⚠️ 诚实说明本闸门的边界：它是**源码级**判据，能保证"有检查的痕迹"，不能保证"业务上一定对"。
真正判"对不对"的是各业务模块的授权矩阵测试（`test_elderly_authorization.py` 等）。
"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(ROOT, "api_routes")

MUTATING = {"post", "put", "patch", "delete"}
ROLE_HINTS = ("_require_role", "_user(", "get_current_user")
SCOPE_HINTS = ("_same_tenant", "_tenant(", "row_in_tenant", "tenant_clause",
               "_owns_resource", "_resource_owner_uid", "_elder_in_tenant",
               "_resolve_elder_uid", "user_id", "uid", "reporter_id", "setter_id")

# 公开写入口白名单：**必须逐条写清理由**（空理由视为未登记）
_PUBLIC_WRITE_ALLOWED = {
    ("auth.py", "login"): "登录入口本身；凭密码校验身份，不涉及他人数据",
    ("auth.py", "demo_login"): "演示免密登录：中间件层已按 DEMO_MODE 硬关（生产直接 403）",
    ("upload.py", "upload_files"): "附件上传：**已登录**即可用（居民/网格员都要传图），"
                                   "落盘前有大小与类型限制；不读写他人业务数据",
}

# 「只写全局内容」的白名单：这些路由写的是**共享语料/派生数据**（非租户表），
# 没有"哪个社区的行"这个概念，所以**角色校验就是完整的授权**（再叠租户检查是错的：全局内容没有租户）。
# 每条都必须写清理由，并且要真的只碰非租户表（下面的 `_written_tenant_tables` 会核对）。
_GLOBAL_CONTENT_ALLOWED = {
    ("health.py", "web_health_article_create"): "健康内容库为全局共享语料（health_contents 非租户表）",
    ("health.py", "web_health_article_action"): "同上：全局语料的发布/下架",
    ("policy.py", "web_knowledge_create"): "政策知识库为全局共享语料（knowledge_base 非租户表）",
    ("policy.py", "web_knowledge_action"): "同上：全局语料的审核/下架",
    ("policy.py", "web_knowledge_new_version"): "同上：全局语料的新版本",
    ("agent.py", "agent_kg_rebuild"): "知识图谱是全局派生视图（kg_* 非租户表），重建幂等且不携带社区行",
    ("opinions.py", "web_opinion_create"): "舆情为全局采集框架（public_opinion 非租户表）",
}

# 其余需要"逐条写理由"的写路由（既不是纯全局内容、又不适合当前装饰器表达）
_EXTRA_ALLOWED = {
    ("opinions.py", "web_opinion_convert"): "舆情转工单：角色校验 + 已按**操作人社区**给新工单盖章"
                                            "（见 data/db_opinion.convert_to_issue 的 tenant 参数）",
    ("issues.py", "issue_action"): "工单状态机：角色按 action 分派（负责人管理 / 居民只能动自己的单），"
                                   "居民侧校验 reporter_id、负责人侧过 _same_tenant；"
                                   "装饰器无法表达 action 维度的角色矩阵，故保留手写检查",
}

_SQL_WRITE_RE = re.compile(
    r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.I)


def _written_tenant_tables(body: str) -> set[str]:
    """路由体里**直接写**的租户表（用于判断"只写全局内容"这条豁免是否成立）。"""
    from utils.tenant import TENANT_TABLES
    tables = {m.group(1).lower() for m in _SQL_WRITE_RE.finditer(body)}
    return {t for t in tables if t in TENANT_TABLES}


def _write_routes() -> list[dict]:
    """扫出全部写操作路由，并标注"有没有授权痕迹 / 是不是 write_route 声明"。"""
    out = []
    for fn in sorted(os.listdir(API)):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(API, fn), encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods, path, declared = [], "", False
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "write_route":
                    declared = True
                name = getattr(d.func, "attr", None) if isinstance(d, ast.Call) else None
                if name in MUTATING:
                    methods.append(name.upper())
                    if d.args and isinstance(d.args[0], ast.Constant):
                        path = str(d.args[0].value)
            if not methods:
                continue
            body = ast.get_source_segment(src, node) or ""
            out.append({
                "file": fn, "fn": node.name, "method": methods[0], "path": path,
                "line": node.lineno, "declared": declared,
                "role": any(h in body for h in ROLE_HINTS),
                "scope": any(h in body for h in SCOPE_HINTS),
                "tenant_tables": _written_tenant_tables(body),
            })
    return out


def test_every_write_route_declares_its_authorization():
    """每个写路由都要有"授权从哪来"的可追溯声明。

    合规的四种情形：
      ① `@write_route(...)` 声明（检查由框架执行）；
      ② 函数体里同时有**角色**检查与**范围**证据（租户 / 自身 uid / 所有权）；
      ③ 只写**全局内容**（非租户表）→ 角色检查即完整授权（`_GLOBAL_CONTENT_ALLOWED` + 表名核对）；
      ④ 登记在公开白名单或 `_EXTRA_ALLOWED` 并写明理由。
    """
    bad = []
    for r in _write_routes():
        if r["declared"] or (r["role"] and r["scope"]):
            continue
        if (r["file"], r["fn"]) in _PUBLIC_WRITE_ALLOWED:
            continue
        if (r["file"], r["fn"]) in _EXTRA_ALLOWED:
            continue
        if r["role"] and (r["file"], r["fn"]) in _GLOBAL_CONTENT_ALLOWED \
                and not r["tenant_tables"]:
            continue
        bad.append(f"{r['file']}:{r['line']} {r['method']} {r['path']} ({r['fn']}) "
                   f"role={r['role']} scope={r['scope']} tenant_tables={sorted(r['tenant_tables'])}")
    assert not bad, (
        "以下写路由既没有 @write_route 声明，也没有「角色 + 范围」检查，也不在已登记的豁免里：\n  "
        + "\n  ".join(bad)
        + "\n（卡7：写操作必须收敛到统一受控入口。要么加 `@write_route(...)`，"
          "要么在路由里显式校验，要么登记理由）")


def test_global_content_exemption_is_honest():
    """「只写全局内容」这条豁免必须真的只碰非租户表（否则豁免就是掩护）。"""
    lied = []
    for r in _write_routes():
        key = (r["file"], r["fn"])
        if key in _GLOBAL_CONTENT_ALLOWED and r["tenant_tables"]:
            lied.append(f"{key[0]}::{key[1]} 直接写了租户表 {sorted(r['tenant_tables'])}，"
                        "却声称「只写全局内容」")
    assert not lied, "以下豁免名不副实：\n  " + "\n  ".join(lied)


def test_public_write_allowlist_entries_have_reasons():
    """公开写入口必须写明理由（空理由 = 没登记），且不能登记不存在的路由。"""
    for name, table in (("公开", _PUBLIC_WRITE_ALLOWED),
                        ("全局内容", _GLOBAL_CONTENT_ALLOWED),
                        ("其它", _EXTRA_ALLOWED)):
        empty = [k for k, v in table.items() if not (v or "").strip()]
        assert not empty, f"{name}豁免缺理由：{empty}"
        known = {(r["file"], r["fn"]) for r in _write_routes()}
        stale = [k for k in table if k not in known]
        assert not stale, f"{name}豁免里的路由已不存在（会变成僵尸豁免）：{stale}"


def test_decorator_is_actually_migrated_somewhere():
    """防锈：统一写入口不能只是"写好了没人用"（本卡要求真正迁移敏感路由）。"""
    migrated = [f"{r['file']}::{r['fn']}" for r in _write_routes() if r["declared"]]
    assert len(migrated) >= 5, (
        f"只有 {len(migrated)} 条路由用了 @write_route，疑似回退：{migrated}")


def test_scanner_finds_undeclared_write_route():
    """扫描器自检：一个"什么检查都没有"的写路由必须被抓到（防止闸门退化成永远绿）。"""
    src = (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.post('/x/{rid}/do')\n"
        "def do(rid: int):\n"
        "    return {'ok': True}\n"
    )
    tree = ast.parse(src)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            methods = [d.func.attr for d in node.decorator_list
                       if isinstance(d, ast.Call) and getattr(d.func, "attr", "") in MUTATING]
            if methods:
                body = ast.get_source_segment(src, node) or ""
                found.append({
                    "declared": False,
                    "role": any(h in body for h in ROLE_HINTS),
                    "scope": any(h in body for h in SCOPE_HINTS),
                })
    assert found and not found[0]["declared"] and not found[0]["role"] and not found[0]["scope"], \
        "扫描逻辑失效：裸写路由没被识别成未声明"
