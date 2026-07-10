from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from memory.ids import normalize_workspace_path

POINTER_VERSION = 1
SUPPORTED_POINTER_VERSIONS = frozenset({POINTER_VERSION})

POINTER_KINDS = frozenset(
    {
        "chat_message",
        "chat_span",
        "tool_result",
        "workspace_file",
        "document_region",
        "image_region",
    }
)


class PointerValidationError(ValueError):
    pass


class PointerOwnershipError(PermissionError):
    pass


@dataclass(frozen=True)
class EvidencePointer:
    pointer_version: int
    kind: str
    source_version_id: str
    location: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.pointer_version not in SUPPORTED_POINTER_VERSIONS:
            raise PointerValidationError(
                f"unsupported pointer_version: {self.pointer_version!r}"
            )
        if self.kind not in POINTER_KINDS:
            raise PointerValidationError(f"unsupported pointer kind: {self.kind!r}")
        source_version_id = str(self.source_version_id or "").strip()
        if not source_version_id:
            raise PointerValidationError("source_version_id must be non-empty")
        canonical_location = _canonicalize_pointer_location(
            self.kind,
            dict(self.location),
        )
        object.__setattr__(self, "source_version_id", source_version_id)
        object.__setattr__(self, "location", MappingProxyType(canonical_location))

    def to_mapping(self) -> dict[str, Any]:
        return pointer_to_mapping(self)


def pointer_to_mapping(pointer: EvidencePointer) -> dict[str, Any]:
    return {
        "pointer_version": pointer.pointer_version,
        "kind": pointer.kind,
        "source_version_id": pointer.source_version_id,
        "location": dict(pointer.location),
    }


def pointer_from_mapping(payload: Mapping[str, Any]) -> EvidencePointer:
    version = payload.get("pointer_version")
    if version not in SUPPORTED_POINTER_VERSIONS:
        raise PointerValidationError(f"unsupported pointer_version: {version!r}")
    kind = payload.get("kind")
    if kind not in POINTER_KINDS:
        raise PointerValidationError(f"unsupported pointer kind: {kind!r}")
    source_version_id = str(payload.get("source_version_id") or "").strip()
    if not source_version_id:
        raise PointerValidationError("source_version_id must be non-empty")
    location = payload.get("location")
    if not isinstance(location, Mapping):
        raise PointerValidationError("location must be an object")
    return EvidencePointer(
        pointer_version=int(version),
        kind=str(kind),
        source_version_id=source_version_id,
        location=dict(location),
    )


def validate_pointer_location(kind: str, location: Mapping[str, Any]) -> None:
    _canonicalize_pointer_location(kind, dict(location))


def _canonicalize_pointer_location(kind: str, location: dict[str, Any]) -> dict[str, Any]:
    if kind == "chat_message":
        _require_positive_int(location, "chat_message_id")
        return location
    if kind == "chat_span":
        start = _require_non_negative_int(location, "char_start")
        end = _require_non_negative_int(location, "char_end")
        if end < start:
            raise PointerValidationError("char_end must be >= char_start")
        _require_positive_int(location, "chat_message_id")
        return location
    if kind == "tool_result":
        ref = str(location.get("tool_result_ref") or "").strip()
        if not ref:
            raise PointerValidationError("tool_result_ref must be non-empty")
        location["tool_result_ref"] = ref
        has_start = "char_start" in location
        has_end = "char_end" in location
        if has_start or has_end:
            if not (has_start and has_end):
                raise PointerValidationError(
                    "tool_result char_start and char_end must be provided together"
                )
            start = _require_non_negative_int(location, "char_start")
            end = _require_non_negative_int(location, "char_end")
            if end < start:
                raise PointerValidationError("char_end must be >= char_start")
        return location
    if kind == "workspace_file":
        location["workspace_path"] = normalize_workspace_path(
            str(location.get("workspace_path") or "")
        )
        return location
    if kind == "document_region":
        location["workspace_path"] = normalize_workspace_path(
            str(location.get("workspace_path") or "")
        )
        _require_positive_int(location, "page")
        if "bbox" in location:
            location["bbox"] = _canonical_bbox(location["bbox"])
        if "char_start" in location or "char_end" in location:
            start = _require_non_negative_int(location, "char_start")
            end = _require_non_negative_int(location, "char_end")
            if end < start:
                raise PointerValidationError("char_end must be >= char_start")
        return location
    if kind == "image_region":
        location["workspace_path"] = normalize_workspace_path(
            str(location.get("workspace_path") or "")
        )
        location["region"] = _canonical_normalized_region(location.get("region"))
        return location
    raise PointerValidationError(f"unsupported pointer kind: {kind!r}")


def _require_positive_int(location: Mapping[str, Any], key: str) -> int:
    value = location.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PointerValidationError(f"{key} must be a positive integer")
    return value


def _require_non_negative_int(location: Mapping[str, Any], key: str) -> int:
    value = location.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PointerValidationError(f"{key} must be a non-negative integer")
    return value


def _canonical_bbox(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise PointerValidationError("bbox must contain four numbers")
    result: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise PointerValidationError("bbox must contain numbers")
        number = float(item)
        if not math.isfinite(number) or number < 0:
            raise PointerValidationError("bbox coordinates must be finite and non-negative")
        result.append(number)
    if result[2] < result[0] or result[3] < result[1]:
        raise PointerValidationError("bbox end coordinates must not precede start")
    return result


def _canonical_normalized_region(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise PointerValidationError("region must contain four normalized coordinates")
    result: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise PointerValidationError("region must contain numbers")
        number = float(item)
        if not math.isfinite(number) or number < 0 or number > 1:
            raise PointerValidationError("region coordinates must be within [0, 1]")
        result.append(number)
    if result[2] < result[0] or result[3] < result[1]:
        raise PointerValidationError("region end coordinates must not precede start")
    return result


@dataclass(frozen=True)
class DereferenceContract:
    pointer: EvidencePointer
    user_id: int
    source_version_id: str


def verify_pointer_ownership(
    pointer: EvidencePointer,
    *,
    user_id: int,
    source_version_id: str,
    source_user_id: int,
) -> None:
    if source_user_id != user_id:
        raise PointerOwnershipError("pointer source belongs to another user")
    if pointer.source_version_id != source_version_id:
        raise PointerOwnershipError("pointer source_version_id mismatch")


def replace_pointer_source_version(pointer: EvidencePointer, source_version_id: str) -> EvidencePointer:
    return EvidencePointer(
        pointer_version=pointer.pointer_version,
        kind=pointer.kind,
        source_version_id=source_version_id,
        location=dict(pointer.location),
    )


def dereference_contract(
    pointer: EvidencePointer,
    *,
    user_id: int,
    source_user_id: int,
) -> DereferenceContract:
    verify_pointer_ownership(
        pointer,
        user_id=user_id,
        source_version_id=pointer.source_version_id,
        source_user_id=source_user_id,
    )
    return DereferenceContract(
        pointer=pointer,
        user_id=user_id,
        source_version_id=pointer.source_version_id,
    )
