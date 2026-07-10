import os
from dataclasses import dataclass

from dotenv import load_dotenv

from prompts import DEFAULT_SYSTEM_PROMPT

# Local `.env` wins by default so a stale shell OPENAI_API_KEY does not override it.
# In production (Docker/K8s), set DOTENV_OVERRIDE=0 so orchestrator secrets win.
load_dotenv(override=os.getenv("DOTENV_OVERRIDE", "1") != "0")

# --- Defaults (override via .env) ---

DEFAULT_OPENAI_BASE_URL = "https://api.fireworks.ai/inference/v1"
DEFAULT_OPENAI_MODEL = "accounts/fireworks/models/glm-5p2"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_LLM_CONTEXT_WINDOW_TOKENS = 1_000_000
DEFAULT_LLM_REQUEST_TIMEOUTS = (30.0, 60.0, 90.0)
REASONING_EFFORT_LEVELS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "auto", "none"}
)

DEFAULT_AGENT_MAX_TOOL_TURNS = 200
DEFAULT_AGENT_SUPERVISOR_ENABLED = True
DEFAULT_AGENT_SUPERVISOR_BONUS_TURNS = 60
DEFAULT_AGENT_SUPERVISOR_MAX_CYCLES = 20
DEFAULT_AGENT_SUPERVISOR_TRACE_MAX_CHARS = 12_000
DEFAULT_AGENT_SUPERVISOR_SOFT_TRIGGERS = True
DEFAULT_AGENT_SUPERVISOR_PERIODIC_EVERY = 0
DEFAULT_AGENT_SUPERVISOR_MAX_RETRIES = 1
DEFAULT_AGENT_SUPERVISOR_DEBUG_TRACE = False
DEFAULT_SKILLS_AUTO_LOAD_DISTINCT_TOOLS = 3
DEFAULT_SKILLS_COLLAPSE_IDLE_TURNS = 7
DEFAULT_BOT_TIMEZONE = "Asia/Tashkent"
DEFAULT_MESSAGE_GAP_MINUTES = 20
DEFAULT_CHAT_MAX_HISTORY = 50
DEFAULT_CHAT_MIGRATE_V1_SOURCE_PATH = "data/chat_history.sqlite"
DEFAULT_CHAT_DB_PATH = "data/chat.sqlite"
DEFAULT_CHAT_SESSION_SUMMARY_ON_ARCHIVE = True
DEFAULT_CHAT_SESSION_SUMMARY_MAX_INPUT_CHARS = 80_000
DEFAULT_CHAT_SESSION_SUMMARY_PER_TURN_MAX_CHARS = 12_000
DEFAULT_CHAT_PERIOD_SUMMARY_ENABLED = True
DEFAULT_CHAT_PERIOD_SUMMARY_ON_SESSION_ARCHIVE = True
DEFAULT_CHAT_PERIOD_SUMMARY_MAX_INPUT_CHARS = 120_000
DEFAULT_CHAT_PERIOD_SUMMARY_BOUNDARY_ENABLED = True
DEFAULT_CHAT_PERIOD_SUMMARY_BOUNDARY_POLL_SECONDS = 60
DEFAULT_CHAT_MIGRATE_V1_ON_STARTUP = True
DEFAULT_CHAT_MIGRATE_V1_TARGET = "active"
DEFAULT_CHAT_MIGRATE_V1_BACKUP = True
DEFAULT_CHAT_SEARCH_CHUNK_CHARS = 800
DEFAULT_CHAT_SEARCH_CHUNK_OVERLAP = 100
DEFAULT_CHAT_SEARCH_TOP_K = 5
DEFAULT_CHAT_SEARCH_KEYWORD_CANDIDATES = 80
DEFAULT_CHAT_SEARCH_VECTOR_SCAN_LIMIT = 2000
DEFAULT_CHAT_SEARCH_MAX_PER_SESSION = 5
DEFAULT_CHAT_INDEX_ON_STARTUP = True
DEFAULT_CHAT_INDEX_PAYLOAD_MAX_CHARS = 4000
DEFAULT_INSTANCE_LOCK_PATH = "data/bot.instance.lock"
DEFAULT_INSTANCE_LOCK_ENABLED = True
DEFAULT_ACCESS_APPROVAL_ENABLED = True
DEFAULT_ACCESS_DB_PATH = "data/access.sqlite"

DEFAULT_MEMORY_INGEST_ENABLED = False
DEFAULT_MEMORY_DB_PATH = "data/memory.sqlite"
DEFAULT_MEMORY_WORKER_ENABLED = False
DEFAULT_MEMORY_WORKER_CONCURRENCY = 2
DEFAULT_MEMORY_WORKER_POLL_SECONDS = 1.0
DEFAULT_MEMORY_JOB_LEASE_SECONDS = 300
DEFAULT_MEMORY_JOB_MAX_ATTEMPTS = 5
DEFAULT_MEMORY_JOB_RETRY_BASE_SECONDS = 5.0
DEFAULT_MEMORY_JOB_RETRY_MAX_SECONDS = 900.0
DEFAULT_MEMORY_JOB_CLAIM_BATCH_SIZE = 10
DEFAULT_MEMORY_INGEST_QUEUE_MAXSIZE = 1000
DEFAULT_MEMORY_INGEST_SCAN_INTERVAL_SECONDS = 30.0
DEFAULT_MEMORY_INGEST_SCAN_BATCH_SIZE = 100
DEFAULT_MEMORY_INGEST_FAILURE_MAX_ATTEMPTS = 10
DEFAULT_MEMORY_INGEST_RETRY_BASE_SECONDS = 5.0
DEFAULT_MEMORY_INGEST_RETRY_MAX_SECONDS = 900.0
DEFAULT_MEMORY_TEXT_SEGMENT_CHARS = 4000
DEFAULT_MEMORY_TEXT_SEGMENT_OVERLAP = 200
DEFAULT_MEMORY_TOOL_RECONCILE_BATCH_SIZE = 100
DEFAULT_MEMORY_INGEST_SHUTDOWN_GRACE_SECONDS = 10.0
DEFAULT_MEMORY_EXTRACTION_ENABLED = False
DEFAULT_MEMORY_EXTRACTION_MODEL_PROFILE = "summarize"
DEFAULT_MEMORY_EXTRACTION_MAX_TOKENS = 4096

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
DEFAULT_MAX_TOOL_CALLS_PER_USER_HOUR = 200

