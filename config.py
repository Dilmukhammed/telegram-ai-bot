import os
from dataclasses import dataclass

from dotenv import load_dotenv

from prompts import DEFAULT_SYSTEM_PROMPT

load_dotenv()

# --- Defaults (override via .env) ---

DEFAULT_OPENAI_BASE_URL = "http://localhost:20128/v1"
DEFAULT_OPENAI_MODEL = "ag/gemini-3.5-flash-low"
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_LLM_REQUEST_TIMEOUTS = (30.0, 60.0, 90.0)
REASONING_EFFORT_LEVELS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "auto", "none"}
)

DEFAULT_AGENT_MAX_TOOL_TURNS = 30
DEFAULT_AGENT_SUPERVISOR_ENABLED = True
DEFAULT_AGENT_SUPERVISOR_BONUS_TURNS = 10
DEFAULT_AGENT_SUPERVISOR_MAX_CYCLES = 2
DEFAULT_AGENT_SUPERVISOR_TRACE_MAX_CHARS = 12_000
DEFAULT_AGENT_SUPERVISOR_SOFT_TRIGGERS = True
DEFAULT_AGENT_SUPERVISOR_PERIODIC_EVERY = 0
DEFAULT_AGENT_SUPERVISOR_MAX_RETRIES = 1
DEFAULT_AGENT_SUPERVISOR_DEBUG_TRACE = False
DEFAULT_SKILLS_AUTO_LOAD_DISTINCT_TOOLS = 3
DEFAULT_SKILLS_COLLAPSE_IDLE_TURNS = 7
DEFAULT_BOT_TIMEZONE = "Asia/Tashkent"
DEFAULT_MESSAGE_GAP_MINUTES = 20
DEFAULT_CHAT_MAX_HISTORY = 20

DEFAULT_QUEUE_MAX_PENDING = 10
DEFAULT_MESSAGE_BURST_QUIET_MS = 150
DEFAULT_MESSAGE_BURST_MAX_WAIT_MS = 600
DEFAULT_TELEGRAM_SPLIT_MIN_CHARS = 3500

DEFAULT_TELEGRAM_RICH_LIMIT = 32768
DEFAULT_TELEGRAM_PLAIN_LIMIT = 4096
DEFAULT_DRAFT_UPDATE_INTERVAL = 0.35
DEFAULT_DRAFT_KEEPALIVE_INTERVAL = 20.0
DEFAULT_DRAFT_TYPING_INTERVAL = 5.0

DEFAULT_IMAGE_MAX_BYTES = 10 * 1024 * 1024

DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"

DEFAULT_EMBEDDING_MODEL = "fireworks/qwen3-embedding-8b"
DEFAULT_LOCAL_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOOL_EMBEDDING_PROVIDER = "api"

DEFAULT_TOOL_CACHE_MAX_TTL = 86400
DEFAULT_MAX_TOOL_CALLS_PER_USER_HOUR = 100

DEFAULT_GOOGLE_REDIRECT_URI = "http://localhost:1"
DEFAULT_GOOGLE_OAUTH_HOST = "127.0.0.1"
DEFAULT_GOOGLE_OAUTH_PORT = 8787
DEFAULT_GOOGLE_TOKEN_DB_PATH = "data/google_tokens.sqlite"
DEFAULT_GOOGLE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/calendar,"
    "https://www.googleapis.com/auth/gmail.modify,"
    "https://www.googleapis.com/auth/gmail.settings.basic,"
    "https://www.googleapis.com/auth/drive,"
    "https://www.googleapis.com/auth/spreadsheets,"
    "https://www.googleapis.com/auth/tasks"
)

DEFAULT_GOOGLE_MAPS_DEFAULT_LANGUAGE = "ru"
DEFAULT_GOOGLE_MAPS_DEFAULT_REGION = "uz"
DEFAULT_GOOGLE_MAPS_DEFAULT_LAT = 41.2995
DEFAULT_GOOGLE_MAPS_DEFAULT_LNG = 69.2401
DEFAULT_MAPS_RATE_LIMIT_GEOCODE = "30/60"
DEFAULT_MAPS_RATE_LIMIT_DEFAULT = "60/3600"
DEFAULT_MAPS_RATE_LIMIT_PLACES = "15/60"
DEFAULT_MAPS_RATE_LIMIT_DETAILS = "20/60"
DEFAULT_MAPS_RATE_LIMIT_ROUTES = "10/60"
DEFAULT_MAPS_RATE_LIMIT_STATIC = "5/60"
DEFAULT_MAPS_TRANSIT_LINK_PROVIDER = "yandex"

