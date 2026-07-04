from __future__ import annotations

from typing import Any

from tools.builtins.google.sheets_client import run_sheets_call
from tools.builtins.google.sheets_core import (
    batch_update,
    require_confirm,
    require_range,
    require_sheet_id,
    require_spreadsheet_id,
    require_user_id,
)
from tools.builtins.google.sheets_serialize import (
    SPREADSHEET_GET_FIELDS,
    build_spreadsheet_url,
    compact_spreadsheet,
)


def _grid_range(arguments: dict[str, Any]) -> dict[str, Any]:
    sheet_id = require_sheet_id(arguments)
    start_row = int(arguments.get("start_row_index", 0))
    end_row = int(arguments.get("end_row_index"))
    start_col = int(arguments.get("start_column_index", 0))
    end_col = int(arguments.get("end_column_index"))
    if end_row <= start_row or end_col <= start_col:
        raise ValueError("end indices must be greater than start indices")
    return {
        "sheetId": sheet_id,
        "startRowIndex": start_row,
        "endRowIndex": end_row,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col,
    }


async def get_spreadsheet_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)

    def _call(service):
        return (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields=SPREADSHEET_GET_FIELDS)
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    return {"spreadsheet": compact_spreadsheet(result)}


async def create_spreadsheet_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    title = str(arguments.get("title") or "Untitled spreadsheet").strip()
    sheet_titles = arguments.get("sheet_titles")
    body: dict[str, Any] = {"properties": {"title": title}}
    if isinstance(sheet_titles, list) and sheet_titles:
        body["sheets"] = [
            {"properties": {"title": str(name).strip() or f"Sheet{i + 1}"}}
            for i, name in enumerate(sheet_titles)
        ]

    def _call(service):
        return service.spreadsheets().create(body=body, fields=SPREADSHEET_GET_FIELDS).execute()

    result = await run_sheets_call(user_id, _call)
    return {"spreadsheet": compact_spreadsheet(result)}


async def update_spreadsheet_properties_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    properties: dict[str, Any] = {}
    if arguments.get("title") is not None:
        properties["title"] = str(arguments["title"]).strip()
    if arguments.get("locale") is not None:
        properties["locale"] = str(arguments["locale"]).strip()
    if arguments.get("time_zone") is not None:
        properties["timeZone"] = str(arguments["time_zone"]).strip()
    if not properties:
        raise ValueError("Provide at least one of: title, locale, time_zone")

    result = await batch_update(
        user_id,
        spreadsheet_id,
        [{"updateSpreadsheetProperties": {"properties": properties, "fields": ",".join(properties)}}],
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "updated_properties": properties,
        "replies": len(result.get("replies") or []),
    }


async def add_sheet_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    title = str(arguments.get("title") or "Sheet").strip()
    row_count = int(arguments.get("row_count", 1000))
    column_count = int(arguments.get("column_count", 26))
    index = arguments.get("index")

    properties: dict[str, Any] = {
        "title": title,
        "gridProperties": {"rowCount": row_count, "columnCount": column_count},
    }
    if index is not None:
        properties["index"] = int(index)

    result = await batch_update(
        user_id,
        spreadsheet_id,
        [{"addSheet": {"properties": properties}}],
    )
    replies = result.get("replies") or []
    sheet_props = {}
    if replies:
        sheet_props = (replies[0].get("addSheet") or {}).get("properties") or {}
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_id": sheet_props.get("sheetId"),
        "title": sheet_props.get("title"),
        "url": build_spreadsheet_url(spreadsheet_id),
    }


async def delete_sheet_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    require_confirm(arguments, "confirm=true is required — this permanently deletes a sheet tab.")
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)

    result = await batch_update(
        user_id,
        spreadsheet_id,
        [{"deleteSheet": {"sheetId": sheet_id}}],
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "deleted_sheet_id": sheet_id,
        "replies": len(result.get("replies") or []),
    }


