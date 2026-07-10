from __future__ import annotations

from config import get_settings


def max_text_chars_per_page() -> int:
    return get_settings().pdf_max_text_chars_per_page


def max_tables() -> int:
    return get_settings().pdf_max_tables


def max_images() -> int:
    return get_settings().pdf_max_images


def max_search_results() -> int:
    return get_settings().pdf_max_search_results
