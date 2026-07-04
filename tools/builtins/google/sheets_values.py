from __future__ import annotations

from typing import Any

from config import get_settings
from tools.builtins.google.sheets_a1 import sheet_data_range
from tools.builtins.google.sheets_client import run_sheets_call
from tools.builtins.google.sheets_core import (
    require_range,
    require_spreadsheet_id,
    require_user_id,
    value_input_option,
    value_render_option,
)
from tools.builtins.google.sheets_serialize import SPREADSHEET_GET_FIELDS, compact_batch_get, compact_value_range


async def get_values_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    range_a1 = require_range(arguments)
    render = value_render_option(arguments)
    major_dimension = str(arguments.get("major_dimension") or "ROWS").upper()
    max_cells = get_settings().sheets_max_cells

    def _call(service):
        return (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=range_a1,
                valueRenderOption=render,
                majorDimension=major_dimension,
            )
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    return {
        "spreadsheet_id": spreadsheet_id,
        **compact_value_range(result, max_cells=max_cells),
    }


async def _resolve_sheet_title(
    user_id: int,
    spreadsheet_id: str,
    *,
    sheet_title: str | None,
    sheet_id: int | None,
) -> str:
    if sheet_title and sheet_title.strip():
        return sheet_title.strip()
    if sheet_id is None:
        raise ValueError("Provide sheet_title or sheet_id")
    sheet_id = int(sheet_id)

    def _call(service):
        return (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields=SPREADSHEET_GET_FIELDS)
            .execute()
        )

    meta = await run_sheets_call(user_id, _call)
    for sheet in meta.get("sheets") or []:
        props = sheet.get("properties") or {}
        if props.get("sheetId") == sheet_id:
            title = str(props.get("title") or "").strip()
            if title:
                return title
            break
    raise ValueError(f"sheet_id {sheet_id} not found in spreadsheet")


async def read_sheet_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    sheet_title = await _resolve_sheet_title(
        user_id,
        spreadsheet_id,
        sheet_title=str(arguments.get("sheet_title") or "").strip() or None,
        sheet_id=arguments.get("sheet_id"),
    )
    max_rows = min(int(arguments.get("max_rows", 1000)), 10_000)
    range_a1 = sheet_data_range(sheet_title, max_rows=max_rows)

    payload = await get_values_handler(
        {
            **arguments,
            "spreadsheet_id": spreadsheet_id,
            "range": range_a1,
        }
    )
    payload["sheet_title"] = sheet_title
    payload["max_rows"] = max_rows
    return payload


async def update_values_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    range_a1 = require_range(arguments)
    values = arguments.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("values must be a non-empty 2D array")
    input_option = value_input_option(arguments)

    body = {"values": values}

    def _call(service):
        return (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_a1,
                valueInputOption=input_option,
                body=body,
            )
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    return {
        "spreadsheet_id": spreadsheet_id,
        "updated_range": result.get("updatedRange"),
        "updated_rows": result.get("updatedRows"),
        "updated_columns": result.get("updatedColumns"),
        "updated_cells": result.get("updatedCells"),
    }


async def append_values_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    range_a1 = str(arguments.get("range") or "").strip() or "Sheet1"
    values = arguments.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("values must be a non-empty 2D array")
    input_option = value_input_option(arguments)
    insert_option = str(arguments.get("insert_data_option") or "INSERT_ROWS").upper()
    if insert_option not in {"OVERWRITE", "INSERT_ROWS"}:
        raise ValueError("insert_data_option must be OVERWRITE or INSERT_ROWS")

    body = {"values": values}

    def _call(service):
        return (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_a1,
                valueInputOption=input_option,
                insertDataOption=insert_option,
                body=body,
            )
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    updates = result.get("updates") or {}
    return {
        "spreadsheet_id": spreadsheet_id,
        "table_range": result.get("tableRange"),
        "updated_range": updates.get("updatedRange"),
        "updated_rows": updates.get("updatedRows"),
        "updated_cells": updates.get("updatedCells"),
    }


async def clear_values_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    range_a1 = require_range(arguments)

    def _call(service):
        return (
            service.spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheet_id, range=range_a1, body={})
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    return {
        "spreadsheet_id": spreadsheet_id,
        "cleared_range": result.get("clearedRange"),
    }


async def batch_get_values_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    ranges = arguments.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        raise ValueError("ranges must be a non-empty array of A1 ranges")
    render = value_render_option(arguments)
    major_dimension = str(arguments.get("major_dimension") or "ROWS").upper()
    max_cells = get_settings().sheets_max_cells

    def _call(service):
        return (
            service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=ranges,
                valueRenderOption=render,
                majorDimension=major_dimension,
            )
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    return compact_batch_get(result, max_cells=max_cells)


async def batch_update_values_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    data = arguments.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("data must be a non-empty array of {range, values} objects")
    input_option = value_input_option(arguments)

    value_ranges = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each data item must be an object with range and values")
        range_a1 = str(item.get("range") or "").strip()
        values = item.get("values")
        if not range_a1 or not isinstance(values, list):
            raise ValueError("Each data item needs range and values")
        value_ranges.append({"range": range_a1, "values": values})

    body = {"valueInputOption": input_option, "data": value_ranges}

    def _call(service):
        return (
            service.spreadsheets()
            .values()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=body)
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    return {
        "spreadsheet_id": spreadsheet_id,
        "total_updated_cells": result.get("totalUpdatedCells"),
        "total_updated_rows": result.get("totalUpdatedRows"),
        "total_updated_columns": result.get("totalUpdatedColumns"),
        "responses": [
            {
                "updated_range": item.get("updatedRange"),
                "updated_cells": item.get("updatedCells"),
            }
            for item in result.get("responses") or []
        ],
    }


async def batch_clear_values_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = require_user_id()
    spreadsheet_id = require_spreadsheet_id(arguments)
    ranges = arguments.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        raise ValueError("ranges must be a non-empty array of A1 ranges")

    body = {"ranges": ranges}

    def _call(service):
        return (
            service.spreadsheets()
            .values()
            .batchClear(spreadsheetId=spreadsheet_id, body=body)
            .execute()
        )

    result = await run_sheets_call(user_id, _call)
    return {
        "spreadsheet_id": spreadsheet_id,
        "cleared_ranges": result.get("clearedRanges") or [],
    }
