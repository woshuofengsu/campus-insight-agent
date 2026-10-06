# -*- coding: utf-8 -*-
"""**恢复演练**：把最新备份真的恢复出来、逐项校验、并记录耗时。

为什么单独写它（而不是"备份脚本跑成功就算数"）：
**没演练过的备份等于没有备份**。备份"看起来成功"很常见（文件在那儿、大小也对），
但恢复时才发现快照缺页、schema 版本对不上、加密列解不开——
到那时候才发现的代价，就是社区的工单全没了。

本脚本做三件事，且**只读真实库、绝不修改它**：
  ① 取最新备份 → 还原到一个**临时目录**（不动生产库一个字节）；
  ② 按备份清单逐项比对：schema 版本、关键表行数、完整性检查、
     **手机号列仍是密文且可解密**、租户字段无空值；
  ③ 打印**恢复耗时**（试点指标里的"备份恢复耗时"就取这个数）。

用法：
    python scripts/restore_drill.py            # 演练并输出报告
    python scripts/restore_drill.py --json      # 机器可读（写进试点记录）

退出码：0 = 全部校验通过；非 0 = 有项不通过（**演练失败必须让人看见**）。
"""
import argparse
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BACKUP_DIR = os.path.join(ROOT, "backups")
#: 需要检查"明文必须为空"的手机号列（与 scripts/audit_phone_encryption.py 同口径）
PHONE_TABLES = {
    "community_issues": ("reporter_phone", "reporter_phone_enc"),
    "user_profile": ("phone", "phone_enc"),
    "emergency_contacts": ("phone", "phone_enc"),
    "health_consults": ("phone", "phone_enc"),
    "emergency_calls": ("target_phone", "target_phone_enc"),
    "proposals": ("reporter_phone", "reporter_phone_enc"),
    "proposal_drafts": ("reporter_phone", "reporter_phone_enc"),
    "issue_drafts": ("reporter_phone", "reporter_phone_enc"),
}


def _latest_backup() -> tuple[str, str]:
    """返回 (备份文件, 清单文件)。找不到就抛错——演练没有对象就该失败。"""
    if not os.path.isdir(BACKUP_DIR):
        raise FileNotFoundError(f"备份目录不存在：{BACKUP_DIR}")
    files = sorted(f for f in os.listdir(BACKUP_DIR)
                   if f.startswith("community_insight-"))
    if not files:
        raise FileNotFoundError("没有找到任何备份文件（先跑 scripts/backup_db.py）")
    latest = files[-1]
    stamp = latest.rsplit("-", 1)[-1].split(".")[0]
    manifests = [f for f in os.listdir(BACKUP_DIR)
                 if f.startswith("manifest-") and stamp in f]
    if not manifests:
        raise FileNotFoundError(f"{latest} 没有配套清单（无法比对，拒绝出具'恢复成功'）")
    return os.path.join(BACKUP_DIR, latest), os.path.join(BACKUP_DIR, manifests[0])


def _check_decryptable(conn: sqlite3.Connection, notes: list) -> tuple[int, int]:
    """加密列检查：明文必须为空；密文必须**能解回非空**（否则等于数据丢了）。"""
    sys.path.insert(0, ROOT)
    from data.db_repair import _dec_phone
    plain_leaks, undecryptable = 0, 0
    for table, (plain_col, enc_col) in PHONE_TABLES.items():
        try:
            rows = conn.execute(
                f"SELECT {plain_col}, {enc_col} FROM {table} "
                f"WHERE COALESCE({enc_col},'') <> ''").fetchall()
        except sqlite3.Error:
            continue      # 表不存在 → 跳过（不假装检查过）
        for plain, enc in rows:
            if (plain or "").strip():
                plain_leaks += 1
            try:
                if not str(_dec_phone(enc, "") or "").strip():
                    undecryptable += 1
            except Exception:  # noqa: BLE001 — 解密失败就是问题，计一次
                undecryptable += 1
    if plain_leaks:
        notes.append(f"手机号明文列有 {plain_leaks} 行非空（脱敏/加密链路有问题）")
    if undecryptable:
        notes.append(f"有 {undecryptable} 行密文解不回明文（备份不可用于恢复）")
    return plain_leaks, undecryptable


