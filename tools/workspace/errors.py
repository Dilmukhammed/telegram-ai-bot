class WorkspaceError(Exception):
    """Base error for workspace operations."""


class WorkspacePathError(WorkspaceError):
    """Invalid or escaping path."""


class WorkspaceNotFoundError(WorkspaceError):
    """Path does not exist."""


class WorkspaceQuotaError(WorkspaceError):
    """Quota exceeded."""


class WorkspaceConflictError(WorkspaceError):
    """Target already exists or not empty."""
