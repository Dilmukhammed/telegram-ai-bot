---
skill_id: google.sheets
description: Google Sheets — read/write cells, structure, formatting, charts, validation, filters (OAuth)
tags: google, sheets
---

# Google Sheets skill

Use when the user asks about **spreadsheet cells, tabs, formulas, formatting, charts, filters, validation, or creating/editing Google Sheets**.

**Auth:** user OAuth — `google.auth.status` → `sheets_ready=true`. Same `/connect_google` as Calendar/Gmail/Drive. If `sheets_ready=false` after connect → user must re-run `/connect_google` (new scopes).

**Spreadsheet id** = Google Drive **file id**. Find via Drive, not Sheets API.

## Discovery

Load once per run: `skills.load` → `skill_id: "google.sheets"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full Sheets catalog (43 tools) | `{"mode":"catalog","tags":["google","sheets"]}` |
| Read values | `{"mode":"catalog","tags":["google","sheets","read","values"]}` |
| Write values | `{"mode":"catalog","tags":["google","sheets","write","values"]}` |
| Structure (tabs, rows/cols) | `{"mode":"catalog","tags":["google","sheets","structure"]}` |
| Formatting | `{"mode":"catalog","tags":["google","sheets","format"]}` |
| Charts | `{"mode":"catalog","tags":["google","sheets","charts"]}` |
| Validation / dropdowns | `{"mode":"catalog","tags":["google","sheets","validation"]}` |
| Filters | `{"mode":"catalog","tags":["google","sheets","filters"]}` |
| Protection | `{"mode":"catalog","tags":["google","sheets","protection"]}` |
| Rank | `{"mode":"rank","query":"update cell range","tags":["google","sheets"]}` |

## Standard flow (almost every task)

```
1. google.drive.search_files
     q: mimeType='application/vnd.google-apps.spreadsheet' [+ name contains '...']
   → spreadsheet_id (= file_id)

2. google.sheets.get_spreadsheet
   → tab titles, numeric sheet_id, grid sizes

