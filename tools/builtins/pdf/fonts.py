from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

FONT_REGULAR = "PdfUnicode"
FONT_BOLD = "PdfUnicode-Bold"
FONT_MONO = "PdfUnicodeMono"

_BUILTIN_FONTS = frozenset(
    {"Helvetica", "Helvetica-Bold", "Times-Roman", "Courier", "Symbol", "ZapfDingbats"}
)


def _font_candidates() -> list[tuple[Path, Path, Path]]:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    fonts = windir / "Fonts"
    return [
        (
            fonts / "arial.ttf",
            fonts / "arialbd.ttf",
            fonts / "consola.ttf",
        ),
        (
            fonts / "segoeui.ttf",
            fonts / "segoeuib.ttf",
            fonts / "consola.ttf",
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        ),
        (
            Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSansMono.ttf"),
        ),
        (
            Path("/Library/Fonts/Arial.ttf"),
            Path("/Library/Fonts/Arial Bold.ttf"),
            Path("/Library/Fonts/Courier New.ttf"),
        ),
    ]


def _find_font_triplet() -> tuple[Path | None, Path | None, Path | None]:
    for regular, bold, mono in _font_candidates():
        if regular.is_file():
            bold_path = bold if bold.is_file() else regular
            mono_path = mono if mono.is_file() else regular
            return regular, bold_path, mono_path
    return None, None, None


@lru_cache(maxsize=1)
def ensure_pdf_fonts() -> tuple[str, str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular_path, bold_path, mono_path = _find_font_triplet()
    if regular_path is None:
        return "Helvetica", "Helvetica-Bold", "Courier"

    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(regular_path)))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold_path or regular_path)))
    pdfmetrics.registerFont(TTFont(FONT_MONO, str(mono_path or regular_path)))
    pdfmetrics.registerFontFamily(
        FONT_REGULAR,
        normal=FONT_REGULAR,
        bold=FONT_BOLD,
        italic=FONT_REGULAR,
        boldItalic=FONT_BOLD,
    )
    return FONT_REGULAR, FONT_BOLD, FONT_MONO


def resolve_body_font(requested: str | None) -> str:
    regular, _, _ = ensure_pdf_fonts()
    if not requested or requested in _BUILTIN_FONTS:
        return regular
    return requested


def resolve_bold_font(body_font: str) -> str:
    regular, bold, _ = ensure_pdf_fonts()
    if body_font == regular:
        return bold
    if body_font == "Helvetica":
        return "Helvetica-Bold"
    return body_font


def resolve_mono_font() -> str:
    _, _, mono = ensure_pdf_fonts()
    return mono
