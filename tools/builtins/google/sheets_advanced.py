from __future__ import annotations

from typing import Any

from tools.builtins.google.sheets_core import (
    batch_update,
    require_sheet_id,
    require_spreadsheet_id,
    require_user_id,
)
from tools.builtins.google.sheets_client import run_sheets_call


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


def _rgb_color(arguments: dict[str, Any], key: str = "background_color") -> dict[str, Any] | None:
    color = arguments.get(key)
    return color if isinstance(color, dict) else None


def _validation_condition(arguments: dict[str, Any]) -> dict[str, Any]:
    condition_type = str(arguments.get("condition_type") or "ONE_OF_LIST").upper()
    allowed = {
        "ONE_OF_LIST",
        "NUMBER_BETWEEN",
        "NUMBER_GREATER",
        "NUMBER_GREATER_THAN_EQ",
        "NUMBER_LESS",
        "NUMBER_LESS_THAN_EQ",
        "TEXT_CONTAINS",
        "DATE_IS_VALID",
        "BOOLEAN",
    }
    if condition_type not in allowed:
        raise ValueError(f"condition_type must be one of: {', '.join(sorted(allowed))}")

    condition: dict[str, Any] = {"type": condition_type}
    if condition_type == "ONE_OF_LIST":
        values = arguments.get("values")
        if not isinstance(values, list) or not values:
            raise ValueError("values[] is required for ONE_OF_LIST (dropdown options)")
        condition["values"] = [{"userEnteredValue": str(v)} for v in values]
    elif condition_type == "NUMBER_BETWEEN":
        if arguments.get("min_value") is None or arguments.get("max_value") is None:
            raise ValueError("min_value and max_value are required for NUMBER_BETWEEN")
        condition["values"] = [
            {"userEnteredValue": str(arguments["min_value"])},
            {"userEnteredValue": str(arguments["max_value"])},
        ]
    elif condition_type in {
        "NUMBER_GREATER",
        "NUMBER_GREATER_THAN_EQ",
        "NUMBER_LESS",
        "NUMBER_LESS_THAN_EQ",
        "TEXT_CONTAINS",
    }:
        if arguments.get("condition_value") is None:
            raise ValueError("condition_value is required for this condition_type")
        condition["values"] = [{"userEnteredValue": str(arguments["condition_value"])}]
    return condition


async def set_data_validation_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    condition = _validation_condition(arguments)
    rule: dict[str, Any] = {
        "condition": condition,
        "showCustomUi": bool(arguments.get("show_dropdown", True)),
        "strict": bool(arguments.get("strict", True)),
    }
    if arguments.get("input_message"):
        rule["inputMessage"] = str(arguments["input_message"])

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"setDataValidation": {"range": _grid_range(arguments), "rule": rule}}],
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "condition_type": condition["type"],
        "validated": True,
    }


async def clear_data_validation_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"setDataValidation": {"range": _grid_range(arguments)}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "cleared": True}


def _conditional_format_rule(arguments: dict[str, Any]) -> dict[str, Any]:
    condition_type = str(arguments.get("condition_type") or "NUMBER_GREATER").upper()
    allowed = {
        "NUMBER_GREATER",
        "NUMBER_GREATER_THAN_EQ",
        "NUMBER_LESS",
        "NUMBER_LESS_THAN_EQ",
        "NUMBER_EQ",
        "TEXT_CONTAINS",
        "TEXT_STARTS_WITH",
        "TEXT_ENDS_WITH",
        "CUSTOM_FORMULA",
    }
    if condition_type not in allowed:
        raise ValueError(f"condition_type must be one of: {', '.join(sorted(allowed))}")

    values: list[dict[str, str]] = []
    if condition_type == "CUSTOM_FORMULA":
        formula = str(arguments.get("formula") or arguments.get("condition_value") or "").strip()
        if not formula:
            raise ValueError("formula or condition_value is required for CUSTOM_FORMULA")
        values = [{"userEnteredValue": formula}]
    else:
        if arguments.get("condition_value") is None:
            raise ValueError("condition_value is required")
        values = [{"userEnteredValue": str(arguments["condition_value"])}]

    fmt: dict[str, Any] = {}
    bg = _rgb_color(arguments)
    if bg:
        fmt["backgroundColor"] = bg
    text_color = _rgb_color(arguments, "text_color")
    if text_color:
        fmt.setdefault("textFormat", {})["foregroundColor"] = text_color
    if arguments.get("bold") is not None:
        fmt.setdefault("textFormat", {})["bold"] = bool(arguments["bold"])
    if not fmt:
        fmt["backgroundColor"] = {"red": 1.0, "green": 0.9, "blue": 0.9}

    return {
        "ranges": [_grid_range(arguments)],
        "booleanRule": {
            "condition": {"type": condition_type, "values": values},
            "format": fmt,
        },
    }


