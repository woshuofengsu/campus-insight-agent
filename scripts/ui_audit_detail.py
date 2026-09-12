# scripts/ui_audit_detail.py — 打印某页审计明细（临时工具）
# -*- coding: utf-8 -*-
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

d = json.load(open(".shots/ui-audit.json", encoding="utf-8"))
name = sys.argv[1]
v = d[name]
print("### overs")
for o in v["overs"]:
    print(f"   {o['sel']:60s} l={o['left']:5d} r={o['right']:5d} w={o['w']:4d} «{o['text']}»")
print("### contrast")
for c in v["contrast"]:
    print(f"   {c['ratio']}:1 need {c['need']}  {c['px']}px  {c['sel']:40s} «{c['text']}» {c['color']}")
print("### fonts")
for f in v["fonts"]:
    print(f"   {f['px']}px need>={f['need']}  {f['sel']:40s} «{f['text']}»")
print("### targets")
for t in v["targets"]:
    print(f"   {t['w']}x{t['h']}  {t['sel']:40s} «{t['text']}»")
print("### panels/anim/reduced")
print("  ", v.get("panels"))
print("  ", [f"{k}:{vv}" for k, vv in (v.get("anim") or {}).items()])
print("  ", v.get("reduced"))
print("  js:", v.get("jsErrors"))