async def duplicate_sheet_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    new_name = str(arguments.get("new_sheet_name") or "").strip() or None
    insert_index = arguments.get("insert_sheet_index")

    request: dict[str, Any] = {"sourceSheetId": sheet_id}
    if new_name:
        request["newSheetName"] = new_name
    if insert_index is not None:
        request["insertSheetIndex"] = int(insert_index)

    result = await batch_update(user_id, spreadsheet_id, [{"duplicateSheet": request}])
    replies = result.get("replies") or []
    props = {}
    if replies:
        props = (replies[0].get("duplicateSheet") or {}).get("properties") or {}
    return {
        "spreadsheet_id": spreadsheet_id,
        "source_sheet_id": sheet_id,
        "new_sheet_id": props.get("sheetId"),
        "new_sheet_title": props.get("title"),
    }


async def update_sheet_properties_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    properties: dict[str, Any] = {"sheetId": sheet_id}
    fields: list[str] = ["sheetId"]

    if arguments.get("title") is not None:
        properties["title"] = str(arguments["title"]).strip()
        fields.append("title")
    if arguments.get("hidden") is not None:
        properties["hidden"] = bool(arguments["hidden"])
        fields.append("hidden")
    if arguments.get("index") is not None:
        properties["index"] = int(arguments["index"])
        fields.append("index")
    grid: dict[str, Any] = {}
    if arguments.get("frozen_row_count") is not None:
        grid["frozenRowCount"] = int(arguments["frozen_row_count"])
    if arguments.get("frozen_column_count") is not None:
        grid["frozenColumnCount"] = int(arguments["frozen_column_count"])
    if grid:
        properties["gridProperties"] = grid
        fields.append("gridProperties")

    if len(fields) == 1:
        raise ValueError("Provide at least one property to update: title, hidden, index, frozen_row_count, frozen_column_count")

    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "updateSheetProperties": {
                    "properties": properties,
                    "fields": ",".join(fields),
                }
            }
        ],
    )
    return {"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id, "updated_fields": fields}


async def insert_dimension_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    dimension = str(arguments.get("dimension") or "ROWS").upper()
    if dimension not in {"ROWS", "COLUMNS"}:
        raise ValueError("dimension must be ROWS or COLUMNS")
    start_index = int(arguments.get("start_index", 0))
    end_index = int(arguments.get("end_index", start_index + 1))
    inherit_from_before = bool(arguments.get("inherit_from_before", True))

    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": dimension,
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                    "inheritFromBefore": inherit_from_before,
                }
            }
        ],
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_id": sheet_id,
        "dimension": dimension,
        "start_index": start_index,
        "end_index": end_index,
    }


async def delete_dimension_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    require_confirm(arguments, "confirm=true is required — this deletes rows/columns.")
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    dimension = str(arguments.get("dimension") or "ROWS").upper()
    if dimension not in {"ROWS", "COLUMNS"}:
        raise ValueError("dimension must be ROWS or COLUMNS")
    start_index = int(arguments.get("start_index", 0))
    end_index = int(arguments.get("end_index", start_index + 1))

    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": dimension,
                        "startIndex": start_index,
                        "endIndex": end_index,
                    }
                }
            }
        ],
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_id": sheet_id,
        "dimension": dimension,
        "start_index": start_index,
        "end_index": end_index,
    }


async def copy_sheet_to_spreadsheet_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    source_id = str(arguments.get("source_spreadsheet_id") or "").strip()
    if not source_id:
        raise ValueError("source_spreadsheet_id is required")
    destination_id = str(arguments.get("destination_spreadsheet_id") or "").strip()
    if not destination_id:
        raise ValueError("destination_spreadsheet_id is required")
    sheet_id = require_sheet_id(arguments)

    def _call(service):
        return (
            service.spreadsheets()
            .sheets()
            .copyTo(
                spreadsheetId=source_id,
                sheetId=sheet_id,
                body={"destinationSpreadsheetId": destination_id},
            )
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    props = result.get("properties") or {}
    return {
        "source_spreadsheet_id": source_id,
        "destination_spreadsheet_id": destination_id,
        "destination_sheet_id": props.get("sheetId"),
        "destination_sheet_title": props.get("title"),
        "url": build_spreadsheet_url(destination_id),
    }


async def move_dimension_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    dimension = str(arguments.get("dimension") or "ROWS").upper()
    if dimension not in {"ROWS", "COLUMNS"}:
        raise ValueError("dimension must be ROWS or COLUMNS")
    source_start = int(arguments.get("source_start", 0))
    source_end = int(arguments.get("source_end", source_start + 1))
    if "destination_index" not in arguments:
        raise ValueError("destination_index is required")
    destination_index = int(arguments["destination_index"])

    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "moveDimension": {
                    "source": {
                        "sheetId": sheet_id,
                        "dimension": dimension,
                        "startIndex": source_start,
                        "endIndex": source_end,
                    },
                    "destinationIndex": destination_index,
                }
            }
        ],
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_id": sheet_id,
        "dimension": dimension,
        "source_start": source_start,
        "source_end": source_end,
        "destination_index": destination_index,
    }


