from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parent / "builtins"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    description: str
    tags: tuple[str, ...]
    content: str

    def to_list_item(self) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "description": self.description,
            "tags": list(self.tags),
        }


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(raw.strip())
    if not match:
        raise ValueError("Skill file must start with YAML frontmatter (---)")

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")

    body = match.group(2).strip()
    if not body:
        raise ValueError("Skill body is empty")
    return meta, body


def _parse_tags(raw: str) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _load_skill_file(path: Path) -> SkillSpec:
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    skill_id = meta.get("skill_id") or path.parent.name
    description = meta.get("description", "").strip()
    if not description:
        raise ValueError(f"Skill {path} missing description in frontmatter")
    return SkillSpec(
        skill_id=skill_id,
        description=description,
        tags=_parse_tags(meta.get("tags", "")),
        content=body,
    )


def _discover_skills() -> dict[str, SkillSpec]:
    skills: dict[str, SkillSpec] = {}
    if not _SKILLS_ROOT.is_dir():
        return skills

    for skill_file in sorted(_SKILLS_ROOT.glob("*/SKILL.md")):
        spec = _load_skill_file(skill_file)
        if spec.skill_id in skills:
            raise ValueError(f"Duplicate skill_id: {spec.skill_id}")
        skills[spec.skill_id] = spec
    return skills


_SKILLS: dict[str, SkillSpec] | None = None


def get_skill_registry() -> dict[str, SkillSpec]:
    global _SKILLS
    if _SKILLS is None:
        _SKILLS = _discover_skills()
    return _SKILLS


def get_skill(skill_id: str) -> SkillSpec | None:
    return get_skill_registry().get(skill_id)


def list_skills(*, tags: list[str] | None = None) -> list[SkillSpec]:
    items = list(get_skill_registry().values())
    if not tags:
        return sorted(items, key=lambda item: item.skill_id)

    required = {tag.strip().lower() for tag in tags if tag.strip()}
    filtered: list[SkillSpec] = []
    for item in items:
        item_tags = {tag.lower() for tag in item.tags}
        if required.issubset(item_tags):
            filtered.append(item)
    return sorted(filtered, key=lambda item: item.skill_id)
