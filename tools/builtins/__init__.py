from tools.builtins.echo import ECHO_TOOL
from tools.builtins.exa_fetch import EXA_WEB_FETCH
from tools.builtins.exa_search import EXA_WEB_SEARCH
from tools.builtins.telegram_send import TELEGRAM_SEND_FILE
from tools.builtins.skills_tools import SKILLS_TOOLS
from tools.builtins.workspace import WORKSPACE_TOOLS
from tools.builtins.google import GOOGLE_TOOLS
from tools.schema import ToolSpec

BUILTIN_TOOLS: tuple[ToolSpec, ...] = (
    ECHO_TOOL,
    EXA_WEB_SEARCH,
    EXA_WEB_FETCH,
    TELEGRAM_SEND_FILE,
    *SKILLS_TOOLS,
    *WORKSPACE_TOOLS,
)

__all__ = ("BUILTIN_TOOLS", "GOOGLE_TOOLS")