async def add_conditional_format_rule_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    rule_index = int(arguments.get("rule_index", 0))
    rule = _conditional_format_rule(arguments)

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"addConditionalFormatRule": {"rule": rule, "index": rule_index}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "rule_index": rule_index, "added": True}


async def delete_conditional_format_rule_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    rule_index = int(arguments.get("rule_index", 0))

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": rule_index}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id, "deleted_rule_index": rule_index}


async def set_basic_filter_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"setBasicFilter": {"filter": {"range": _grid_range(arguments)}}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "filter_enabled": True}


async def clear_basic_filter_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)

    await batch_update(user_id, spreadsheet_id, [{"clearBasicFilter": {"sheetId": sheet_id}}])
    return {"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id, "filter_cleared": True}


def _chart_source_range(sheet_id: int, start_row: int, end_row: int, start_col: int, end_col: int) -> dict[str, Any]:
    return {
        "sources": [
            {
                "sheetId": sheet_id,
                "startRowIndex": start_row,
                "endRowIndex": end_row,
                "startColumnIndex": start_col,
                "endColumnIndex": end_col,
            }
        ]
    }


def _build_chart_spec(arguments: dict[str, Any]) -> dict[str, Any]:
    sheet_id = require_sheet_id(arguments)
    start_row = int(arguments.get("start_row_index", 0))
    end_row = int(arguments.get("end_row_index"))
    start_col = int(arguments.get("start_column_index", 0))
    end_col = int(arguments.get("end_column_index"))
    domain_col = int(arguments.get("domain_column_index", start_col))
    has_header = bool(arguments.get("has_header_row", True))
    chart_type = str(arguments.get("chart_type") or "COLUMN").upper()
    title = str(arguments.get("title") or "").strip()

    if end_row <= start_row or end_col <= start_col:
        raise ValueError("end indices must be greater than start indices")
    if domain_col < start_col or domain_col >= end_col:
        raise ValueError("domain_column_index must be within the data range columns")

    data_start_row = start_row + (1 if has_header else 0)
    spec: dict[str, Any] = {}
    if title:
        spec["title"] = title

    if chart_type == "PIE":
        series_col = domain_col + 1 if domain_col + 1 < end_col else domain_col
        spec["pieChart"] = {
            "legendPosition": "RIGHT_LEGEND",
            "domain": {
                "sourceRange": _chart_source_range(sheet_id, data_start_row, end_row, domain_col, domain_col + 1)
            },
            "series": {
                "sourceRange": _chart_source_range(sheet_id, data_start_row, end_row, series_col, series_col + 1)
            },
        }
        return spec

    basic_type = chart_type if chart_type in {"BAR", "LINE", "COLUMN", "AREA"} else "COLUMN"
    series_cols = [col for col in range(start_col, end_col) if col != domain_col]
    if not series_cols and end_col - start_col >= 2:
        series_cols = [domain_col + 1 if domain_col + 1 < end_col else start_col + 1]
    series = []
    for col in series_cols:
        series.append(
            {
                "series": {"sourceRange": _chart_source_range(sheet_id, start_row, end_row, col, col + 1)},
                "targetAxis": "LEFT_AXIS",
            }
        )

    spec["basicChart"] = {
        "chartType": basic_type,
        "legendPosition": "RIGHT_LEGEND",
        "axis": [
            {"position": "BOTTOM_AXIS"},
            {"position": "LEFT_AXIS"},
        ],
        "domains": [
            {
                "domain": {
                    "sourceRange": _chart_source_range(sheet_id, data_start_row, end_row, domain_col, domain_col + 1)
                }
            }
        ],
        "series": series,
    }
    return spec


async def add_chart_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_id = require_sheet_id(arguments)
    anchor_row = int(arguments.get("anchor_row_index", arguments.get("end_row_index", 0)))
    anchor_col = int(arguments.get("anchor_column_index", arguments.get("end_column_index", 0)))
    spec = _build_chart_spec(arguments)

    result = await batch_update(
        user_id,
        spreadsheet_id,
        [
            {
                "addChart": {
                    "chart": {
                        "spec": spec,
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": sheet_id,
                                    "rowIndex": anchor_row,
                                    "columnIndex": anchor_col,
                                }
                            }
                        },
                    }
                }
            }
        ],
    )
    replies = result.get("replies") or []
    chart_id = None
    if replies:
        chart_id = (replies[0].get("addChart") or {}).get("chart", {}).get("chartId")
    return {
        "spreadsheet_id": spreadsheet_id,
        "chart_id": chart_id,
        "chart_type": str(arguments.get("chart_type") or "COLUMN").upper(),
    }


