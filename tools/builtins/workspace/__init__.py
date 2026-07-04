from tools.builtins.workspace.read_tools import WORKSPACE_READ_TOOLS
from tools.builtins.workspace.write_tools import WORKSPACE_WRITE_TOOLS
from tools.builtins.workspace.maintain_tools import WORKSPACE_MAINTAIN_TOOLS
from tools.schema import ToolSpec

WORKSPACE_TOOLS: tuple[ToolSpec, ...] = (
    WORKSPACE_READ_TOOLS + WORKSPACE_WRITE_TOOLS + WORKSPACE_MAINTAIN_TOOLS
)

__all__ = ("WORKSPACE_TOOLS",)