async def update_dimension_properties_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    dimension = str(arguments.get("dimension") or "COLUMNS").upper()
    if dimension not in {"ROWS", "COLUMNS"}:
        raise ValueError("dimension must be ROWS or COLUMNS")
    start_index = int(arguments.get("start_index", 0))
    end_index = int(arguments.get("end_index", start_index + 1))

    properties: dict[str, Any] = {}
    fields: list[str] = []
    if arguments.get("pixel_size") is not None:
        properties["pixelSize"] = int(arguments["pixel_size"])
        fields.append("pixelSize")
    if arguments.get("hidden") is not None:
        properties["hiddenByUser"] = bool(arguments["hidden"])
        fields.append("hiddenByUser")

    if not fields:
        raise ValueError("Provide at least one of: pixel_size, hidden")

    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": dimension,
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                    "properties": properties,
                    "fields": ",".join(fields),
                }
            }
        ],
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_id": sheet_id,
        "dimension": dimension,
        "start_index": start_index,
        "end_index": end_index,
        "updated_fields": fields,
    }


async def merge_cells_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    merge_type = str(arguments.get("merge_type") or "MERGE_ALL").upper()
    if merge_type not in {"MERGE_ALL", "MERGE_COLUMNS", "MERGE_ROWS"}:
        raise ValueError("merge_type must be MERGE_ALL, MERGE_COLUMNS, or MERGE_ROWS")

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"mergeCells": {"range": _grid_range(arguments), "mergeType": merge_type}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "merged": True}


async def unmerge_cells_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"unmergeCells": {"range": _grid_range(arguments)}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "unmerged": True}


async def format_cells_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    fields: list[str] = []
    cell: dict[str, Any] = {}
    user_format: dict[str, Any] = {}

    if arguments.get("bold") is not None:
        user_format.setdefault("textFormat", {})["bold"] = bool(arguments["bold"])
        fields.append("userEnteredFormat.textFormat.bold")
    if arguments.get("italic") is not None:
        user_format.setdefault("textFormat", {})["italic"] = bool(arguments["italic"])
        fields.append("userEnteredFormat.textFormat.italic")
    if arguments.get("font_size") is not None:
        user_format.setdefault("textFormat", {})["fontSize"] = int(arguments["font_size"])
        fields.append("userEnteredFormat.textFormat.fontSize")
    if arguments.get("number_format_type") is not None:
        number_format: dict[str, Any] = {"type": str(arguments["number_format_type"]).upper()}
        if arguments.get("number_format_pattern"):
            number_format["pattern"] = str(arguments["number_format_pattern"])
        user_format["numberFormat"] = number_format
        fields.append("userEnteredFormat.numberFormat")
    if arguments.get("background_color") is not None:
        color = arguments["background_color"]
        if isinstance(color, dict):
            user_format["backgroundColor"] = color
            fields.append("userEnteredFormat.backgroundColor")

    if not fields:
        raise ValueError(
            "Provide at least one format option: bold, italic, font_size, number_format_type, background_color"
        )

    cell["userEnteredFormat"] = user_format
    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "repeatCell": {
                    "range": _grid_range(arguments),
                    "cell": cell,
                    "fields": ",".join(fields),
                }
            }
        ],
    )
    return {"spreadsheet_id": spreadsheet_id, "formatted_fields": fields}


