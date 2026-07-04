from tools.builtins.google.auth_tools import GOOGLE_AUTH_TOOLS
from tools.builtins.google.calendar_tools import GOOGLE_CALENDAR_TOOLS
from tools.builtins.google.drive_tools import GOOGLE_DRIVE_TOOLS
from tools.builtins.google.gmail_tools import GOOGLE_GMAIL_TOOLS
from tools.builtins.google.maps_tools import GOOGLE_MAPS_TOOLS
from tools.builtins.google.sheets_tools import GOOGLE_SHEETS_TOOLS
from tools.builtins.google.tasks_tools import GOOGLE_TASKS_TOOLS
from tools.schema import ToolSpec

GOOGLE_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_AUTH_TOOLS
    + GOOGLE_CALENDAR_TOOLS
    + GOOGLE_GMAIL_TOOLS
    + GOOGLE_DRIVE_TOOLS
    + GOOGLE_SHEETS_TOOLS
    + GOOGLE_TASKS_TOOLS
    + GOOGLE_MAPS_TOOLS
)
