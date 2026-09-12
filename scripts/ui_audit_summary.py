# scripts/ui_audit_summary.py — 汇总 .shots/ui-audit.json（简短表）
# -*- coding: utf-8 -*-
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

path = sys.argv[1] if len(sys.argv) > 1 else ".shots/ui-audit.json"
d = json.load(open(path, encoding="utf-8"))
for k, v in d.items():
    if "error" in v:
        print(f"{k:22s} ERROR {v['error']}")
        continue
    js = len(v.get("jsErrors") or [])
    print(f"{k:22s} url={v['url']:22s} vw={v['vw']:4d} ovX={v['overflowX']:4d} "
          f"contrast={len(v['contrast']):2d} targets={len(v['targets']):2d} "
          f"fonts={len(v['fonts']):2d} overs={len(v['overs']):2d} broken={len(v['broken'])} js={js}")
