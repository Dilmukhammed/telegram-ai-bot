from tools.builtins import BUILTIN_TOOLS
from tools.builtins.google import GOOGLE_TOOLS
from tools.builtins.yandex import YANDEX_TOOLS
from tools.index import HybridToolIndex, create_tool_index
from tools.registry import ToolRegistry
from tools.runtime import ToolRuntime

_runtime: ToolRuntime | None = None


async def create_tool_runtime() -> ToolRuntime:
    registry = ToolRegistry()
    for tool in BUILTIN_TOOLS:
        registry.register(tool)
    for tool in GOOGLE_TOOLS:
        registry.register(tool)
    for tool in YANDEX_TOOLS:
        registry.register(tool)
    index = await create_tool_index(registry)
    return ToolRuntime(registry, index)


async def get_tool_runtime() -> ToolRuntime:
    global _runtime
    if _runtime is None:
        _runtime = await create_tool_runtime()
    return _runtime