3. Read or write cells (A1 notation: Sheet1!A1:D10)
```

**Do NOT** use `drive.export_file` for cell-level work — that's a whole-file CSV snapshot.  
**Do NOT** use Exa to find user's spreadsheets.

## Read values

| Tool | When |
|------|------|
| `get_values` | **One** A1 range — main read tool |
| `batch_get_values` | **Multiple** ranges in one call (headers + totals) |
| `read_sheet` | **Entire tab** (sugar; cap `max_rows`, default 1000) |

**A1 examples:** `Sheet1!A1:D10`, `Budget!B:B`, `'My Sheet'!A1:Z100`

**`value_render_option`:** `FORMATTED_VALUE` (default) | `UNFORMATTED_VALUE` | `FORMULA`

**`value_input_option` (writes):** `USER_ENTERED` (formulas/dates parsed) | `RAW` (literals)

## Write values

| Tool | When |
|------|------|
| `update_values` | Overwrite one range |
| `append_values` | Add rows after existing data (tables, logs) |
| `batch_update_values` | Multiple range writes at once |
| `clear_values` | Clear cell values (formatting stays) |
| `batch_clear_values` | Clear multiple ranges |

Prefer `USER_ENTERED` when writing formulas like `=SUM(A1:A10)` or dates.

## Structure (workbook & tabs)

| Tool | When |
|------|------|
| `create_spreadsheet` | **New file** (not a new tab on existing file) |
| `get_spreadsheet` | Metadata, tab list, sheet_ids |
| `update_spreadsheet_properties` | Rename **file**, locale, timezone |
| `add_sheet` | New tab on existing spreadsheet |
| `delete_sheet` | Remove tab — **`confirm=true`** |
| `duplicate_sheet` | Copy tab within workbook |
| `copy_sheet_to_spreadsheet` | Copy tab to another spreadsheet |
| `update_sheet_properties` | Rename/hide/freeze **tab** |
| `insert_dimension` / `delete_dimension` / `move_dimension` | Rows/columns — delete needs **`confirm=true`** |
| `update_dimension_properties` | Column width, hide rows/cols |

**Naming trap:** `update_spreadsheet_properties` = whole file; `update_sheet_properties` = one tab.

## Formatting & data ops (wave 3)

| Tool | When |
|------|------|
| `format_cells` | Bold, colors, number format |
| `merge_cells` / `unmerge_cells` | Merge range |
| `set_borders` | Cell borders |
| `auto_resize_columns` / `auto_resize_rows` | Fit content |
| `copy_paste_range` / `cut_paste_range` | Move/copy cell blocks |
| `sort_range` | Sort data in range |
| `find_replace` | Find & replace in sheet |
| `add_named_range` / `delete_named_range` | Named ranges |

## Validation, filters, charts, protection (wave 4)

| Tool | When |
|------|------|
| `set_data_validation` / `clear_data_validation` | Dropdowns, number rules |
| `add_conditional_format_rule` / `delete_conditional_format_rule` | Conditional colors |
| `set_basic_filter` / `clear_basic_filter` | AutoFilter on range |
| `add_chart` / `update_chart` / `delete_chart` | Charts |
| `add_protected_range` / `delete_protected_range` | Lock cells/ranges |

## Sharing & links

- **Share** spreadsheet → `google.drive.share_file` (not Sheets API).
- **Open in browser:** put docs.google.com/spreadsheets URL in final reply (plain or markdown) — inline button, stripped from text (via Drive link collector).

## Limits

- Max cells per read response: ~10,000 (`sheets_max_cells` in config).
- Read rate ~60/min; write ~30/min.
- `read_sheet` max_rows capped (up to 10,000) — for huge sheets use targeted `get_values` ranges.

## Destructive actions (require `confirm=true`)

- `delete_sheet`
- `delete_dimension`

Warn user before confirming.

## Anti-patterns

| Wrong | Right |
|-------|-------|
| `drive.export_file` for one cell | `get_values` / `update_values` |
| `create_spreadsheet` to add tab | `add_sheet` |
| `update_spreadsheet_properties` to rename tab | `update_sheet_properties` |
| Gmail to share sheet | `drive.share_file` |
| Invent `spreadsheet_id` | From `drive.search_files` or user URL |
| Exa web search for user's sheets | `drive.search_files` |

## Typical user requests

| User says | Flow |
|-----------|------|
| «Покажи ячейки A1:D10 в таблице Budget» | drive search → `get_spreadsheet` → `get_values` |
| «Добавь строку в конец» | `append_values` |
| «Создай новую таблицу» | `create_spreadsheet` |
| «Добавь лист Expenses» | `get_spreadsheet` → `add_sheet` |
| «Сделай жирным заголовок» | `format_cells` |
| «Поставь выпадающий список в колонке B» | `set_data_validation` |
| «Отсортируй по колонке C» | `sort_range` |
| «Замени все "foo" на "bar"» | `find_replace` |

## All 43 tools (prefix `google.sheets.`)

**Wave 1 — core:** `get_spreadsheet`, `create_spreadsheet`, `update_spreadsheet_properties`, `get_values`, `read_sheet`, `batch_get_values`, `update_values`, `append_values`, `clear_values`, `batch_update_values`, `batch_clear_values`

**Wave 2 — structure:** `add_sheet`, `delete_sheet`, `duplicate_sheet`, `copy_sheet_to_spreadsheet`, `update_sheet_properties`, `insert_dimension`, `delete_dimension`, `move_dimension`, `update_dimension_properties`

**Wave 3 — format/data:** `merge_cells`, `unmerge_cells`, `format_cells`, `set_borders`, `auto_resize_columns`, `auto_resize_rows`, `copy_paste_range`, `cut_paste_range`, `sort_range`, `find_replace`, `add_named_range`, `delete_named_range`

**Wave 4 — advanced:** `set_data_validation`, `clear_data_validation`, `add_conditional_format_rule`, `delete_conditional_format_rule`, `set_basic_filter`, `clear_basic_filter`, `add_chart`, `update_chart`, `delete_chart`, `add_protected_range`, `delete_protected_range`
