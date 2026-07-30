# tools/__init__.py
"""Tool auto-discovery: scans the tools/ directory and collects all @tool-decorated functions."""
import importlib
import pkgutil
from langchain.tools import BaseTool


def discover_tools() -> list[BaseTool]:
    """Auto-discover all @tool-decorated functions in the tools/ package.

    Scans all modules in this package, finds functions decorated with @tool,
    and returns them as a list ready to bind to a LangChain agent.
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
    """Return list of discovered tool names for the tool registry."""
    return [t.name for t in discover_tools()]
