from typing import Any

from tools.schema import ToolSpec


async def _echo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"message": arguments["message"]}


ECHO_TOOL = ToolSpec(
    name="echo.test",
    description=(
        "Echoes back the provided message unchanged. Useful for testing the tool "
        "runtime and agent loop without external services."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Text to echo back.",
            },
        },
        "required": ["message"],
    },
    handler=_echo_handler,
    tags=("test", "debug", "echo"),
    cache_ttl_seconds=None,
    rate_limit=None,
    parallel_safe=True,
    examples=(
        "echo a message back",
        "repeat the input text",
        "test tool execution",
    ),
)
