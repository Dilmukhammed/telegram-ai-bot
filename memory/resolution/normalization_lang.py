from __future__ import annotations

import unicodedata


def detect_script_language(text: str) -> str | None:
    """Return dominant script bucket for alias language hints."""
    if not text:
        return None
    cyrillic = 0
    latin = 0
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        if "CYRILLIC" in name:
            cyrillic += 1
        elif "LATIN" in name:
            latin += 1
    if cyrillic == 0 and latin == 0:
        return None
    if cyrillic > 0 and latin == 0:
        return "cyrillic"
    if latin > 0 and cyrillic == 0:
        return "latin"
    return None