async def auto_resize_columns_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    start_col = int(arguments.get("start_column_index", 0))
    end_col = int(arguments.get("end_column_index", start_col + 1))

    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": start_col,
                        "endIndex": end_col,
                    }
                }
            }
        ],
    )
    return {"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id, "auto_resized": True}


async def auto_resize_rows_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    start_row = int(arguments.get("start_row_index", 0))
    end_row = int(arguments.get("end_row_index", start_row + 1))

    await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_row,
                        "endIndex": end_row,
                    }
                }
            }
        ],
    )
    return {"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id, "auto_resized": True}


def _border_side(style: str, width: int, color: dict[str, Any] | None) -> dict[str, Any]:
    side: dict[str, Any] = {"style": style, "width": width}
    if color:
        side["color"] = color
    return side


async def set_borders_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    style = str(arguments.get("border_style") or "SOLID").upper()
    if style not in {"SOLID", "DASHED", "DOTTED", "DOUBLE", "NONE"}:
        raise ValueError("border_style must be SOLID, DASHED, DOTTED, DOUBLE, or NONE")
    width = int(arguments.get("border_width", 1))
    color = arguments.get("border_color")
    border_color = color if isinstance(color, dict) else None
    outer = bool(arguments.get("outer_borders", True))
    inner = bool(arguments.get("inner_borders", False))
    if not outer and not inner:
        raise ValueError("Enable outer_borders and/or inner_borders")

    side = _border_side(style, width, border_color)
    update: dict[str, Any] = {"range": _grid_range(arguments)}
    if outer:
        for key in ("top", "bottom", "left", "right"):
            update[key] = dict(side)
    if inner:
        update["innerHorizontal"] = dict(side)
        update["innerVertical"] = dict(side)

    await batch_update(user_id, spreadsheet_id, [{"updateBorders": update}])
    return {
        "spreadsheet_id": spreadsheet_id,
        "border_style": style,
        "outer_borders": outer,
        "inner_borders": inner,
    }


async def copy_paste_range_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    paste_type = str(arguments.get("paste_type") or "PASTE_NORMAL").upper()
    if paste_type not in {"PASTE_NORMAL", "PASTE_VALUES", "PASTE_FORMAT", "PASTE_FORMULA"}:
        raise ValueError("paste_type must be PASTE_NORMAL, PASTE_VALUES, PASTE_FORMAT, or PASTE_FORMULA")

    def _source_grid() -> dict[str, Any]:
        end_row = arguments.get("source_end_row_index")
        end_col = arguments.get("source_end_column_index")
        if end_row is None or end_col is None:
            raise ValueError("source_end_row_index and source_end_column_index are required")
        return _grid_range(
            {
                "sheet_id": sheet_id,
                "start_row_index": arguments.get("source_start_row_index", 0),
                "end_row_index": end_row,
                "start_column_index": arguments.get("source_start_column_index", 0),
                "end_column_index": end_col,
            }
        )

    def _dest_grid() -> dict[str, Any]:
        end_row = arguments.get("dest_end_row_index")
        end_col = arguments.get("dest_end_column_index")
        if end_row is None or end_col is None:
            raise ValueError("dest_end_row_index and dest_end_column_index are required")
        return _grid_range(
            {
                "sheet_id": sheet_id,
                "start_row_index": arguments.get("dest_start_row_index", 0),
                "end_row_index": end_row,
                "start_column_index": arguments.get("dest_start_column_index", 0),
                "end_column_index": end_col,
            }
        )

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"copyPaste": {"source": _source_grid(), "destination": _dest_grid(), "pasteType": paste_type}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "copied": True, "paste_type": paste_type}


