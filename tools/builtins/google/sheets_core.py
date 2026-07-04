from __future__ import annotations

from typing import Any

from tools.builtins.google.sheets_client import run_sheets_call
from tools.context import get_run_context


def require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def require_confirm(arguments: dict[str, Any], message: str) -> None:
    if arguments.get("confirm") is not True:
        raise ValueError(message)


def require_spreadsheet_id(arguments: dict[str, Any]) -> str:
    spreadsheet_id = str(arguments.get("spreadsheet_id") or "").strip()
    if not spreadsheet_id:
        raise ValueError("spreadsheet_id is required")
    return spreadsheet_id


def require_range(arguments: dict[str, Any]) -> str:
    range_a1 = str(arguments.get("range") or "").strip()
    if not range_a1:
        raise ValueError("range is required (A1 notation, e.g. Sheet1!A1:D10)")
    return range_a1


def require_sheet_id(arguments: dict[str, Any]) -> int:
    sheet_id = arguments.get("sheet_id")
    if sheet_id is None:
        raise ValueError("sheet_id is required (numeric id from get_spreadsheet)")
    return int(sheet_id)


def value_input_option(arguments: dict[str, Any]) -> str:
    option = str(arguments.get("value_input_option") or "USER_ENTERED").upper()
    if option not in {"RAW", "USER_ENTERED"}:
        raise ValueError("value_input_option must be RAW or USER_ENTERED")
    return option


def value_render_option(arguments: dict[str, Any]) -> str:
    option = str(arguments.get("value_render_option") or "FORMATTED_VALUE").upper()
    if option not in {"FORMATTED_VALUE", "UNFORMATTED_VALUE", "FORMULA"}:
        raise ValueError("value_render_option must be FORMATTED_VALUE, UNFORMATTED_VALUE, or FORMULA")
    return option


async def batch_update(
    user_id: int,
    spreadsheet_id: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    body = {"requests": requests}

    def _call(service):
        return (
            service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=body)
            .execute()
        )

    return await run_sheets_call(user_id, _call)