def _check_tenant(conn: sqlite3.Connection, notes: list) -> int:
    """租户字段完整性：社区范围表的 `tenant_id` 不该有空值（空 = 自己人也看不见）。"""
    empty = 0
    for table in ("community_issues", "agent_handoffs", "notices"):
        try:
            n = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE COALESCE(tenant_id,'')=''"
            ).fetchone()[0]
        except sqlite3.Error:
            continue
        if n:
            empty += n
            notes.append(f"{table} 有 {n} 行 tenant_id 为空")
    return empty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict = {"drill_at": datetime.now().isoformat(timespec="seconds"),
                    "checks": {}, "notes": [], "passed": False}
    t0 = time.time()
    tmpdir = tempfile.mkdtemp(prefix="restore_drill_")
    try:
        backup, manifest_path = _latest_backup()
        manifest = json.loads(io.open(manifest_path, encoding="utf-8").read())
        report["backup_file"] = os.path.basename(backup)
        report["manifest_file"] = os.path.basename(manifest_path)

        # ① 恢复：拷到临时目录（生产库一个字节都不动）
        restored = os.path.join(tmpdir, "restored.db")
        shutil.copy2(backup, restored)
        restore_seconds = round(time.time() - t0, 2)
        report["restore_seconds"] = restore_seconds

        conn = sqlite3.connect(restored)
        try:
            # ② 逐项校验
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            report["checks"]["integrity_check"] = integrity
            sv = conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
            restored_schema = int(sv[0]) if sv and sv[0] is not None else None
            report["checks"]["schema_version"] = restored_schema
            report["checks"]["schema_matches_manifest"] = (
                restored_schema == manifest.get("schema_version"))

            counts = {}
            for t, want in (manifest.get("table_counts") or {}).items():
                try:
                    got = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except sqlite3.Error:
                    got = None
                counts[t] = {"restored": got, "manifest": want, "match": got == want}
            report["checks"]["table_counts"] = counts
            report["checks"]["counts_all_match"] = all(
                v["match"] for v in counts.values()) if counts else False

            leaks, undec = _check_decryptable(conn, report["notes"])
            report["checks"]["phone_plaintext_rows"] = leaks
            report["checks"]["phone_undecryptable_rows"] = undec
            empty_tenant = _check_tenant(conn, report["notes"])
            report["checks"]["tenant_empty_rows"] = empty_tenant
        finally:
            conn.close()

        # ③ 判定
        c = report["checks"]
        report["passed"] = bool(
            c.get("integrity_check") == "ok"
            and c.get("schema_matches_manifest")
            and c.get("counts_all_match")
            and c.get("phone_plaintext_rows") == 0
            and c.get("phone_undecryptable_rows") == 0
            and c.get("tenant_empty_rows") == 0)
        report["total_seconds"] = round(time.time() - t0, 2)
    except Exception as e:  # noqa: BLE001 — 演练失败必须显式失败
        report["notes"].append(f"演练中断：{e}")
        report["total_seconds"] = round(time.time() - t0, 2)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    print("=" * 74)
    print("备份恢复演练报告")
    print("=" * 74)
    print(f"备份文件：{report.get('backup_file', '（无）')}")
    print(f"恢复耗时：{report.get('restore_seconds', '—')} 秒"
          f"（含校验共 {report.get('total_seconds')} 秒）")
    c = report["checks"]
    if c:
        print(f"① 完整性检查      : {c.get('integrity_check')}")
        print(f"② schema 版本     : {c.get('schema_version')}"
              f"（{'与清单一致' if c.get('schema_matches_manifest') else '与清单不一致'}）")
        print(f"③ 关键表行数      : {'全部一致' if c.get('counts_all_match') else '有不一致'}")
        print(f"④ 手机号明文残留  : {c.get('phone_plaintext_rows')} 行（应为 0）")
        print(f"⑤ 密文不可解密    : {c.get('phone_undecryptable_rows')} 行（应为 0）")
        print(f"⑥ 租户字段为空    : {c.get('tenant_empty_rows')} 行（应为 0）")
    for n in report["notes"]:
        print(f"   [异常] {n}")
    print()
    # 注意：这里**不用 emoji/✅**——Windows 控制台默认 GBK，打不出来会**在演练通过之后崩掉**，
    # 于是"演练成功"被报成"脚本失败"（实测踩到过）。`tests/test_no_emoji_ui.py` 现在也扫脚本。
    print("结论：" + ("[通过] 恢复演练**通过**（这条数字可以写进试点记录）"
                     if report["passed"] else
                     "[未通过] 恢复演练**失败**——按纪律，此时不得声称具备恢复能力"))
    print("=" * 74)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
