"""Post-process GFM table cells before HTML render.

Telegram parses $...$ math only in markdown blocks, not inside <table> cells.
Models often wrap temperatures and simple values in LaTeX anyway — normalize here.
Extend incrementally as new artifacts show up in production.
"""

from __future__ import annotations

import re

# --- LaTeX typos / symbols (extend as needed) ---
_LATEX_APPROX_TYPO_RE = re.compile(r"\\appro\b")
_LATEX_APPROX_RE = re.compile(r"\\approx\b")

# $ +32^\circ\mathrm{C}$ or $+26^\\circ C$
_TEMP_MATH_RE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*"
    r"(?:\^\{?\s*\\circ\s*\}?|\\circ)\s*"
    r"(?:\\mathrm\s*\{\s*C\s*\}|C|°C)?\s*$",
    re.IGNORECASE,
)

_SIMPLE_NUMBER_MATH_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*$")
_INLINE_MATH_RE = re.compile(r"\$([^$]+)\$")
_ELLIPSIS_RANGE_RE = re.compile(r"\s+\.\.\.\s+")


def _normalize_math_fragment(inner: str) -> str:
    text = inner.strip()
    if not text:
        return ""

    if text in {"\\approx", "\\appro", "≈"}:
        return "≈"

    temp = _TEMP_MATH_RE.match(text)
    if temp:
        return f"{temp.group(1).replace(',', '.')} °C"

    number = _SIMPLE_NUMBER_MATH_RE.match(text)
    if number:
        return number.group(1).replace(",", ".")

    # Fallback: strip common wrappers, leave readable plain text.
    text = re.sub(r"\\mathrm\s*\{([^}]+)\}", r"\1", text)
    text = re.sub(r"\\text\s*\{([^}]+)\}", r"\1", text)
    text = text.replace("\\circ", "°").replace("^", "")
    return re.sub(r"\s+", " ", text).strip()


def _replace_inline_math(text: str) -> str:
    return _INLINE_MATH_RE.sub(lambda match: _normalize_math_fragment(match.group(1)), text)


def normalize_table_cell(text: str) -> str:
    """Convert LaTeX-ish table cell content to Telegram-safe plain text."""
    if not text or "$" not in text and "\\" not in text:
        return text

    out = text
    out = _LATEX_APPROX_TYPO_RE.sub("≈", out)
    out = _LATEX_APPROX_RE.sub("≈", out)
    out = _replace_inline_math(out)
    out = _ELLIPSIS_RANGE_RE.sub(" … ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out