DEFAULT_GOOGLE_REDIRECT_URI = "http://localhost:1"
DEFAULT_GOOGLE_OAUTH_HOST = "127.0.0.1"
DEFAULT_GOOGLE_OAUTH_PORT = 8787
DEFAULT_GOOGLE_TOKEN_DB_PATH = "data/google_tokens.sqlite"
DEFAULT_GOOGLE_CLOUD_TEST_USERS_URL = ""
DEFAULT_GOOGLE_CLOUD_PROJECT_ID = ""
DEFAULT_GOOGLE_TEST_USERS_VERIFY_SA_PATH = ""
DEFAULT_GOOGLE_TEST_USER_VERIFY_TRUST_ADMIN = True
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
DEFAULT_MAPS_RATE_LIMIT_GEOCODE = "60/60"
DEFAULT_MAPS_RATE_LIMIT_DEFAULT = "120/3600"
DEFAULT_MAPS_RATE_LIMIT_PLACES = "30/60"
DEFAULT_MAPS_RATE_LIMIT_DETAILS = "40/60"
DEFAULT_MAPS_RATE_LIMIT_ROUTES = "20/60"
DEFAULT_MAPS_RATE_LIMIT_STATIC = "10/60"
DEFAULT_MAPS_TRANSIT_LINK_PROVIDER = "yandex"

# Yandex Music (device OAuth via yandex-music library)
DEFAULT_YANDEX_TOKEN_DB_PATH = "data/yandex_tokens.sqlite"
DEFAULT_YANDEX_MUSIC_LANGUAGE = "ru"
DEFAULT_YANDEX_MUSIC_RATE_LIMIT_READ = "120/60"
DEFAULT_YANDEX_MUSIC_RATE_LIMIT_WRITE = "60/60"

DEFAULT_TOOL_RESULT_DB_PATH = "data/tool_results.sqlite"
DEFAULT_TOOL_RESULT_ARCHIVE_MIN_CHARS = 150
DEFAULT_TOOL_RESULT_COLLAPSE_STALE_STEPS = 10
DEFAULT_TOOL_RESULT_TTL_HOURS = 0
DEFAULT_TOOL_RESULT_SUMMARIZE_MAX_INPUT_CHARS = 12_000
DEFAULT_TOOL_RESULT_SUMMARIZE_MAX_RETRIES = 3
DEFAULT_TOOL_RESULT_SUMMARIZE_MIN_CHARS = 80
DEFAULT_TOOL_RESULT_SUMMARIZE_MAX_CONCURRENT = 3
DEFAULT_SUMMARIZE_MODEL = "accounts/fireworks/models/deepseek-v4-flash"
DEFAULT_WORKER_CONTENT_SUMMARIZE_MAX_CHARS = 200

DEFAULT_AGENT_COACH_ENABLED = True
DEFAULT_COACH_EVERY_N_TOOL_CALLS = 5
DEFAULT_COACH_MAX_FIELD_CHARS = 700
DEFAULT_COACH_MAX_TRACE_CHARS = 60000
DEFAULT_COACH_INJECT_HINTS = True
DEFAULT_COACH_MAX_OUTPUT_TOKENS = 8192

DEFAULT_AGENT_CHECKER_ENABLED = True
DEFAULT_CHECKER_TOOLS_ALLOWLIST = "*"
DEFAULT_CHECKER_MAX_OUTPUT_TOKENS = 1024
DEFAULT_CHECKER_SKIP_CACHED = True
DEFAULT_CHECKER_EVIDENCE_MAX_CHARS = 8000
DEFAULT_AGENT_CHECKER_DEBUG = False

# Thorough multi-agent system (phase 1 planners + phase 2 merger) — not wired to bot yet
DEFAULT_THOROUGH_ENABLED = False
DEFAULT_THOROUGH_PLANNER_UNIT_MODEL = "accounts/fireworks/models/kimi-k2p6"
DEFAULT_THOROUGH_PLANNER_SURFACE_MODEL = "accounts/fireworks/models/glm-5p2"
DEFAULT_THOROUGH_PLANNER_HOT_MODEL = "accounts/fireworks/models/qwen3p7-plus"
DEFAULT_THOROUGH_MERGER_MODEL = "accounts/fireworks/models/glm-5p2"
DEFAULT_THOROUGH_PLANNER_MAX_OUTPUT_TOKENS = 4096
DEFAULT_THOROUGH_MERGER_MAX_OUTPUT_TOKENS = 8192

