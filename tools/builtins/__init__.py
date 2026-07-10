from tools.builtins.chat_tools import CHAT_TOOLS
from tools.builtins.coach_reply import COACH_REPLY_TOOL
from tools.builtins.echo import ECHO_TOOL
from tools.builtins.exa_fetch import EXA_WEB_FETCH
from tools.builtins.exa_search import EXA_WEB_SEARCH
from tools.builtins.telegram_send import TELEGRAM_SEND_FILE
from tools.builtins.tool_results_get import TOOL_RESULTS_GET
from tools.builtins.skills_tools import SKILLS_TOOLS
from tools.builtins.workspace import WORKSPACE_TOOLS
from tools.builtins.pdf import PDF_TOOLS
from tools.schema import ToolSpec

BUILTIN_TOOLS: tuple[ToolSpec, ...] = (
    ECHO_TOOL,
    COACH_REPLY_TOOL,
    EXA_WEB_SEARCH,
    EXA_WEB_FETCH,
    TELEGRAM_SEND_FILE,
    TOOL_RESULTS_GET,
    *CHAT_TOOLS,
    *SKILLS_TOOLS,
    *WORKSPACE_TOOLS,
    *PDF_TOOLS,
)

__all__ = ("BUILTIN_TOOLS", "GOOGLE_TOOLS")