async def _find_chart_spec(user_id: int, spreadsheet_id: str, chart_id: int) -> dict[str, Any]:
    def _call(service):
        return (
            service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets(charts(chartId,spec))",
            )
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    for sheet in result.get("sheets") or []:
        for chart in sheet.get("charts") or []:
            if int(chart.get("chartId", -1)) == chart_id:
                return dict(chart.get("spec") or {})
    raise ValueError(f"chart_id {chart_id} not found in spreadsheet")


async def update_chart_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    chart_id = int(arguments.get("chart_id"))
    if arguments.get("title") is None and arguments.get("chart_type") is None:
        raise ValueError("Provide at least one of: title, chart_type (with data range to rebuild spec)")

    if arguments.get("chart_type") is not None:
        spec = _build_chart_spec(arguments)
    else:
        spec = await _find_chart_spec(user_id, spreadsheet_id, chart_id)
        if arguments.get("title") is not None:
            spec["title"] = str(arguments["title"]).strip()

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"updateChartSpec": {"chartId": chart_id, "spec": spec}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "chart_id": chart_id, "updated": True}


async def delete_chart_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    chart_id = int(arguments.get("chart_id"))

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"deleteEmbeddedObject": {"objectId": chart_id}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "deleted_chart_id": chart_id}


async def add_protected_range_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    protected: dict[str, Any] = {
        "range": _grid_range(arguments),
        "warningOnly": bool(arguments.get("warning_only", False)),
    }
    if arguments.get("description"):
        protected["description"] = str(arguments["description"]).strip()

    result = await batch_update(
        user_id,
        spreadsheet_id,
        [{"addProtectedRange": {"protectedRange": protected}}],
    )
    replies = result.get("replies") or []
    protected_range_id = None
    if replies:
        protected_range_id = (replies[0].get("addProtectedRange") or {}).get("protectedRange", {}).get(
            "protectedRangeId"
        )
    return {
        "spreadsheet_id": spreadsheet_id,
        "protected_range_id": protected_range_id,
        "warning_only": protected["warningOnly"],
    }


async def delete_protected_range_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    protected_range_id = int(arguments.get("protected_range_id"))

    await batch_update(
        user_id,
        spreadsheet_id,
        [{"deleteProtectedRange": {"protectedRangeId": protected_range_id}}],
    )
    return {"spreadsheet_id": spreadsheet_id, "deleted_protected_range_id": protected_range_id}
