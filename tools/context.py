import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    user_id: int | None = None
    turn: int = 0
    meta_tool: str = ""


_current_run_context: contextvars.ContextVar[RunContext] = contextvars.ContextVar(
    "current_run_context",
    default=RunContext(),
)


def set_run_context(ctx: RunContext) -> contextvars.Token[RunContext]:
    return _current_run_context.set(ctx)


def reset_run_context(token: contextvars.Token[RunContext]) -> None:
    _current_run_context.reset(token)


def get_run_context() -> RunContext:
    return _current_run_context.get()
