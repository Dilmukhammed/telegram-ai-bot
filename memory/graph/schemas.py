"""PR6 MVP: disposable graph projection from durable belief heads."""

from __future__ import annotations

GRAPH_SCHEMA_VERSION = "1"
MATERIALIZER_VERSION = "1"
BELIEF_POLICY_VERSION = "minimal_belief_v1"

OUTBOX_UPSERT = "upsert"
OUTBOX_EXPIRE = "expire"
OUTBOX_REMOVE = "remove"
OUTBOX_REBUILD_USER = "rebuild_user"

OUTBOX_PENDING = "pending"
OUTBOX_PROCESSING = "processing"
OUTBOX_DONE = "done"
OUTBOX_FAILED = "failed"

NODE_STATUS_ACTIVE = "active"
NODE_STATUS_EXPIRED = "expired"
EDGE_STATUS_ACTIVE = "active"
EDGE_STATUS_EXPIRED = "expired"

SUBJECT_ROLES = frozenset({"subject", "person", "actor", "owner", "user"})

ELIGIBLE_BELIEF_STATUS = "active"
ELIGIBLE_UTILITY_CLASS = "durable"


def is_materializable(*, belief_status: str, utility_class: str) -> bool:
    return (
        belief_status == ELIGIBLE_BELIEF_STATUS
        and utility_class == ELIGIBLE_UTILITY_CLASS
    )


def edge_type_for(*, kind: str, schema_name: str) -> str:
    return f"{kind}:{schema_name}"
