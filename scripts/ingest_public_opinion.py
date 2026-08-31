# -*- coding: utf-8 -*-
"""舆情外部源接入框架（P2-2，演示级 + 可扩展）。

设计：
- SourceAdapter 接口：fetch() 返回 [{content, source, keywords}]，供真实外部源实现。
- MockSource：内置演示数据（3 档分级），证明"能接"。
- 主入口拉取各源 → add_opinion 写入（自动分级）→ 打印入库结果。
- 真实外部源（政务 12345 / RSS / 微博）后续实现同接口即可接入，不改动入库逻辑。

用法：
    python scripts/ingest_public_opinion.py            # 默认 mock 源
    python scripts/ingest_public_opinion.py --source mock
"""
import argparse
import os
import sys
from abc import ABC, abstractmethod

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEMO_MODE", "true")

from data.db_opinion import add_opinion  # noqa: E402


def _ensure_db() -> None:
    from data import db_core
    if not db_core._DB_PATH:
        import config
        db_core.init_db(config.DB_PATH)


# =====================================================================
# 源适配器接口：真实外部源实现该抽象类即可接入
# =====================================================================

class SourceAdapter(ABC):
    """舆情源适配器基类。子类实现 fetch()。"""

    @abstractmethod
    def fetch(self) -> list[dict]:
        """拉取一批舆情，返回 [{content, source, keywords}]。"""

    def name(self) -> str:
        return type(self).__name__


class MockSource(SourceAdapter):
    """演示级 mock 源：3 条覆盖 3 档分级，证明接入链路可行。"""

    def fetch(self) -> list[dict]:
        return [
            {"content": "小区广场大树被风吹倒，砸到停放的电动车（红色），速燃气管道爆炸风险",
             "source": "12345热线", "keywords": "树倒,砸车"},
            {"content": "四号楼电梯连续三天故障，老人下楼买菜困难，希望能尽快维修",
             "source": "本地论坛", "keywords": "电梯,故障,老人"},
            {"content": "楼下垃圾桶满溢没人清，夏天味道大，建议增加清运频率",
             "source": "微信公众号留言", "keywords": "垃圾桶,异味"},
        ]


_REGISTRY = {"mock": MockSource}


# =====================================================================
# 主入口
# =====================================================================

def ingest(source_name: str = "mock") -> int:
    """拉取并入库指定源，返回入库条数。"""
    _ensure_db()
    adapter_cls = _REGISTRY.get(source_name)
    if adapter_cls is None:
        print(f"未知源：{source_name}，可选 {list(_REGISTRY)}")
        return 0
    adapter = adapter_cls()
    items = adapter.fetch()
    n = 0
    for it in items:
        try:
            oid = add_opinion(content=it["content"], source=it["source"])
            level = _classify_preview(it["content"])
            print(f"  [#{oid}] {it['source']} | {level} | {it['content'][:40]}")
            n += 1
        except Exception as e:  # noqa: BLE001
            print(f"  入库失败: {it['content'][:30]} -> {e}")
    print(f"共入库 {n} 条舆情")
    return n


def _classify_preview(content: str) -> str:
    # add_opinion 内部自动分级；这里仅预览分级结果（复用其规则）
    from data.db_opinion import _classify
    return _classify(content)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="mock")
    args = ap.parse_args()
    sys.exit(0 if ingest(args.source) > 0 else 1)
