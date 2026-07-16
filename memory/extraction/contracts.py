"""Legacy closed schema contracts removed.

PR3 extraction fields (kind / schema_name / role / mention_type) are free strings.
Ontology normalization belongs in later stages.
"""

from __future__ import annotations

from memory.extraction.schemas import ExtractionResult


def normalize_candidate_contracts(result: ExtractionResult) -> ExtractionResult:
    return result


def candidate_contract_violations(result: ExtractionResult) -> list[dict[str, object]]:
    return []
