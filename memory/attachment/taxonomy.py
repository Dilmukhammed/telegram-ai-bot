from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

_TAXONOMY_DIR = Path(__file__).resolve().parent / "taxonomy"


def normalize_label(text: str) -> str:
    lowered = unicodedata.normalize("NFKC", text.strip().casefold())
    return re.sub(r"\s+", " ", lowered)


@dataclass(frozen=True, slots=True)
class TaxonomyTriple:
    child: str
    child_aliases: tuple[str, ...]
    op: str
    parent: str
    parent_aliases: tuple[str, ...]
    language: str
    domain_pack: str


def _iter_jsonl(path: Path, *, domain_pack: str) -> Iterator[TaxonomyTriple]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            yield TaxonomyTriple(
                child=str(row["child"]),
                child_aliases=tuple(str(a) for a in row.get("child_aliases") or ()),
                op=str(row["op"]),
                parent=str(row["parent"]),
                parent_aliases=tuple(str(a) for a in row.get("parent_aliases") or ()),
                language=str(row.get("language") or ""),
                domain_pack=domain_pack,
            )


def load_taxonomy(*, domain_pack: str | None = None) -> tuple[TaxonomyTriple, ...]:
    packs: list[TaxonomyTriple] = []
    for path in sorted(_TAXONOMY_DIR.glob("*_v1.jsonl")):
        name = path.stem
        pack = name.split("_", 1)[0] if "_" in name else name
        if domain_pack is not None and pack != domain_pack:
            continue
        packs.extend(_iter_jsonl(path, domain_pack=pack))
    return tuple(packs)


def match_taxonomy(
    label: str,
    *,
    domain_pack: str | None = None,
    enabled: bool = True,
) -> TaxonomyTriple | None:
    if not enabled:
        return None
    normalized = normalize_label(label)
    if not normalized:
        return None
    for triple in load_taxonomy(domain_pack=domain_pack):
        candidates = (triple.child, *triple.child_aliases)
        for candidate in candidates:
            if normalize_label(candidate) == normalized:
                return triple
    return None