async def cut_paste_range_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    paste_type = str(arguments.get("paste_type") or "PASTE_NORMAL").upper()
    if paste_type not in {"PASTE_NORMAL", "PASTE_VALUES", "PASTE_FORMAT", "PASTE_FORMULA"}:
        raise ValueError("paste_type must be PASTE_NORMAL, PASTE_VALUES, PASTE_FORMAT, or PASTE_FORMULA")

    def _source_grid() -> dict[str, Any]:
        end_row = arguments.get("source_end_row_index")
        end_col = arguments.get("source_end_column_index")
        if end_row is None or end_col is None:
            raise ValueError("source_end_row_index and source_end_column_index are required")
        return _grid_range(
            {
                "sheet_id": sheet_id,
                "start_row_index": arguments.get("source_start_row_index", 0),
                "end_row_index": end_row,
                "start_column_index": arguments.get("source_start_column_index", 0),
                "end_column_index": end_col,
            }
        )

    def _dest_grid() -> dict[str, Any]:
        end_row = arguments.get("dest_end_row_index")
        end_col = arguments.get("dest_end_column_index")
        if end_row is None or end_col is None:
            raise ValueError("dest_end_row_index and dest_end_column_index are required")
        return _grid_range(
            {
                "sheet_id": sheet_id,
                "start_row_index": arguments.get("dest_start_row_index", 0),
                "end_row_index": end_row,
                "start_column_index": arguments.get("dest_start_column_index", 0),
                "end_column_index": end_col,
            }
        )

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"cutPaste": {"source": _source_grid(), "destination": _dest_grid(), "pasteType": paste_type}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "cut": True, "paste_type": paste_type}


async def find_replace_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    find_text = str(arguments.get("find") or "")
    replace_text = str(arguments.get("replace") or "")
    if not find_text:
        raise ValueError("find is required")
    match_case = bool(arguments.get("match_case", False))
    match_entire_cell = bool(arguments.get("match_entire_cell", False))
    search_by_regex = bool(arguments.get("search_by_regex", False))
    sheet_id = arguments.get("sheet_id")

    request: dict[str, Any] = {
        "find": find_text,
        "replacement": replace_text,
        "matchCase": match_case,
        "matchEntireCell": match_entire_cell,
        "searchByRegex": search_by_regex,
        "allSheets": sheet_id is None,
    }
    if sheet_id is not None:
        request["sheetId"] = int(sheet_id)

    result = await batch_update(user_id, spreadsheet_id, [{"findReplace": request}])
    replies = result.get("replies") or []
    occurrences = 0
    if replies:
        occurrences = int((replies[0].get("findReplace") or {}).get("occurrencesChanged") or 0)
    return {"spreadsheet_id": spreadsheet_id, "occurrences_changed": occurrences}


async def sort_range_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sort_specs = arguments.get("sort_specs")
    if not isinstance(sort_specs, list) or not sort_specs:
        raise ValueError("sort_specs must be a non-empty array of {dimension_index, sort_order}")

    specs = []
    for item in sort_specs:
        if not isinstance(item, dict):
            raise ValueError("Each sort_specs item must be an object")
        order = str(item.get("sort_order") or "ASCENDING").upper()
        if order not in {"ASCENDING", "DESCENDING"}:
            raise ValueError("sort_order must be ASCENDING or DESCENDING")
        specs.append(
            {
                "dimensionIndex": int(item["dimension_index"]),
                "sortOrder": order,
            }
        )

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"sortRange": {"range": _grid_range(arguments), "sortSpecs": specs}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "sorted": True, "sort_specs": len(specs)}


async def add_named_range_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    name = str(arguments.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    result = await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "addNamedRange": {
                    "namedRange": {
                        "name": name,
                        "range": _grid_range(arguments),
                    }
                }
            }
        ],
    )
    replies = result.get("replies") or []
    named_range_id = None
    if replies:
        named_range_id = (replies[0].get("addNamedRange") or {}).get("namedRange", {}).get("namedRangeId")
    return {
        "spreadsheet_id": spreadsheet_id,
        "name": name,
        "named_range_id": named_range_id,
    }


async def delete_named_range_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    named_range_id = str(arguments.get("named_range_id") or "").strip()
    if not named_range_id:
        raise ValueError("named_range_id is required (from add_named_range or get_spreadsheet)")

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"deleteNamedRange": {"namedRangeId": named_range_id}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "deleted_named_range_id": named_range_id}
