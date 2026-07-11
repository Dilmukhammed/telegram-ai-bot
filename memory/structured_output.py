from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StructuredGeneration:
    text: str
    metadata: Mapping[str, Any]


class StructuredOutputModel:
    """Provider-neutral strict JSON transport with compatibility fallbacks."""

    def __init__(self, client: Any, *, model_profile: str, max_tokens: int) -> None:
        if not model_profile.strip():
            raise ValueError("model_profile must be non-empty")
        if max_tokens < 256:
            raise ValueError("max_tokens must be >= 256")
        self._client = client
        self.model_profile = model_profile
        self.max_tokens = max_tokens

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        schema_name: str | None,
        schema: Mapping[str, Any] | None,
    ) -> StructuredGeneration:
        formats: list[tuple[str, dict[str, Any]]] = []
        if schema_name is not None:
            if schema is None:
                raise ValueError("structured schema payload is required with schema_name")
            formats.extend(
                (
                    (
                        "json_schema_strict",
                        _structured_response_format(schema_name, schema, strict=True),
                    ),
                    (
                        "json_schema_compatible",
                        _structured_response_format(schema_name, schema, strict=False),
                    ),
                )
            )
        formats.append(("json_object", {"type": "json_object"}))
        attempts: list[dict[str, Any]] = []
        last_error: BaseException | None = None
        for format_name, response_format in formats:
            try:
                chat_structured = getattr(self._client, "chat_structured", None)
                call = chat_structured or self._client.chat_without_reasoning
                text = await call(
                    messages,
                    max_tokens=self.max_tokens,
                    response_format=response_format,
                    temperature=0.0,
                )
                attempts.append({"response_format": format_name, "status": "ok"})
                return StructuredGeneration(
                    text=text,
                    metadata={
                        "model_profile": self.model_profile,
                        "model": getattr(self._client, "model_name", None),
                        "reasoning_effort": getattr(self._client, "reasoning_effort", None),
                        "response_format": format_name,
                        "attempts": tuple(attempts),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - provider-specific format failures
                last_error = exc
                attempts.append(
                    {
                        "response_format": format_name,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        if last_error is not None:
            raise last_error
        raise RuntimeError("structured output call failed without a captured error")


def _structured_response_format(
    name: str,
    schema: Mapping[str, Any],
    *,
    strict: bool,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("structured schema name must be non-empty")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": strict,
            "schema": dict(schema),
        },
    }