DEFAULT_TOOL_RESULT_ARCHIVE_ENABLED = True
DEFAULT_TOOL_RESULT_COLLAPSE_WAIT_SECONDS = 30.0
DEFAULT_TOOL_RESULT_CLEANUP_INTERVAL_SECONDS = 3600
DEFAULT_TOOL_RESULT_MAX_ROWS_PER_USER = 0

DEFAULT_PDF_RATE_LIMIT_READ = "60/60"
DEFAULT_PDF_MAX_TEXT_CHARS_PER_PAGE = 8000
DEFAULT_PDF_MAX_TABLES = 20
DEFAULT_PDF_MAX_IMAGES = 20
DEFAULT_PDF_MAX_SEARCH_RESULTS = 50

DEFAULT_OCR_BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_OCR_API_KEY = ""
DEFAULT_OCR_MODEL = "mistral-ocr-latest"  # Mistral OCR 4 (mistral-ocr-4-0)
DEFAULT_OCR_MAX_PAGES = 50
DEFAULT_OCR_DPI = 200
DEFAULT_OCR_RATE_LIMIT = "20/60"

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
DEFAULT_GMAIL_RATE_LIMIT_READ = "120/60"
DEFAULT_GMAIL_RATE_LIMIT_WRITE = "60/60"

DEFAULT_DRIVE_MAX_DOWNLOAD_BYTES = GOOGLE_DRIVE_MAX_BLOB_BYTES
DEFAULT_DRIVE_MAX_EXPORT_BYTES = GOOGLE_DRIVE_MAX_EXPORT_BYTES
DEFAULT_DRIVE_MAX_UPLOAD_BYTES = 10 * _MB
DEFAULT_DRIVE_MAX_EXPORT_CHARS = 50_000
DEFAULT_DRIVE_DEFAULT_MAX_RESULTS = 10
DEFAULT_DRIVE_RATE_LIMIT_READ = "120/60"
DEFAULT_DRIVE_RATE_LIMIT_WRITE = "60/60"

DEFAULT_RUN_FILE_MAX_BYTES = GOOGLE_DRIVE_MAX_BLOB_BYTES

DEFAULT_WORKSPACE_ROOT = "data/workspaces"
DEFAULT_WORKSPACE_MAX_BYTES_PER_USER = 500 * _MB
DEFAULT_WORKSPACE_MAX_FILE_BYTES = 50 * _MB
DEFAULT_WORKSPACE_MAX_FILES_PER_USER = 1000
DEFAULT_WORKSPACE_READ_PREVIEW_LINES = 30
DEFAULT_WORKSPACE_READ_PREVIEW_LINES_MAX = 50
DEFAULT_WORKSPACE_READ_LINES_MAX = 500
DEFAULT_WORKSPACE_UPLOAD_MAX_BYTES = 20 * _MB
DEFAULT_WORKSPACE_RATE_LIMIT_READ = "120/60"
DEFAULT_WORKSPACE_RATE_LIMIT_WRITE = "60/60"
DEFAULT_WORKSPACE_RATE_LIMIT_DELETE = "20/60"
DEFAULT_WORKSPACE_GREP_MAX_MATCHES = 200
DEFAULT_WORKSPACE_GREP_MAX_FILES = 100
DEFAULT_WORKSPACE_UNZIP_MAX_FILES = 500
DEFAULT_WORKSPACE_UNZIP_MAX_BYTES = 200 * _MB

DEFAULT_TELEGRAM_MAX_DOCUMENT_BYTES = TELEGRAM_BOT_MAX_DOCUMENT_BYTES
DEFAULT_TELEGRAM_MAX_PHOTO_BYTES = TELEGRAM_BOT_MAX_PHOTO_BYTES
DEFAULT_TELEGRAM_MAX_AUDIO_BYTES = TELEGRAM_BOT_MAX_AUDIO_BYTES

DEFAULT_SHEETS_MAX_CELLS = 10_000
DEFAULT_SHEETS_RATE_LIMIT_READ = "120/60"
DEFAULT_SHEETS_RATE_LIMIT_WRITE = "60/60"


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


def _llm_triplet_env(
    prefix: str,
    *,
    default_base_url: str,
    default_api_key: str,
    default_model: str,
) -> tuple[str, str, str]:
    return (
        _str_env(f"{prefix}_BASE_URL", default_base_url),
        _str_env(f"{prefix}_API_KEY", default_api_key),
        _str_env(f"{prefix}_MODEL", default_model),
    )


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


def _parse_user_ids(raw: str) -> frozenset[int]:
    if not raw:
        return frozenset()
    return frozenset(int(part.strip()) for part in raw.split(",") if part.strip())


def _parse_admin_user_ids(raw: str) -> frozenset[int]:
    return _parse_user_ids(raw)


