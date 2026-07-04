from __future__ import annotations


def quote_sheet_title(title: str) -> str:
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def sheet_data_range(sheet_title: str, *, max_rows: int) -> str:
    title = sheet_title.strip()
    if not title:
        raise ValueError("sheet_title is required")
    max_rows = max(1, min(max_rows, 10_000))
    prefix = quote_sheet_title(title) if any(ch in title for ch in " '!") else title
    return f"{prefix}!A1:ZZ{max_rows}"
