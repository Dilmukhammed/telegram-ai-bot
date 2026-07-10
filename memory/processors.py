from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from memory.ids import canonical_json
from memory.models import ProcessorContext, ProcessorOutput


@runtime_checkable
class MemoryProcessor(Protocol):
    name: str
    version: str
    stages: frozenset[str]

    async def process(self, context: ProcessorContext) -> ProcessorOutput: ...


class ProcessorRegistry:
    def __init__(self) -> None:
        self._processors: dict[tuple[str, str, str], MemoryProcessor] = {}

    def register(self, processor: MemoryProcessor) -> None:
        for stage in processor.stages:
            key = (stage, processor.name, processor.version)
            existing = self._processors.get(key)
            if existing is not None:
                if _registry_identity(existing) != _registry_identity(processor):
                    raise ValueError(
                        f"incompatible processor already registered for {key!r}"
                    )
                continue
            self._processors[key] = processor

    def resolve(self, stage: str, processor_name: str, processor_version: str) -> MemoryProcessor:
        processor = self._processors.get((stage, processor_name, processor_version))
        if processor is None:
            raise KeyError(
                f"no processor registered for stage={stage!r} "
                f"name={processor_name!r} version={processor_version!r}"
            )
        return processor


class NoopProcessor:
    name = "noop"
    version = "1"
    stages = frozenset({"noop"})

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        payload = {
            "job_id": context.job.job_id,
            "source_version_id": context.source_version.source_version_id,
            "noop": True,
        }
        output_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return ProcessorOutput(output_hash=output_hash, output_json=payload)


def default_registry() -> ProcessorRegistry:
    registry = ProcessorRegistry()
    registry.register(NoopProcessor())
    return registry


def register_text_normalizers(
    registry: ProcessorRegistry,
    *,
    chat_reader: object,
    tool_reader: object,
    config: object,
) -> None:
    """Register ChatTextNormalizer and ToolResultTextNormalizer with the given readers.

    Called by TextIngestionRuntime after readers are available.
    Imported lazily to avoid pulling ingestion dependencies at module load.
    """
    from memory.ingestion.normalizers import ChatTextNormalizer, ToolResultTextNormalizer

    registry.register(ChatTextNormalizer(chat_reader=chat_reader, config=config))  # type: ignore[arg-type]
    registry.register(ToolResultTextNormalizer(tool_reader=tool_reader, config=config))  # type: ignore[arg-type]


def _registry_identity(processor: MemoryProcessor) -> object:
    explicit = getattr(processor, "registry_identity", None)
    if callable(explicit):
        return explicit()
    return type(processor)