DEFAULT_GOOGLE_OAUTH_CLIENT_TYPE = "installed"
DEFAULT_GOOGLE_OAUTH_BIND_HOST = "127.0.0.1"
DEFAULT_GOOGLE_OAUTH_PUBLIC_BIND_HOST = "0.0.0.0"
MAPS_TRANSIT_LINK_PROVIDERS = frozenset({"google", "yandex"})

# --- Byte size units ---
_TIB = 1024 * 1024 * 1024 * 1024
_MB = 1024 * 1024

# --- Google → server download limits (Google API documented caps) ---
# Drive blob (files.get alt=media): max file size stored in Drive.
GOOGLE_DRIVE_MAX_BLOB_BYTES = 5 * _TIB
# Drive export (files.export): exported byte content hard cap.
GOOGLE_DRIVE_MAX_EXPORT_BYTES = 10 * _MB
# Gmail attachment (messages.attachments.get).
GOOGLE_GMAIL_MAX_ATTACHMENT_BYTES = 25 * _MB

# --- Telegram Bot API outbound file caps (send_document / photo / audio) ---
TELEGRAM_BOT_MAX_DOCUMENT_BYTES = 50 * _MB
TELEGRAM_BOT_MAX_PHOTO_BYTES = 10 * _MB
TELEGRAM_BOT_MAX_AUDIO_BYTES = 50 * _MB

# --- Env-overridable defaults (.env keys in get_settings) ---
DEFAULT_GMAIL_MAX_BODY_CHARS = 4000
DEFAULT_GMAIL_MAX_ATTACHMENT_BYTES = GOOGLE_GMAIL_MAX_ATTACHMENT_BYTES
DEFAULT_GMAIL_DEFAULT_MAX_RESULTS = 10
DEFAULT_GMAIL_RATE_LIMIT_READ = "60/60"
DEFAULT_GMAIL_RATE_LIMIT_WRITE = "30/60"

DEFAULT_DRIVE_MAX_DOWNLOAD_BYTES = GOOGLE_DRIVE_MAX_BLOB_BYTES
DEFAULT_DRIVE_MAX_EXPORT_BYTES = GOOGLE_DRIVE_MAX_EXPORT_BYTES
DEFAULT_DRIVE_MAX_UPLOAD_BYTES = 10 * _MB
DEFAULT_DRIVE_MAX_EXPORT_CHARS = 50_000
DEFAULT_DRIVE_DEFAULT_MAX_RESULTS = 10
DEFAULT_DRIVE_RATE_LIMIT_READ = "60/60"
DEFAULT_DRIVE_RATE_LIMIT_WRITE = "30/60"

DEFAULT_RUN_FILE_MAX_BYTES = GOOGLE_DRIVE_MAX_BLOB_BYTES

DEFAULT_WORKSPACE_ROOT = "data/workspaces"
DEFAULT_WORKSPACE_MAX_BYTES_PER_USER = 500 * _MB
DEFAULT_WORKSPACE_MAX_FILE_BYTES = 50 * _MB
DEFAULT_WORKSPACE_MAX_FILES_PER_USER = 1000
DEFAULT_WORKSPACE_READ_PREVIEW_LINES = 30
DEFAULT_WORKSPACE_READ_PREVIEW_LINES_MAX = 50
DEFAULT_WORKSPACE_READ_LINES_MAX = 500
DEFAULT_WORKSPACE_UPLOAD_MAX_BYTES = 20 * _MB
DEFAULT_WORKSPACE_RATE_LIMIT_READ = "60/60"
DEFAULT_WORKSPACE_RATE_LIMIT_WRITE = "30/60"
DEFAULT_WORKSPACE_RATE_LIMIT_DELETE = "10/60"
DEFAULT_WORKSPACE_GREP_MAX_MATCHES = 200
DEFAULT_WORKSPACE_GREP_MAX_FILES = 100
DEFAULT_WORKSPACE_UNZIP_MAX_FILES = 500
DEFAULT_WORKSPACE_UNZIP_MAX_BYTES = 200 * _MB

