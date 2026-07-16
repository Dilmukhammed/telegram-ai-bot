from __future__ import annotations


class BrowserError(RuntimeError):
    """Base browser tool error with a stable agent-facing code."""

    code = "browser_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)

    @property
    def agent_code(self) -> str:
        return self.code


class BrowserNotConfiguredError(BrowserError):
    code = "browser_not_configured"


class BrowserViewerNotConfiguredError(BrowserError):
    code = "browser_viewer_not_configured"


class BrowserSessionLimitError(BrowserError):
    code = "session_limit"


class BrowserSteelRateLimitError(BrowserError):
    code = "steel_rate_limited"


class BrowserNoSessionError(BrowserError):
    code = "no_session"


class BrowserSessionExpiredError(BrowserError):
    code = "session_expired"


class BrowserProfileNotReadyError(BrowserError):
    code = "profile_not_ready"


class BrowserViewerTokenError(BrowserError):
    code = "viewer_token_invalid"


class BrowserNavigationError(BrowserError):
    code = "navigation_failed"


class BrowserRefNotFoundError(BrowserError):
    code = "ref_not_found"


class BrowserHandlerTimeoutError(BrowserError):
    code = "handler_timeout"


class BrowserReleaseError(BrowserError):
    code = "release_failed"