@dataclass(frozen=True)
class Settings:
    # Telegram bot
    telegram_bot_token: str
    admin_user_ids: frozenset[int]
    allowed_user_ids: frozenset[int]
    access_approval_enabled: bool
    access_db_path: str

    # Graph memory foundation (PR 0 — disabled by default, no user-visible behavior)
    memory_ingest_enabled: bool
    memory_db_path: str
    memory_worker_enabled: bool
    memory_worker_concurrency: int
    memory_worker_poll_seconds: float
    memory_job_lease_seconds: int
    memory_job_max_attempts: int
    memory_job_retry_base_seconds: float
    memory_job_retry_max_seconds: float
    memory_job_claim_batch_size: int
    memory_ingest_queue_maxsize: int
    memory_ingest_scan_interval_seconds: float
    memory_ingest_scan_batch_size: int
    memory_ingest_failure_max_attempts: int
    memory_ingest_retry_base_seconds: float
    memory_ingest_retry_max_seconds: float
    memory_text_segment_chars: int
    memory_text_segment_overlap: int
    memory_tool_reconcile_batch_size: int
    memory_ingest_shutdown_grace_seconds: float
    memory_extraction_enabled: bool
    memory_extraction_model_profile: str
    memory_extraction_max_tokens: int

    # LLM / agent
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    reasoning_effort: str | None
    llm_context_window_tokens: int
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
    chat_db_path: str
    chat_migrate_v1_source_path: str
    chat_session_summary_on_archive: bool
    chat_session_summary_max_input_chars: int
    chat_session_summary_per_turn_max_chars: int
    chat_period_summary_enabled: bool
    chat_period_summary_on_session_archive: bool
    chat_period_summary_max_input_chars: int
    chat_period_summary_boundary_enabled: bool
    chat_period_summary_boundary_poll_seconds: int
    chat_migrate_v1_on_startup: bool
    chat_migrate_v1_target: str
    chat_migrate_v1_backup: bool
    chat_search_chunk_chars: int
    chat_search_chunk_overlap: int
    chat_search_top_k: int
    chat_search_keyword_candidates: int
    chat_search_vector_scan_limit: int
    chat_search_max_per_session: int
    chat_index_on_startup: bool
    chat_index_payload_max_chars: int
    message_gap_minutes: int

    # Single-instance guard (Telegram polling)
    instance_lock_enabled: bool
    instance_lock_path: str

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
    google_cloud_project_id: str
    google_cloud_test_users_url: str
    google_test_users_verify_sa_path: str
    google_test_user_verify_trust_admin: bool

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

    # Yandex Music
    yandex_token_db_path: str
    yandex_music_language: str
    rate_limit_yandex_music_read: tuple[int, int] | None
    rate_limit_yandex_music_write: tuple[int, int] | None

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

    # Tool result archive (per-user SQLite + summarize + collapse)
    tool_result_archive_enabled: bool
    tool_result_db_path: str
    tool_result_archive_min_chars: int
    tool_result_collapse_stale_steps: int
    tool_result_ttl_hours: int
    tool_result_summarize_max_input_chars: int
    tool_result_summarize_max_retries: int
    tool_result_summarize_min_chars: int
    tool_result_summarize_max_concurrent: int
    tool_result_collapse_wait_seconds: float
    tool_result_cleanup_interval_seconds: int
    tool_result_max_rows_per_user: int

    # Lightweight LLM for tool-result + worker-content summarization (not the agent model)
    summarize_base_url: str
    summarize_api_key: str
    summarize_model: str

    # Worker content summarize (assistant planning text compression)
    worker_content_summarize_max_chars: int

    # Trajectory coach (periodic strategy review, uses summarize model)
    agent_coach_enabled: bool
    coach_every_n_tool_calls: int
    coach_max_field_chars: int
    coach_max_trace_chars: int
    coach_inject_hints: bool
    coach_max_output_tokens: int

    # Per-tool checker (uses checker/summarize model profile)
    agent_checker_enabled: bool
    checker_base_url: str
    checker_api_key: str
    checker_model: str
    checker_max_output_tokens: int
    checker_skip_cached: bool
    checker_tools_allowlist: str
    checker_evidence_max_chars: int
    agent_checker_debug: bool

    # Thorough multi-agent (phase planners P1/P2/P3 + merger M)
    thorough_enabled: bool
    thorough_planner_unit_base_url: str
    thorough_planner_unit_api_key: str
    thorough_planner_unit_model: str
    thorough_planner_surface_base_url: str
    thorough_planner_surface_api_key: str
    thorough_planner_surface_model: str
    thorough_planner_hot_base_url: str
    thorough_planner_hot_api_key: str
    thorough_planner_hot_model: str
    thorough_merger_base_url: str
    thorough_merger_api_key: str
    thorough_merger_model: str
    thorough_planner_max_output_tokens: int
    thorough_merger_max_output_tokens: int

    # PDF tools
    pdf_rate_limit_read: tuple[int, int] | None
    pdf_max_text_chars_per_page: int
    pdf_max_tables: int
    pdf_max_images: int
    pdf_max_search_results: int

    # OCR via vision API
    ocr_base_url: str
    ocr_api_key: str
    ocr_model: str
    ocr_max_pages: int
    ocr_dpi: int
    ocr_rate_limit: tuple[int, int] | None


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

    openai_api_key = _str_env("OPENAI_API_KEY") or _str_env("EMBEDDING_API_KEY")
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY or EMBEDDING_API_KEY is not set")

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

    chat_migrate_v1_source_path = (
        _optional_str_env("CHAT_MIGRATE_V1_SOURCE_PATH")
        or _str_env("CHAT_HISTORY_DB_PATH", DEFAULT_CHAT_MIGRATE_V1_SOURCE_PATH)
    )

    summarize_base_url = _str_env("SUMMARIZE_BASE_URL", openai_base_url)
    summarize_api_key = _str_env("SUMMARIZE_API_KEY", openai_api_key)
    summarize_model = _str_env("SUMMARIZE_MODEL", DEFAULT_SUMMARIZE_MODEL)
    checker_base_url = _str_env("CHECKER_BASE_URL", summarize_base_url)
    checker_api_key = _str_env("CHECKER_API_KEY", summarize_api_key)
    checker_model = _str_env("CHECKER_MODEL", summarize_model)

    thorough_llm_defaults = {
        "default_base_url": summarize_base_url,
        "default_api_key": summarize_api_key,
    }
    (
        thorough_planner_unit_base_url,
        thorough_planner_unit_api_key,
        thorough_planner_unit_model,
    ) = _llm_triplet_env(
        "THOROUGH_PLANNER_UNIT",
        default_model=DEFAULT_THOROUGH_PLANNER_UNIT_MODEL,
        **thorough_llm_defaults,
    )
    (
        thorough_planner_surface_base_url,
        thorough_planner_surface_api_key,
        thorough_planner_surface_model,
    ) = _llm_triplet_env(
        "THOROUGH_PLANNER_SURFACE",
        default_model=DEFAULT_THOROUGH_PLANNER_SURFACE_MODEL,
        **thorough_llm_defaults,
    )
    (
        thorough_planner_hot_base_url,
        thorough_planner_hot_api_key,
        thorough_planner_hot_model,
    ) = _llm_triplet_env(
        "THOROUGH_PLANNER_HOT",
        default_model=DEFAULT_THOROUGH_PLANNER_HOT_MODEL,
        **thorough_llm_defaults,
    )
    (
        thorough_merger_base_url,
        thorough_merger_api_key,
        thorough_merger_model,
    ) = _llm_triplet_env(
        "THOROUGH_MERGER",
        default_model=DEFAULT_THOROUGH_MERGER_MODEL,
        **thorough_llm_defaults,
    )

    return Settings(
        telegram_bot_token=telegram_bot_token,
        admin_user_ids=_parse_admin_user_ids(_str_env("ADMIN_USER_IDS")),
        allowed_user_ids=_parse_user_ids(_str_env("ALLOWED_USER_IDS")),
        access_approval_enabled=_bool_env("ACCESS_APPROVAL_ENABLED", DEFAULT_ACCESS_APPROVAL_ENABLED),
        access_db_path=_str_env("ACCESS_DB_PATH", DEFAULT_ACCESS_DB_PATH),
        memory_ingest_enabled=_bool_env("MEMORY_INGEST_ENABLED", DEFAULT_MEMORY_INGEST_ENABLED),
        memory_db_path=_str_env("MEMORY_DB_PATH", DEFAULT_MEMORY_DB_PATH),
        memory_worker_enabled=_bool_env("MEMORY_WORKER_ENABLED", DEFAULT_MEMORY_WORKER_ENABLED),
        memory_worker_concurrency=_int_env(
            "MEMORY_WORKER_CONCURRENCY",
            DEFAULT_MEMORY_WORKER_CONCURRENCY,
        ),
        memory_worker_poll_seconds=_float_env(
            "MEMORY_WORKER_POLL_SECONDS",
            DEFAULT_MEMORY_WORKER_POLL_SECONDS,
        ),
        memory_job_lease_seconds=_int_env(
            "MEMORY_JOB_LEASE_SECONDS",
            DEFAULT_MEMORY_JOB_LEASE_SECONDS,
        ),
        memory_job_max_attempts=_int_env(
            "MEMORY_JOB_MAX_ATTEMPTS",
            DEFAULT_MEMORY_JOB_MAX_ATTEMPTS,
        ),
        memory_job_retry_base_seconds=_float_env(
            "MEMORY_JOB_RETRY_BASE_SECONDS",
            DEFAULT_MEMORY_JOB_RETRY_BASE_SECONDS,
        ),
        memory_job_retry_max_seconds=_float_env(
            "MEMORY_JOB_RETRY_MAX_SECONDS",
            DEFAULT_MEMORY_JOB_RETRY_MAX_SECONDS,
        ),
        memory_job_claim_batch_size=_int_env(
            "MEMORY_JOB_CLAIM_BATCH_SIZE",
            DEFAULT_MEMORY_JOB_CLAIM_BATCH_SIZE,
        ),
        memory_ingest_queue_maxsize=_int_env(
            "MEMORY_INGEST_QUEUE_MAXSIZE",
            DEFAULT_MEMORY_INGEST_QUEUE_MAXSIZE,
        ),
        memory_ingest_scan_interval_seconds=_float_env(
            "MEMORY_INGEST_SCAN_INTERVAL_SECONDS",
            DEFAULT_MEMORY_INGEST_SCAN_INTERVAL_SECONDS,
        ),
        memory_ingest_scan_batch_size=_int_env(
            "MEMORY_INGEST_SCAN_BATCH_SIZE",
            DEFAULT_MEMORY_INGEST_SCAN_BATCH_SIZE,
        ),
        memory_ingest_failure_max_attempts=_int_env(
            "MEMORY_INGEST_FAILURE_MAX_ATTEMPTS",
            DEFAULT_MEMORY_INGEST_FAILURE_MAX_ATTEMPTS,
        ),
        memory_ingest_retry_base_seconds=_float_env(
            "MEMORY_INGEST_RETRY_BASE_SECONDS",
            DEFAULT_MEMORY_INGEST_RETRY_BASE_SECONDS,
        ),
        memory_ingest_retry_max_seconds=_float_env(
            "MEMORY_INGEST_RETRY_MAX_SECONDS",
            DEFAULT_MEMORY_INGEST_RETRY_MAX_SECONDS,
        ),
        memory_text_segment_chars=_int_env(
            "MEMORY_TEXT_SEGMENT_CHARS",
            DEFAULT_MEMORY_TEXT_SEGMENT_CHARS,
        ),
        memory_text_segment_overlap=_int_env(
            "MEMORY_TEXT_SEGMENT_OVERLAP",
            DEFAULT_MEMORY_TEXT_SEGMENT_OVERLAP,
        ),
        memory_tool_reconcile_batch_size=_int_env(
            "MEMORY_TOOL_RECONCILE_BATCH_SIZE",
            DEFAULT_MEMORY_TOOL_RECONCILE_BATCH_SIZE,
        ),
        memory_ingest_shutdown_grace_seconds=_float_env(
            "MEMORY_INGEST_SHUTDOWN_GRACE_SECONDS",
            DEFAULT_MEMORY_INGEST_SHUTDOWN_GRACE_SECONDS,
        ),
        memory_extraction_enabled=_bool_env(
            "MEMORY_EXTRACTION_ENABLED",
            DEFAULT_MEMORY_EXTRACTION_ENABLED,
        ),
        memory_extraction_model_profile=_str_env(
            "MEMORY_EXTRACTION_MODEL_PROFILE",
            DEFAULT_MEMORY_EXTRACTION_MODEL_PROFILE,
        ),
        memory_extraction_max_tokens=_int_env(
            "MEMORY_EXTRACTION_MAX_TOKENS",
            DEFAULT_MEMORY_EXTRACTION_MAX_TOKENS,
        ),
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        openai_model=_str_env("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        reasoning_effort=_reasoning_effort_env("REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
        llm_context_window_tokens=_int_env(
            "LLM_CONTEXT_WINDOW_TOKENS",
            DEFAULT_LLM_CONTEXT_WINDOW_TOKENS,
        ),
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
        chat_db_path=_str_env("CHAT_DB_PATH", DEFAULT_CHAT_DB_PATH),
        chat_migrate_v1_source_path=chat_migrate_v1_source_path,
        chat_session_summary_on_archive=_bool_env(
            "CHAT_SESSION_SUMMARY_ON_ARCHIVE",
            DEFAULT_CHAT_SESSION_SUMMARY_ON_ARCHIVE,
        ),
        chat_session_summary_max_input_chars=_int_env(
            "CHAT_SESSION_SUMMARY_MAX_INPUT_CHARS",
            DEFAULT_CHAT_SESSION_SUMMARY_MAX_INPUT_CHARS,
        ),
        chat_session_summary_per_turn_max_chars=_int_env(
            "CHAT_SESSION_SUMMARY_PER_TURN_MAX_CHARS",
            DEFAULT_CHAT_SESSION_SUMMARY_PER_TURN_MAX_CHARS,
        ),
        chat_period_summary_enabled=_bool_env(
            "CHAT_PERIOD_SUMMARY_ENABLED",
            DEFAULT_CHAT_PERIOD_SUMMARY_ENABLED,
        ),
        chat_period_summary_on_session_archive=_bool_env(
            "CHAT_PERIOD_SUMMARY_ON_SESSION_ARCHIVE",
            DEFAULT_CHAT_PERIOD_SUMMARY_ON_SESSION_ARCHIVE,
        ),
        chat_period_summary_max_input_chars=_int_env(
            "CHAT_PERIOD_SUMMARY_MAX_INPUT_CHARS",
            DEFAULT_CHAT_PERIOD_SUMMARY_MAX_INPUT_CHARS,
        ),
        chat_period_summary_boundary_enabled=_bool_env(
            "CHAT_PERIOD_SUMMARY_BOUNDARY_ENABLED",
            DEFAULT_CHAT_PERIOD_SUMMARY_BOUNDARY_ENABLED,
        ),
        chat_period_summary_boundary_poll_seconds=_int_env(
            "CHAT_PERIOD_SUMMARY_BOUNDARY_POLL_SECONDS",
            DEFAULT_CHAT_PERIOD_SUMMARY_BOUNDARY_POLL_SECONDS,
        ),
        chat_migrate_v1_on_startup=_bool_env(
            "CHAT_MIGRATE_V1_ON_STARTUP",
            DEFAULT_CHAT_MIGRATE_V1_ON_STARTUP,
        ),
        chat_migrate_v1_target=_str_env(
            "CHAT_MIGRATE_V1_TARGET",
            DEFAULT_CHAT_MIGRATE_V1_TARGET,
        ).lower(),
        chat_migrate_v1_backup=_bool_env(
            "CHAT_MIGRATE_V1_BACKUP",
            DEFAULT_CHAT_MIGRATE_V1_BACKUP,
        ),
        chat_search_chunk_chars=_int_env(
            "CHAT_SEARCH_CHUNK_CHARS",
            DEFAULT_CHAT_SEARCH_CHUNK_CHARS,
        ),
        chat_search_chunk_overlap=_int_env(
            "CHAT_SEARCH_CHUNK_OVERLAP",
            DEFAULT_CHAT_SEARCH_CHUNK_OVERLAP,
        ),
        chat_search_top_k=_int_env(
            "CHAT_SEARCH_TOP_K",
            DEFAULT_CHAT_SEARCH_TOP_K,
        ),
        chat_search_keyword_candidates=_int_env(
            "CHAT_SEARCH_KEYWORD_CANDIDATES",
            DEFAULT_CHAT_SEARCH_KEYWORD_CANDIDATES,
        ),
        chat_search_vector_scan_limit=_int_env(
            "CHAT_SEARCH_VECTOR_SCAN_LIMIT",
            DEFAULT_CHAT_SEARCH_VECTOR_SCAN_LIMIT,
        ),
        chat_search_max_per_session=_int_env(
            "CHAT_SEARCH_MAX_PER_SESSION",
            DEFAULT_CHAT_SEARCH_MAX_PER_SESSION,
        ),
        chat_index_on_startup=_bool_env(
            "CHAT_INDEX_ON_STARTUP",
            DEFAULT_CHAT_INDEX_ON_STARTUP,
        ),
        chat_index_payload_max_chars=_int_env(
            "CHAT_INDEX_PAYLOAD_MAX_CHARS",
            DEFAULT_CHAT_INDEX_PAYLOAD_MAX_CHARS,
        ),
        message_gap_minutes=_int_env("MESSAGE_GAP_MINUTES", DEFAULT_MESSAGE_GAP_MINUTES),
        instance_lock_enabled=_bool_env("INSTANCE_LOCK_ENABLED", DEFAULT_INSTANCE_LOCK_ENABLED),
        instance_lock_path=_str_env("INSTANCE_LOCK_PATH", DEFAULT_INSTANCE_LOCK_PATH),
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
        google_cloud_project_id=_str_env("GOOGLE_CLOUD_PROJECT_ID", DEFAULT_GOOGLE_CLOUD_PROJECT_ID),
        google_cloud_test_users_url=_str_env(
            "GOOGLE_CLOUD_TEST_USERS_URL",
            DEFAULT_GOOGLE_CLOUD_TEST_USERS_URL,
        ),
        google_test_users_verify_sa_path=_str_env(
            "GOOGLE_TEST_USERS_VERIFY_SA_PATH",
            DEFAULT_GOOGLE_TEST_USERS_VERIFY_SA_PATH,
        ),
        google_test_user_verify_trust_admin=_bool_env(
            "GOOGLE_TEST_USER_VERIFY_TRUST_ADMIN",
            DEFAULT_GOOGLE_TEST_USER_VERIFY_TRUST_ADMIN,
        ),
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
        yandex_token_db_path=_str_env("YANDEX_TOKEN_DB_PATH", DEFAULT_YANDEX_TOKEN_DB_PATH),
        yandex_music_language=_str_env("YANDEX_MUSIC_LANGUAGE", DEFAULT_YANDEX_MUSIC_LANGUAGE),
        rate_limit_yandex_music_read=_parse_rate_limit(
            _optional_str_env("YANDEX_MUSIC_RATE_LIMIT_READ") or DEFAULT_YANDEX_MUSIC_RATE_LIMIT_READ
        ),
        rate_limit_yandex_music_write=_parse_rate_limit(
            _optional_str_env("YANDEX_MUSIC_RATE_LIMIT_WRITE") or DEFAULT_YANDEX_MUSIC_RATE_LIMIT_WRITE
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
        tool_result_archive_enabled=_bool_env(
            "TOOL_RESULT_ARCHIVE_ENABLED",
            DEFAULT_TOOL_RESULT_ARCHIVE_ENABLED,
        ),
        tool_result_db_path=_str_env("TOOL_RESULT_DB_PATH", DEFAULT_TOOL_RESULT_DB_PATH),
        tool_result_archive_min_chars=_int_env(
            "TOOL_RESULT_ARCHIVE_MIN_CHARS",
            DEFAULT_TOOL_RESULT_ARCHIVE_MIN_CHARS,
        ),
        tool_result_collapse_stale_steps=_int_env(
            "TOOL_RESULT_COLLAPSE_STALE_STEPS",
            DEFAULT_TOOL_RESULT_COLLAPSE_STALE_STEPS,
        ),
        tool_result_ttl_hours=_int_env("TOOL_RESULT_TTL_HOURS", DEFAULT_TOOL_RESULT_TTL_HOURS),
        tool_result_summarize_max_input_chars=_int_env(
            "TOOL_RESULT_SUMMARIZE_MAX_INPUT_CHARS",
            DEFAULT_TOOL_RESULT_SUMMARIZE_MAX_INPUT_CHARS,
        ),
        tool_result_summarize_max_retries=_int_env(
            "TOOL_RESULT_SUMMARIZE_MAX_RETRIES",
            DEFAULT_TOOL_RESULT_SUMMARIZE_MAX_RETRIES,
        ),
        tool_result_summarize_min_chars=_int_env(
            "TOOL_RESULT_SUMMARIZE_MIN_CHARS",
            DEFAULT_TOOL_RESULT_SUMMARIZE_MIN_CHARS,
        ),
        tool_result_summarize_max_concurrent=_int_env(
            "TOOL_RESULT_SUMMARIZE_MAX_CONCURRENT",
            DEFAULT_TOOL_RESULT_SUMMARIZE_MAX_CONCURRENT,
        ),
        tool_result_collapse_wait_seconds=_float_env(
            "TOOL_RESULT_COLLAPSE_WAIT_SECONDS",
            DEFAULT_TOOL_RESULT_COLLAPSE_WAIT_SECONDS,
        ),
        tool_result_cleanup_interval_seconds=_int_env(
            "TOOL_RESULT_CLEANUP_INTERVAL_SECONDS",
            DEFAULT_TOOL_RESULT_CLEANUP_INTERVAL_SECONDS,
        ),
        tool_result_max_rows_per_user=_int_env(
            "TOOL_RESULT_MAX_ROWS_PER_USER",
            DEFAULT_TOOL_RESULT_MAX_ROWS_PER_USER,
        ),
        summarize_base_url=summarize_base_url,
        summarize_api_key=summarize_api_key,
        summarize_model=summarize_model,
        worker_content_summarize_max_chars=_int_env(
            "WORKER_CONTENT_SUMMARIZE_MAX_CHARS",
            DEFAULT_WORKER_CONTENT_SUMMARIZE_MAX_CHARS,
        ),
        agent_coach_enabled=_bool_env("AGENT_COACH_ENABLED", DEFAULT_AGENT_COACH_ENABLED),
        coach_every_n_tool_calls=_int_env(
            "COACH_EVERY_N_TOOL_CALLS",
            DEFAULT_COACH_EVERY_N_TOOL_CALLS,
        ),
        coach_max_field_chars=_int_env("COACH_MAX_FIELD_CHARS", DEFAULT_COACH_MAX_FIELD_CHARS),
        coach_max_trace_chars=_int_env("COACH_MAX_TRACE_CHARS", DEFAULT_COACH_MAX_TRACE_CHARS),
        coach_inject_hints=_bool_env("COACH_INJECT_HINTS", DEFAULT_COACH_INJECT_HINTS),
        coach_max_output_tokens=_int_env(
            "COACH_MAX_OUTPUT_TOKENS",
            DEFAULT_COACH_MAX_OUTPUT_TOKENS,
        ),
        agent_checker_enabled=_bool_env("AGENT_CHECKER_ENABLED", DEFAULT_AGENT_CHECKER_ENABLED),
        checker_base_url=checker_base_url,
        checker_api_key=checker_api_key,
        checker_model=checker_model,
        checker_max_output_tokens=_int_env(
            "CHECKER_MAX_OUTPUT_TOKENS",
            DEFAULT_CHECKER_MAX_OUTPUT_TOKENS,
        ),
        checker_skip_cached=_bool_env("CHECKER_SKIP_CACHED", DEFAULT_CHECKER_SKIP_CACHED),
        checker_tools_allowlist=_str_env(
            "CHECKER_TOOLS_ALLOWLIST",
            DEFAULT_CHECKER_TOOLS_ALLOWLIST,
        ),
        checker_evidence_max_chars=_int_env(
            "CHECKER_EVIDENCE_MAX_CHARS",
            DEFAULT_CHECKER_EVIDENCE_MAX_CHARS,
        ),
        agent_checker_debug=_bool_env("AGENT_CHECKER_DEBUG", DEFAULT_AGENT_CHECKER_DEBUG),
        thorough_enabled=_bool_env("THOROUGH_ENABLED", DEFAULT_THOROUGH_ENABLED),
        thorough_planner_unit_base_url=thorough_planner_unit_base_url,
        thorough_planner_unit_api_key=thorough_planner_unit_api_key,
        thorough_planner_unit_model=thorough_planner_unit_model,
        thorough_planner_surface_base_url=thorough_planner_surface_base_url,
        thorough_planner_surface_api_key=thorough_planner_surface_api_key,
        thorough_planner_surface_model=thorough_planner_surface_model,
        thorough_planner_hot_base_url=thorough_planner_hot_base_url,
        thorough_planner_hot_api_key=thorough_planner_hot_api_key,
        thorough_planner_hot_model=thorough_planner_hot_model,
        thorough_merger_base_url=thorough_merger_base_url,
        thorough_merger_api_key=thorough_merger_api_key,
        thorough_merger_model=thorough_merger_model,
        thorough_planner_max_output_tokens=_int_env(
            "THOROUGH_PLANNER_MAX_OUTPUT_TOKENS",
            DEFAULT_THOROUGH_PLANNER_MAX_OUTPUT_TOKENS,
        ),
        thorough_merger_max_output_tokens=_int_env(
            "THOROUGH_MERGER_MAX_OUTPUT_TOKENS",
            DEFAULT_THOROUGH_MERGER_MAX_OUTPUT_TOKENS,
        ),
        pdf_rate_limit_read=_parse_rate_limit(
            _optional_str_env("PDF_RATE_LIMIT_READ") or DEFAULT_PDF_RATE_LIMIT_READ
        ),
        pdf_max_text_chars_per_page=_int_env(
            "PDF_MAX_TEXT_CHARS_PER_PAGE",
            DEFAULT_PDF_MAX_TEXT_CHARS_PER_PAGE,
        ),
        pdf_max_tables=_int_env("PDF_MAX_TABLES", DEFAULT_PDF_MAX_TABLES),
        pdf_max_images=_int_env("PDF_MAX_IMAGES", DEFAULT_PDF_MAX_IMAGES),
        pdf_max_search_results=_int_env(
            "PDF_MAX_SEARCH_RESULTS",
            DEFAULT_PDF_MAX_SEARCH_RESULTS,
        ),
        ocr_base_url=_str_env("OCR_BASE_URL", DEFAULT_OCR_BASE_URL),
        ocr_api_key=_str_env("OCR_API_KEY", DEFAULT_OCR_API_KEY),
        ocr_model=_str_env("OCR_MODEL", DEFAULT_OCR_MODEL),
        ocr_max_pages=_int_env("OCR_MAX_PAGES", DEFAULT_OCR_MAX_PAGES),
        ocr_dpi=_int_env("OCR_DPI", DEFAULT_OCR_DPI),
        ocr_rate_limit=_parse_rate_limit(
            _optional_str_env("OCR_RATE_LIMIT") or DEFAULT_OCR_RATE_LIMIT
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
