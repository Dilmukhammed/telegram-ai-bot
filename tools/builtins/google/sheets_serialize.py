from __future__ import annotations

from typing import Any

SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"

SPREADSHEET_GET_FIELDS = (
    "spreadsheetId,properties(title,locale,timeZone),spreadsheetUrl,sheets("
    "properties(sheetId,title,index,hidden,gridProperties),"
    "merges,basicFilter"
    ")"
)


def build_spreadsheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def compact_sheet_properties(sheet: dict[str, Any]) -> dict[str, Any]:
    props = sheet.get("properties") or {}
    grid = props.get("gridProperties") or {}
    return {
        "sheet_id": props.get("sheetId"),
        "title": props.get("title"),
        "index": props.get("index"),
        "hidden": props.get("hidden"),
        "row_count": grid.get("rowCount"),
        "column_count": grid.get("columnCount"),
        "frozen_row_count": grid.get("frozenRowCount"),
        "frozen_column_count": grid.get("frozenColumnCount"),
    }


def compact_spreadsheet(spreadsheet: dict[str, Any]) -> dict[str, Any]:
    props = spreadsheet.get("properties") or {}
    sheets = spreadsheet.get("sheets") or []
    spreadsheet_id = spreadsheet.get("spreadsheetId")
    return {
        "spreadsheet_id": spreadsheet_id,
        "title": props.get("title"),
        "locale": props.get("locale"),
        "time_zone": props.get("timeZone"),
        "url": spreadsheet.get("spreadsheetUrl") or (
            build_spreadsheet_url(spreadsheet_id) if spreadsheet_id else None
        ),
        "sheet_count": len(sheets),
        "sheets": [compact_sheet_properties(sheet) for sheet in sheets],
    }


def count_cells(values: list[list[Any]] | None) -> int:
    if not values:
        return 0
    return sum(len(row) for row in values)


def truncate_values(values: list[list[Any]], max_cells: int) -> tuple[list[list[Any]], bool]:
    if max_cells <= 0 or count_cells(values) <= max_cells:
        return values, False

    truncated: list[list[Any]] = []
    used = 0
    for row in values:
        if used >= max_cells:
            break
        remaining = max_cells - used
        if len(row) <= remaining:
            truncated.append(row)
            used += len(row)
        else:
            truncated.append(row[:remaining])
            used = max_cells
    return truncated, True


def compact_value_range(result: dict[str, Any], *, max_cells: int) -> dict[str, Any]:
    values = result.get("values") or []
    trimmed, truncated = truncate_values(values, max_cells)
    payload: dict[str, Any] = {
        "range": result.get("range"),
        "major_dimension": result.get("majorDimension"),
        "values": trimmed,
        "row_count": len(trimmed),
        "cell_count": count_cells(trimmed),
    }
    if truncated:
        payload["truncated"] = True
        payload["note"] = f"Values truncated to {max_cells} cells for LLM context."
    return payload


def compact_batch_get(result: dict[str, Any], *, max_cells: int) -> dict[str, Any]:
    ranges = []
    total_cells = 0
    for item in result.get("valueRanges") or []:
        compact = compact_value_range(item, max_cells=max(0, max_cells - total_cells))
        total_cells += compact.get("cell_count", 0)
        ranges.append(compact)
        if total_cells >= max_cells:
            break
    return {
        "spreadsheet_id": result.get("spreadsheetId"),
        "value_ranges": ranges,
        "range_count": len(ranges),
    }
