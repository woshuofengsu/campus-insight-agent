# -*- coding: utf-8 -*-
"""一次性维护脚本：把「当前状态文档」里的 schema / 迁移条数同步到 v53 / 52。

为什么需要这样一个脚本：`sync_test_count.py` 只管「用例数 + UI 覆盖面」，
**结构数字（schema 版本、迁移条数）没有任何一键同步入口** —— 每次加迁移，
就得手改十几处文档，漏一处门禁才报。这个脚本补上这个口子（下次加迁移可以直接用）。

⚠️ 只改**当前值**；`<!-- baseline:historical:begin/end -->` 里的历史快照**一字不动**
（改它等于篡改历史），这与 `check_claims` / `sync_test_count` 同口径。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.check_claims import (COUNT_EXEMPT, CURRENT_DOCS, SNAPSHOT_DOCS,
                                  STRUCTURE_EXEMPT, _current_lines, _unclosed_hist_block)
from scripts.sync_test_count import split_historical

EXTRA = ["docs/复现指南.md", "docs/scaling.md"]
#: 豁免名单：这些是**历史记录**（变更日志/交接快照），里面的版本号是"当时是什么样"，
#: 改它等于篡改历史。实测踩到：第一版脚本把 `CHANGELOG.md` 也改了，只能 git 撤销。
EXEMPT = set(COUNT_EXEMPT) | set(STRUCTURE_EXEMPT)


def _rewrite(text: str, schema: int, migrations: int) -> str:
    """只改块外内容（split_historical 给出的 'not hist' 段）。"""
    out = []
    for hist, seg in split_historical(text):
        if hist:
            out.append(seg)
            continue
        s = seg
        # schema 版本（含加粗与 mermaid 里的 `SQLite vNN` 写法）
        s = re.sub(r"(schema\s*\*{0,2}v)\d+", rf"\g<1>{schema}", s)
        s = re.sub(r"(SQLite\s+v)\d+", rf"\g<1>{schema}", s)
        # 迁移条数：「51 个版本化迁移 / 51 个迁移」
        s = re.sub(r"\b\d+(\s*个(?:版本化)?迁移)", rf"{migrations}\g<1>", s)
        out.append(s)
    return "".join(out)


def main() -> int:
    schema = int(sys.argv[1]) if len(sys.argv) > 1 else 53
    migrations = int(sys.argv[2]) if len(sys.argv) > 2 else 52
    docs = list(dict.fromkeys(CURRENT_DOCS + SNAPSHOT_DOCS + EXTRA))
    changed = []
    for doc in docs:
        if os.path.basename(doc) in EXEMPT or doc in EXEMPT:
            continue      # 历史记录（CHANGELOG / HANDOFF）不动
        p = os.path.join(ROOT, doc)
        if not os.path.exists(p):
            continue
        orig = io.open(p, encoding="utf-8").read()
        if _unclosed_hist_block(orig):
            print(f"  ⚠️ 跳过 {doc}：历史块标记不成对（先修标记，别让脚本乱改）")
            continue
        new = _rewrite(orig, schema, migrations)
        if new != orig:
            io.open(p, "w", encoding="utf-8", newline="").write(new)
            n = sum(1 for a, b in zip(_current_lines(orig), _current_lines(new)) if a != b)
            changed.append(f"{doc}（{n} 行）")
    if changed:
        print(f"已同步 schema v{schema} / {migrations} 个迁移：")
        for c in changed:
            print("  -", c)
    else:
        print(f"✅ 无需修改（schema v{schema} / {migrations} 个迁移已一致）")
    print("\n提示：跑 `python scripts/check_claims.py` 复核（历史块内容不会被本脚本触碰）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
