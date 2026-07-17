from __future__ import annotations

from tools.builtins.browser.advanced_tools import BROWSER_ADVANCED_TOOLS
from tools.builtins.browser.captcha_tools import BROWSER_CAPTCHA_TOOLS
from tools.builtins.browser.content_tools import BROWSER_CONTENT_TOOLS
from tools.builtins.browser.cookie_tools import BROWSER_COOKIE_TOOLS
from tools.builtins.browser.diagnostics_tools import BROWSER_DIAGNOSTICS_TOOLS
from tools.builtins.browser.file_tools import BROWSER_FILE_TOOLS
from tools.builtins.browser.frame_eval_tools import BROWSER_FRAME_EVAL_TOOLS
from tools.builtins.browser.inspect_tools import BROWSER_INSPECT_TOOLS
from tools.builtins.browser.interaction_tools import BROWSER_INTERACTION_TOOLS
from tools.builtins.browser.page_tools import BROWSER_PAGE_TOOLS
from tools.builtins.browser.power_tools import BROWSER_POWER_TOOLS
from tools.builtins.browser.profile_tools import BROWSER_PROFILE_TOOLS
from tools.builtins.browser.session_tools import BROWSER_SESSION_TOOLS
from tools.builtins.browser.state_tools import BROWSER_STATE_TOOLS
from tools.builtins.browser.tab_tools import BROWSER_TAB_TOOLS
from tools.schema import ToolSpec

BROWSER_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_PROFILE_TOOLS
    + BROWSER_SESSION_TOOLS
    + BROWSER_PAGE_TOOLS
    + BROWSER_TAB_TOOLS
    + BROWSER_INTERACTION_TOOLS
    + BROWSER_POWER_TOOLS
    + BROWSER_FILE_TOOLS
    + BROWSER_INSPECT_TOOLS
    + BROWSER_COOKIE_TOOLS
    + BROWSER_FRAME_EVAL_TOOLS
    + BROWSER_STATE_TOOLS
    + BROWSER_DIAGNOSTICS_TOOLS
    + BROWSER_ADVANCED_TOOLS
    + BROWSER_CONTENT_TOOLS
    + BROWSER_CAPTCHA_TOOLS
)

__all__ = ["BROWSER_TOOLS"]
