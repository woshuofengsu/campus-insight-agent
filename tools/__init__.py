# tools/__init__.py
"""工具自动发现：扫 tools/ 目录，把带 @tool 装饰器的函数都收集起来。"""
import importlib
import pkgutil
from langchain.tools import BaseTool


def discover_tools() -> list[BaseTool]:
    """自动发现 tools/ 包里所有带 @tool 装饰器的函数。

    遍历包内所有模块，找出 @tool 装饰过的函数，
    返回列表，方便直接绑给 LangChain agent。
    """
    tools: list[BaseTool] = []

    package = importlib.import_module(__name__)
    package_path = package.__path__  # type: ignore

    for _, module_name, _ in pkgutil.iter_modules(package_path):
        if module_name == "__init__":
            continue
        full_name = f"{__name__}.{module_name}"
        module = importlib.import_module(full_name)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, BaseTool):
                tools.append(attr)

    return tools


def get_tool_names() -> list[str]:
    """返回发现到的工具名列表，给工具注册表用。"""
    return [t.name for t in discover_tools()]