DEFAULT_TELEGRAM_MAX_DOCUMENT_BYTES = TELEGRAM_BOT_MAX_DOCUMENT_BYTES
DEFAULT_TELEGRAM_MAX_PHOTO_BYTES = TELEGRAM_BOT_MAX_PHOTO_BYTES
DEFAULT_TELEGRAM_MAX_AUDIO_BYTES = TELEGRAM_BOT_MAX_AUDIO_BYTES

DEFAULT_SHEETS_MAX_CELLS = 10_000
DEFAULT_SHEETS_RATE_LIMIT_READ = "60/60"
DEFAULT_SHEETS_RATE_LIMIT_WRITE = "30/60"


def format_byte_size(num: int) -> str:
    if num >= _MB:
        mb = num / _MB
        return f"{int(mb)} MB" if mb == int(mb) else f"{mb:.1f} MB"
    if num >= 1024:
        return f"{num // 1024} KB"
    return f"{num} bytes"


def google_limit_label(source: str) -> str:
    if source == "drive_blob":
        return "Google Drive max file size (5 TiB)"
    if source == "drive_export":
        return f"Google Drive files.export limit ({format_byte_size(GOOGLE_DRIVE_MAX_EXPORT_BYTES)})"
    if source == "gmail_attachment":
        return f"Gmail attachment limit ({format_byte_size(GOOGLE_GMAIL_MAX_ATTACHMENT_BYTES)})"
    return source


def telegram_limit_label(kind: str) -> str:
    if kind == "photo":
        return f"Telegram photo limit ({format_byte_size(TELEGRAM_BOT_MAX_PHOTO_BYTES)})"
    if kind == "audio":
        return f"Telegram audio limit ({format_byte_size(TELEGRAM_BOT_MAX_AUDIO_BYTES)})"
    return f"Telegram document limit ({format_byte_size(TELEGRAM_BOT_MAX_DOCUMENT_BYTES)})"


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _is_local_base_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://127.0.0.1") or lowered.startswith("http://localhost")


def _str_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _optional_str_env(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    return raw or None


def _reasoning_effort_env(name: str, default: str | None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        value = (default or "").strip().lower()
    else:
        value = raw.strip().lower()
    if not value:
        return None
    if value not in REASONING_EFFORT_LEVELS:
        allowed = ", ".join(sorted(REASONING_EFFORT_LEVELS))
        raise RuntimeError(f"{name} must be one of: {allowed}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _optional_int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _float_tuple_env(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return default
    values = tuple(float(part) for part in parts)
    if any(value <= 0 for value in values):
        raise RuntimeError(f"{name} values must be positive numbers")
    return values


def _parse_rate_limit(raw: str | None) -> tuple[int, int] | None:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    for separator in ("/", ":", ","):
        if separator in text:
            left, right = text.split(separator, 1)
            return int(left.strip()), int(right.strip())
    raise ValueError(f"Invalid rate limit format: {raw!r}. Use max/window, e.g. 10/60")


def _parse_admin_user_ids(raw: str) -> frozenset[int]:
    if not raw:
        return frozenset()
    return frozenset(int(part.strip()) for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    # Telegram bot
    telegram_bot_token: str
    admin_user_ids: frozenset[int]

    # LLM / agent
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    reasoning_effort: str | None
    llm_request_timeouts: tuple[float, ...]
    system_prompt: str
    agent_max_tool_turns: int
    agent_supervisor_enabled: bool
    agent_supervisor_bonus_turns: int
    agent_supervisor_max_cycles: int
    agent_supervisor_trace_max_chars: int
    agent_supervisor_soft_triggers: bool
    agent_supervisor_periodic_every: int
    agent_supervisor_max_retries: int
    agent_supervisor_debug_trace: bool
    skills_auto_load_distinct_tools: int
    skills_collapse_idle_turns: int

    # Runtime context
    bot_timezone: str

    # Chat history & gaps
    chat_max_history: int
    message_gap_minutes: int

    # Message queue & burst grouping
    queue_max_pending: int
    message_burst_quiet_ms: int
    message_burst_max_wait_ms: int
    telegram_split_min_chars: int

    # Telegram message limits
    telegram_rich_limit: int
    telegram_plain_limit: int
    draft_update_interval: float
    draft_keepalive_interval: float
    draft_typing_interval: float

    # Vision
    image_max_bytes: int

    # Voice transcription (Groq)
    groq_api_key: str
    groq_base_url: str
    groq_transcription_model: str
    groq_transcription_language: str | None

    # Exa
    exa_api_key: str
    exa_search_cache_ttl: int | None
    exa_fetch_cache_ttl: int | None
    rate_limit_exa_search: tuple[int, int] | None
    rate_limit_exa_fetch: tuple[int, int] | None

    # Tool embeddings
    embedding_base_url: str
    embedding_api_key: str
    openai_embedding_model: str
    local_embedding_model: str
    tool_embedding_provider: str

    # Tool cache & rate limits
    tool_cache_max_ttl: int
    max_tool_calls_per_user_hour: int

    # Google OAuth / Calendar
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_oauth_host: str
    google_oauth_port: int
    google_token_db_path: str
    google_oauth_scopes: tuple[str, ...]
    google_oauth_client_type: str
    google_public_base_url: str | None

    # Google Maps Platform (API key, not user OAuth)
    google_maps_api_key: str | None
    google_maps_default_language: str
    google_maps_default_region: str
    google_maps_default_lat: float
    google_maps_default_lng: float
    rate_limit_maps_geocode: tuple[int, int] | None
    rate_limit_maps_default: tuple[int, int] | None
    rate_limit_maps_places: tuple[int, int] | None
    rate_limit_maps_details: tuple[int, int] | None
    rate_limit_maps_routes: tuple[int, int] | None
    rate_limit_maps_static: tuple[int, int] | None
    maps_transit_link_provider: str

    # Google Gmail (user OAuth)
    gmail_max_body_chars: int
    gmail_max_attachment_bytes: int
    gmail_default_max_results: int
    rate_limit_gmail_read: tuple[int, int] | None
    rate_limit_gmail_write: tuple[int, int] | None

    # Google Drive (user OAuth)
    drive_max_download_bytes: int
    drive_max_export_bytes: int
    drive_max_upload_bytes: int
    drive_max_export_chars: int
    drive_default_max_results: int
    rate_limit_drive_read: tuple[int, int] | None
    rate_limit_drive_write: tuple[int, int] | None

    # Google Sheets (user OAuth)
    sheets_max_cells: int
    rate_limit_sheets_read: tuple[int, int] | None
    rate_limit_sheets_write: tuple[int, int] | None

    # Run-scoped files & Telegram delivery
    run_file_max_bytes: int
    telegram_max_document_bytes: int
    telegram_max_photo_bytes: int
    telegram_max_audio_bytes: int

    # Agent workspace (per-user sandbox)
    workspace_root: str
    workspace_max_bytes_per_user: int
    workspace_max_file_bytes: int
    workspace_max_files_per_user: int
    workspace_read_preview_lines: int
    workspace_read_preview_lines_max: int
    workspace_read_lines_max: int
    workspace_upload_max_bytes: int
    workspace_grep_max_matches: int
    workspace_grep_max_files: int
    workspace_unzip_max_files: int
    workspace_unzip_max_bytes: int
    rate_limit_workspace_read: tuple[int, int] | None
    rate_limit_workspace_write: tuple[int, int] | None
    rate_limit_workspace_delete: tuple[int, int] | None


def _maps_transit_link_provider_env(name: str, default: str) -> str:
    value = _str_env(name, default).lower()
    if value not in MAPS_TRANSIT_LINK_PROVIDERS:
        allowed = ", ".join(sorted(MAPS_TRANSIT_LINK_PROVIDERS))
        raise RuntimeError(f"{name} must be one of: {allowed}")
    return value


def get_settings(*, require_telegram_token: bool = False) -> Settings:
    telegram_bot_token = _str_env("TELEGRAM_BOT_TOKEN")
    if require_telegram_token and not telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    openai_api_key = _str_env("OPENAI_API_KEY")
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    openai_base_url = _str_env("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
    google_public_base_url = _optional_str_env("GOOGLE_PUBLIC_BASE_URL")
    if google_public_base_url:
        google_public_base_url = _normalize_base_url(google_public_base_url)
    if google_public_base_url:
        google_redirect_uri = f"{google_public_base_url}/oauth/google/callback"
        google_oauth_host = _str_env("GOOGLE_OAUTH_HOST", DEFAULT_GOOGLE_OAUTH_PUBLIC_BIND_HOST)
    else:
        google_redirect_uri = _str_env("GOOGLE_REDIRECT_URI", DEFAULT_GOOGLE_REDIRECT_URI)
        google_oauth_host = _str_env("GOOGLE_OAUTH_HOST", DEFAULT_GOOGLE_OAUTH_BIND_HOST)

    return Settings(
        telegram_bot_token=telegram_bot_token,
        admin_user_ids=_parse_admin_user_ids(_str_env("ADMIN_USER_IDS")),
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        openai_model=_str_env("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        reasoning_effort=_reasoning_effort_env("REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
        llm_request_timeouts=_float_tuple_env(
            "LLM_REQUEST_TIMEOUTS",
            DEFAULT_LLM_REQUEST_TIMEOUTS,
        ),
        system_prompt=_str_env("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        agent_max_tool_turns=_int_env("AGENT_MAX_TOOL_TURNS", DEFAULT_AGENT_MAX_TOOL_TURNS),
        agent_supervisor_enabled=_bool_env(
            "AGENT_SUPERVISOR_ENABLED",
            DEFAULT_AGENT_SUPERVISOR_ENABLED,
        ),
        agent_supervisor_bonus_turns=_int_env(
            "AGENT_SUPERVISOR_BONUS_TURNS",
            DEFAULT_AGENT_SUPERVISOR_BONUS_TURNS,
        ),
        agent_supervisor_max_cycles=_int_env(
            "AGENT_SUPERVISOR_MAX_CYCLES",
            DEFAULT_AGENT_SUPERVISOR_MAX_CYCLES,
        ),
        agent_supervisor_trace_max_chars=_int_env(
            "AGENT_SUPERVISOR_TRACE_MAX_CHARS",
            DEFAULT_AGENT_SUPERVISOR_TRACE_MAX_CHARS,
        ),
        agent_supervisor_soft_triggers=_bool_env(
            "AGENT_SUPERVISOR_SOFT_TRIGGERS",
            DEFAULT_AGENT_SUPERVISOR_SOFT_TRIGGERS,
        ),
        agent_supervisor_periodic_every=_int_env(
            "AGENT_SUPERVISOR_PERIODIC_EVERY",
            DEFAULT_AGENT_SUPERVISOR_PERIODIC_EVERY,
        ),
        agent_supervisor_max_retries=_int_env(
            "AGENT_SUPERVISOR_MAX_RETRIES",
            DEFAULT_AGENT_SUPERVISOR_MAX_RETRIES,
        ),
        agent_supervisor_debug_trace=_bool_env(
            "AGENT_SUPERVISOR_DEBUG_TRACE",
            DEFAULT_AGENT_SUPERVISOR_DEBUG_TRACE,
        ),
        skills_auto_load_distinct_tools=_int_env(
            "SKILLS_AUTO_LOAD_DISTINCT_TOOLS",
            DEFAULT_SKILLS_AUTO_LOAD_DISTINCT_TOOLS,
        ),
        skills_collapse_idle_turns=_int_env(
            "SKILLS_COLLAPSE_IDLE_TURNS",
            DEFAULT_SKILLS_COLLAPSE_IDLE_TURNS,
        ),
        bot_timezone=_str_env("BOT_TIMEZONE", DEFAULT_BOT_TIMEZONE) or "UTC",
        chat_max_history=_int_env("CHAT_MAX_HISTORY", DEFAULT_CHAT_MAX_HISTORY),
        message_gap_minutes=_int_env("MESSAGE_GAP_MINUTES", DEFAULT_MESSAGE_GAP_MINUTES),
        queue_max_pending=_int_env("QUEUE_MAX_PENDING", DEFAULT_QUEUE_MAX_PENDING),
        message_burst_quiet_ms=_int_env("MESSAGE_BURST_QUIET_MS", DEFAULT_MESSAGE_BURST_QUIET_MS),
        message_burst_max_wait_ms=_int_env(
            "MESSAGE_BURST_MAX_WAIT_MS",
            DEFAULT_MESSAGE_BURST_MAX_WAIT_MS,
        ),
        telegram_split_min_chars=_int_env(
            "TELEGRAM_SPLIT_MIN_CHARS",
            DEFAULT_TELEGRAM_SPLIT_MIN_CHARS,
        ),
        telegram_rich_limit=_int_env("TELEGRAM_RICH_LIMIT", DEFAULT_TELEGRAM_RICH_LIMIT),
        telegram_plain_limit=_int_env("TELEGRAM_PLAIN_LIMIT", DEFAULT_TELEGRAM_PLAIN_LIMIT),
        draft_update_interval=_float_env("DRAFT_UPDATE_INTERVAL", DEFAULT_DRAFT_UPDATE_INTERVAL),
        draft_keepalive_interval=_float_env(
            "DRAFT_KEEPALIVE_INTERVAL",
            DEFAULT_DRAFT_KEEPALIVE_INTERVAL,
        ),
        draft_typing_interval=_float_env(
            "DRAFT_TYPING_INTERVAL",
            DEFAULT_DRAFT_TYPING_INTERVAL,
        ),
        image_max_bytes=_int_env("IMAGE_MAX_BYTES", DEFAULT_IMAGE_MAX_BYTES),
        groq_api_key=_str_env("GROQ_API_KEY"),
        groq_base_url=_str_env("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL),
        groq_transcription_model=_str_env(
            "GROQ_TRANSCRIPTION_MODEL",
            DEFAULT_GROQ_TRANSCRIPTION_MODEL,
        ),
        groq_transcription_language=_optional_str_env("GROQ_TRANSCRIPTION_LANGUAGE"),
        exa_api_key=_str_env("EXA_API_KEY"),
        exa_search_cache_ttl=_optional_int_env("EXA_SEARCH_CACHE_TTL"),
        exa_fetch_cache_ttl=_optional_int_env("EXA_FETCH_CACHE_TTL"),
        rate_limit_exa_search=_parse_rate_limit(_optional_str_env("RATE_LIMIT_EXA_SEARCH")),
        rate_limit_exa_fetch=_parse_rate_limit(_optional_str_env("RATE_LIMIT_EXA_FETCH")),
        embedding_base_url=_str_env("EMBEDDING_BASE_URL", openai_base_url),
        embedding_api_key=_str_env("EMBEDDING_API_KEY", openai_api_key),
        openai_embedding_model=_str_env("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        local_embedding_model=_str_env("LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL),
        tool_embedding_provider=_str_env(
            "TOOL_EMBEDDING_PROVIDER",
            DEFAULT_TOOL_EMBEDDING_PROVIDER,
        ).lower(),
        tool_cache_max_ttl=_int_env("TOOL_CACHE_MAX_TTL", DEFAULT_TOOL_CACHE_MAX_TTL),
        max_tool_calls_per_user_hour=_int_env(
            "MAX_TOOL_CALLS_PER_USER_HOUR",
            DEFAULT_MAX_TOOL_CALLS_PER_USER_HOUR,
        ),
        google_client_id=_str_env("GOOGLE_CLIENT_ID"),
        google_client_secret=_str_env("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=google_redirect_uri,
        google_oauth_host=google_oauth_host,
        google_oauth_port=_int_env("GOOGLE_OAUTH_PORT", DEFAULT_GOOGLE_OAUTH_PORT),
        google_token_db_path=_str_env("GOOGLE_TOKEN_DB_PATH", DEFAULT_GOOGLE_TOKEN_DB_PATH),
        google_oauth_scopes=tuple(
            scope.strip()
            for scope in _str_env("GOOGLE_OAUTH_SCOPES", DEFAULT_GOOGLE_OAUTH_SCOPES).split(",")
            if scope.strip()
        ),
        google_oauth_client_type=(
            "web"
            if google_public_base_url
            else _str_env("GOOGLE_OAUTH_CLIENT_TYPE", DEFAULT_GOOGLE_OAUTH_CLIENT_TYPE).lower()
        ),
        google_public_base_url=google_public_base_url,
        google_maps_api_key=_optional_str_env("GOOGLE_MAPS_API_KEY"),
        google_maps_default_language=_str_env(
            "GOOGLE_MAPS_DEFAULT_LANGUAGE",
            DEFAULT_GOOGLE_MAPS_DEFAULT_LANGUAGE,
        ),
        google_maps_default_region=_str_env(
            "GOOGLE_MAPS_DEFAULT_REGION",
            DEFAULT_GOOGLE_MAPS_DEFAULT_REGION,
        ),
        google_maps_default_lat=float(
            _str_env("GOOGLE_MAPS_DEFAULT_LAT", str(DEFAULT_GOOGLE_MAPS_DEFAULT_LAT))
        ),
        google_maps_default_lng=float(
            _str_env("GOOGLE_MAPS_DEFAULT_LNG", str(DEFAULT_GOOGLE_MAPS_DEFAULT_LNG))
        ),
        rate_limit_maps_geocode=_parse_rate_limit(
            _optional_str_env("MAPS_RATE_LIMIT_GEOCODE") or DEFAULT_MAPS_RATE_LIMIT_GEOCODE
        ),
        rate_limit_maps_default=_parse_rate_limit(
            _optional_str_env("MAPS_RATE_LIMIT_DEFAULT") or DEFAULT_MAPS_RATE_LIMIT_DEFAULT
        ),
        rate_limit_maps_places=_parse_rate_limit(
            _optional_str_env("MAPS_RATE_LIMIT_PLACES") or DEFAULT_MAPS_RATE_LIMIT_PLACES
        ),
        rate_limit_maps_details=_parse_rate_limit(
            _optional_str_env("MAPS_RATE_LIMIT_DETAILS") or DEFAULT_MAPS_RATE_LIMIT_DETAILS
        ),
        rate_limit_maps_routes=_parse_rate_limit(
            _optional_str_env("MAPS_RATE_LIMIT_ROUTES") or DEFAULT_MAPS_RATE_LIMIT_ROUTES
        ),
        rate_limit_maps_static=_parse_rate_limit(
            _optional_str_env("MAPS_RATE_LIMIT_STATIC") or DEFAULT_MAPS_RATE_LIMIT_STATIC
        ),
        maps_transit_link_provider=_maps_transit_link_provider_env(
            "MAPS_TRANSIT_LINK_PROVIDER",
            DEFAULT_MAPS_TRANSIT_LINK_PROVIDER,
        ),
        gmail_max_body_chars=_int_env("GMAIL_MAX_BODY_CHARS", DEFAULT_GMAIL_MAX_BODY_CHARS),
        gmail_max_attachment_bytes=_int_env(
            "GMAIL_MAX_ATTACHMENT_BYTES",
            DEFAULT_GMAIL_MAX_ATTACHMENT_BYTES,
        ),
        gmail_default_max_results=_int_env(
            "GMAIL_DEFAULT_MAX_RESULTS",
            DEFAULT_GMAIL_DEFAULT_MAX_RESULTS,
        ),
        rate_limit_gmail_read=_parse_rate_limit(
            _optional_str_env("GMAIL_RATE_LIMIT_READ") or DEFAULT_GMAIL_RATE_LIMIT_READ
        ),
        rate_limit_gmail_write=_parse_rate_limit(
            _optional_str_env("GMAIL_RATE_LIMIT_WRITE") or DEFAULT_GMAIL_RATE_LIMIT_WRITE
        ),
        drive_max_download_bytes=_int_env(
            "DRIVE_MAX_DOWNLOAD_BYTES",
            DEFAULT_DRIVE_MAX_DOWNLOAD_BYTES,
        ),
        drive_max_export_bytes=_int_env(
            "DRIVE_MAX_EXPORT_BYTES",
            DEFAULT_DRIVE_MAX_EXPORT_BYTES,
        ),
        drive_max_upload_bytes=_int_env(
            "DRIVE_MAX_UPLOAD_BYTES",
            DEFAULT_DRIVE_MAX_UPLOAD_BYTES,
        ),
        drive_max_export_chars=_int_env("DRIVE_MAX_EXPORT_CHARS", DEFAULT_DRIVE_MAX_EXPORT_CHARS),
        drive_default_max_results=_int_env(
            "DRIVE_DEFAULT_MAX_RESULTS",
            DEFAULT_DRIVE_DEFAULT_MAX_RESULTS,
        ),
        rate_limit_drive_read=_parse_rate_limit(
            _optional_str_env("DRIVE_RATE_LIMIT_READ") or DEFAULT_DRIVE_RATE_LIMIT_READ
        ),
        rate_limit_drive_write=_parse_rate_limit(
            _optional_str_env("DRIVE_RATE_LIMIT_WRITE") or DEFAULT_DRIVE_RATE_LIMIT_WRITE
        ),
        sheets_max_cells=_int_env("SHEETS_MAX_CELLS", DEFAULT_SHEETS_MAX_CELLS),
        rate_limit_sheets_read=_parse_rate_limit(
            _optional_str_env("SHEETS_RATE_LIMIT_READ") or DEFAULT_SHEETS_RATE_LIMIT_READ
        ),
        rate_limit_sheets_write=_parse_rate_limit(
            _optional_str_env("SHEETS_RATE_LIMIT_WRITE") or DEFAULT_SHEETS_RATE_LIMIT_WRITE
        ),
        run_file_max_bytes=_int_env("RUN_FILE_MAX_BYTES", DEFAULT_RUN_FILE_MAX_BYTES),
        telegram_max_document_bytes=_int_env(
            "TELEGRAM_MAX_DOCUMENT_BYTES",
            DEFAULT_TELEGRAM_MAX_DOCUMENT_BYTES,
        ),
        telegram_max_photo_bytes=_int_env(
            "TELEGRAM_MAX_PHOTO_BYTES",
            DEFAULT_TELEGRAM_MAX_PHOTO_BYTES,
        ),
        telegram_max_audio_bytes=_int_env(
            "TELEGRAM_MAX_AUDIO_BYTES",
            DEFAULT_TELEGRAM_MAX_AUDIO_BYTES,
        ),
        workspace_root=_str_env("WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT),
        workspace_max_bytes_per_user=_int_env(
            "WORKSPACE_MAX_BYTES",
            DEFAULT_WORKSPACE_MAX_BYTES_PER_USER,
        ),
        workspace_max_file_bytes=_int_env(
            "WORKSPACE_MAX_FILE_BYTES",
            DEFAULT_WORKSPACE_MAX_FILE_BYTES,
        ),
        workspace_max_files_per_user=_int_env(
            "WORKSPACE_MAX_FILES",
            DEFAULT_WORKSPACE_MAX_FILES_PER_USER,
        ),
        workspace_read_preview_lines=_int_env(
            "WORKSPACE_READ_PREVIEW_LINES",
            DEFAULT_WORKSPACE_READ_PREVIEW_LINES,
        ),
        workspace_read_preview_lines_max=_int_env(
            "WORKSPACE_READ_PREVIEW_LINES_MAX",
            DEFAULT_WORKSPACE_READ_PREVIEW_LINES_MAX,
        ),
        workspace_read_lines_max=_int_env(
            "WORKSPACE_READ_LINES_MAX",
            DEFAULT_WORKSPACE_READ_LINES_MAX,
        ),
        workspace_upload_max_bytes=_int_env(
            "WORKSPACE_UPLOAD_MAX_BYTES",
            DEFAULT_WORKSPACE_UPLOAD_MAX_BYTES,
        ),
        workspace_grep_max_matches=_int_env(
            "WORKSPACE_GREP_MAX_MATCHES",
            DEFAULT_WORKSPACE_GREP_MAX_MATCHES,
        ),
        workspace_grep_max_files=_int_env(
            "WORKSPACE_GREP_MAX_FILES",
            DEFAULT_WORKSPACE_GREP_MAX_FILES,
        ),
        workspace_unzip_max_files=_int_env(
            "WORKSPACE_UNZIP_MAX_FILES",
            DEFAULT_WORKSPACE_UNZIP_MAX_FILES,
        ),
        workspace_unzip_max_bytes=_int_env(
            "WORKSPACE_UNZIP_MAX_BYTES",
            DEFAULT_WORKSPACE_UNZIP_MAX_BYTES,
        ),
        rate_limit_workspace_read=_parse_rate_limit(
            _optional_str_env("WORKSPACE_RATE_LIMIT_READ") or DEFAULT_WORKSPACE_RATE_LIMIT_READ
        ),
        rate_limit_workspace_write=_parse_rate_limit(
            _optional_str_env("WORKSPACE_RATE_LIMIT_WRITE") or DEFAULT_WORKSPACE_RATE_LIMIT_WRITE
        ),
        rate_limit_workspace_delete=_parse_rate_limit(
            _optional_str_env("WORKSPACE_RATE_LIMIT_DELETE") or DEFAULT_WORKSPACE_RATE_LIMIT_DELETE
        ),
    )


def google_oauth_manual_mode() -> bool:
    """Paste callback URL flow (Desktop client + localhost redirect). No HTTP server needed."""
    return not get_settings().google_public_base_url


def google_oauth_configured() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def google_maps_configured() -> bool:
    return bool(get_settings().google_maps_api_key)


def google_oauth_remote_ready() -> bool:
    settings = get_settings()
    if not settings.google_public_base_url:
        return False
    return settings.google_public_base_url.startswith("https://") and not _is_local_base_url(
        settings.google_public_base_url
    )
