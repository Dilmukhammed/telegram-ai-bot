# Google Sheets — план интеграции (production)

Полный каталог tools, теги, auth, discovery flow и технические детали.  
**Файл для ревью перед кодом.** Целевой scope: агент **полноценно** управляет таблицами через **Sheets API v4** + **Drive** для файловых операций — по тому же паттерну, что Gmail (45 tools) и Maps (18 tools).

**Статус:** Sheets **complete** ✅ — все 4 волны, 43 tools — 2026-07-03.

---

## 1. Цель

Telegram-бот (Hermes Agent) получает cell-level доступ к Google Sheets пользователя через **тот же OAuth**, что Calendar / Gmail / Drive.

### Что пользователь может делать

- найти таблицу по имени (Drive) → прочитать/записать ячейки, диапазоны, формулы
- создать таблицу, добавить/удалить/переименовать вкладки
- вставить/удалить строки и столбцы, сортировать, find/replace
- форматировать (bold, цвет, number format, borders, merge)
- validation (dropdown), conditional formatting, charts
- защитить диапазоны от редактирования
- поделиться файлом (Drive permissions)

### Discovery flow (как Maps)

Агент **не** знает tools заранее. Каждый запрос:

```json
{"mode": "catalog", "tags": ["google", "sheets"]}
{"mode": "rank", "query": "read cells from spreadsheet range", "tags": ["google", "sheets", "read"]}
{"mode": "rank", "query": "append row to sheet", "tags": ["google", "sheets", "write", "values"]}
```

**Tool graph не используется** — все tools в registry с тегами + embedding index.

---

## 2. Auth

| | Calendar/Gmail/Drive/Sheets | Maps |
|---|----------------------------|------|
| Модель | User OAuth 2.0 | Project API key |
| Per-user | да | нет |

### 2.1 Scope

| Scope | Зачем |
|-------|-------|
| `https://www.googleapis.com/auth/spreadsheets` | read/write values, structure, formatting, charts, validation |

Добавляется в `GOOGLE_OAUTH_SCOPES` рядом с calendar, gmail, drive.

### 2.2 Guards

- `google.sheets.*` без токена → `GoogleNotConnectedError`
- токен без `spreadsheets` scope → `SheetsScopeMissingError` + `sheets_ready=false`
- Re-consent: `/disconnect_google` → `/connect_google`

### 2.3 GCP

Enable **Google Sheets API** в том же проекте, что Calendar.

### 2.4 Status flags

`google.auth.status` → `sheets_ready: true/false` (аналог `gmail_ready`, `drive_ready`).

---

## 3. Схема тегов

Baseline: **`google`, `sheets`** — у каждого tool.

| Tag | Смысл | Когда фильтровать |
|-----|-------|------------------|
| `read` | только чтение | «прочитай», «покажи», «сколько» |
| `write` | изменяет данные/структуру | «запиши», «добавь», «удали», «создай» |
| `values` | ячейки / ranges A1 | read/write cell data |
| `structure` | вкладки, rows/cols insert/delete | tabs, dimensions |
| `format` | визуальное оформление | bold, merge, borders, colors |
| `data` | сортировка, find/replace, named ranges | операции над содержимым |
| `validation` | dropdowns, rules | data validation |
| `charts` | диаграммы | add/update/delete chart |
| `filters` | filter views, basic filter | автофильтр |
| `protection` | protected ranges | lock cells |
| `sugar` | shortcut поверх другого tool | упрощённый UX для LLM |

**TAG_HINT_PROFILES** (добавить в `search_enrichment.py`):

```python
("google", "sheets"),
("google", "sheets", "read"),
("google", "sheets", "write"),
("google", "sheets", "values"),
("google", "sheets", "structure"),
("google", "sheets", "format"),
("google", "sheets", "validation"),
("google", "sheets", "charts"),
```

**Правило AND:** `tags=["google","sheets","read"]` → tool должен иметь **все** три тега.

---

## 4. Разделение Sheets vs Drive

| Задача | Сервис | Tool |
|--------|--------|------|
| Найти таблицу по имени | Drive | `google.drive.search_files` (`mimeType='application/vnd.google-apps.spreadsheet'`) |
| Share / permissions | Drive | `google.drive.share_file`, `list_permissions` |
| Trash / delete **файла** | Drive | `google.drive.trash_file`, `delete_file` |
| Export **всего файла** CSV snapshot | Drive | `google.drive.export_file` — только summary, **не** cell edit |
| Copy **файла** целиком | Drive | `google.drive.copy_file` |
| Read/write **ячеек** | Sheets | `google.sheets.*` |
| Tabs, format, charts | Sheets | `google.sheets.*` |

**Критично для prompt:** если нужны конкретные ячейки — **Sheets**, не Drive export.

---

## 5. Полный каталог — **42 tools**

Префикс: `google.sheets.*`  
Naming: `google.sheets.<verb>_<noun>` (как `google.drive.search_files`).

### Сводная таблица

| # | Tool | Tags | API family |
|---|------|------|------------|
| 1 | `get_spreadsheet` | read, structure | spreadsheets.get |
| 2 | `create_spreadsheet` | write, structure | spreadsheets.create |
| 3 | `update_spreadsheet_properties` | write, structure | batchUpdate |
| 4 | `get_values` | read, values | values.get |
| 5 | `read_sheet` | read, values, sugar | values.get (whole tab) |
| 6 | `batch_get_values` | read, values | values.batchGet |
| 7 | `update_values` | write, values | values.update |
| 8 | `append_values` | write, values | values.append |
| 9 | `clear_values` | write, values | values.clear |
| 10 | `batch_update_values` | write, values | values.batchUpdate |
| 11 | `batch_clear_values` | write, values | values.batchClear |
| 12 | `add_sheet` | write, structure | batchUpdate addSheet |
| 13 | `delete_sheet` | write, structure | batchUpdate deleteSheet |
| 14 | `duplicate_sheet` | write, structure | batchUpdate duplicateSheet |
| 15 | `copy_sheet_to_spreadsheet` | write, structure | sheets.copyTo |
| 16 | `update_sheet_properties` | write, structure | batchUpdate updateSheetProperties |
| 17 | `insert_dimension` | write, structure | batchUpdate insertDimension |
| 18 | `delete_dimension` | write, structure | batchUpdate deleteDimension |
| 19 | `move_dimension` | write, structure | batchUpdate moveDimension |
| 20 | `update_dimension_properties` | write, structure | batchUpdate updateDimensionProperties |
| 21 | `merge_cells` | write, format | batchUpdate mergeCells |
| 22 | `unmerge_cells` | write, format | batchUpdate unmergeCells |
| 23 | `format_cells` | write, format | batchUpdate repeatCell |
| 24 | `set_borders` | write, format | batchUpdate updateBorders |
| 25 | `auto_resize_columns` | write, format | batchUpdate autoResizeDimensions |
| 26 | `auto_resize_rows` | write, format | batchUpdate autoResizeDimensions |
| 27 | `copy_paste_range` | write, format, data | batchUpdate copyPaste |
| 28 | `cut_paste_range` | write, format, data | batchUpdate cutPaste |
| 29 | `sort_range` | write, data | batchUpdate sortRange |
| 30 | `find_replace` | write, data | batchUpdate findReplace |
| 31 | `add_named_range` | write, data | batchUpdate addNamedRange |
| 32 | `delete_named_range` | write, data | batchUpdate deleteNamedRange |
| 33 | `set_data_validation` | write, validation | batchUpdate setDataValidation |
| 34 | `clear_data_validation` | write, validation | batchUpdate setDataValidation (empty) |
| 35 | `add_conditional_format_rule` | write, format | batchUpdate addConditionalFormatRule |
| 36 | `delete_conditional_format_rule` | write, format | batchUpdate deleteConditionalFormatRule |
| 37 | `set_basic_filter` | write, filters | batchUpdate setBasicFilter |
| 38 | `clear_basic_filter` | write, filters | batchUpdate clearBasicFilter |
| 39 | `add_chart` | write, charts | batchUpdate addChart |
| 40 | `update_chart` | write, charts | batchUpdate updateChartSpec |
| 41 | `delete_chart` | write, charts | batchUpdate deleteEmbeddedObject |
| 42 | `add_protected_range` | write, protection | batchUpdate addProtectedRange |
| 43 | `delete_protected_range` | write, protection | batchUpdate deleteProtectedRange |

**Итого: 43 tools** (42 core + 1 sugar `read_sheet`).

---

## 6. Описание каждого tool

Формат: **когда выбирать**, **когда НЕ выбирать**, **параметры**, **returns**, **examples** (для embedding index).

---

### 6.1 Spreadsheet metadata (3)

#### `google.sheets.get_spreadsheet`

| | |
|---|---|
| **Когда** | Нужны **вкладки** (tab titles + numeric `sheet_id`), title файла, locale, timezone. **Первый шаг** после `drive.search_files` когда знаешь `spreadsheet_id`. |
| **НЕ когда** | Нужны только значения ячеек → `get_values`. Нужно найти файл по имени → `drive.search_files`. |
| **API** | `spreadsheets.get` |
| **Tags** | `google`, `sheets`, `read`, `structure` |
| **Params** | `spreadsheet_id` (required) — id из Drive или URL `.../d/{id}/edit` |
| **Returns** | `{spreadsheet_id, title, locale, time_zone, url, sheets: [{sheet_id, title, index, hidden, row_count, column_count, frozen_row_count, frozen_column_count}]}` |
| **Examples** | "list sheet tabs", "get spreadsheet metadata", "what worksheets exist" |

#### `google.sheets.create_spreadsheet`

| | |
|---|---|
| **Когда** | Создать **новую** Google таблицу с нуля. |
| **НЕ когда** | Добавить вкладку в существующую → `add_sheet`. Копировать файл → `drive.copy_file`. |
| **API** | `spreadsheets.create` |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `title` (optional, default "Untitled spreadsheet"), `sheet_titles[]` (optional initial tab names) |
| **Returns** | `{spreadsheet: {spreadsheet_id, title, url, sheets[]}}` |
| **Examples** | "create new spreadsheet", "new google sheet budget 2026" |

#### `google.sheets.update_spreadsheet_properties`

| | |
|---|---|
| **Когда** | Переименовать **файл** таблицы, сменить locale или timezone workbook. |
| **НЕ когда** | Переименовать вкладку → `update_sheet_properties`. |
| **API** | `batchUpdate` → `updateSpreadsheetProperties` |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `title?`, `locale?` (e.g. `ru_RU`), `time_zone?` (e.g. `Asia/Tashkent`) — хотя бы одно |
| **Returns** | `{spreadsheet_id, updated_properties}` |
| **Examples** | "rename spreadsheet", "set spreadsheet timezone" |

---

### 6.2 Values — read (3)

#### `google.sheets.get_values`

| | |
|---|---|
| **Когда** | Прочитать **один диапазон** A1 (`Sheet1!A1:D10`, `Budget!B:B`). Основной read tool. |
| **НЕ когда** | Несколько ranges → `batch_get_values`. Вся вкладка целиком → `read_sheet` (sugar). Snapshot CSV → `drive.export_file`. |
| **API** | `values.get` |
| **Tags** | `google`, `sheets`, `read`, `values` |
| **Params** | `spreadsheet_id`, `range` (required), `value_render_option` (`FORMATTED_VALUE` \| `UNFORMATTED_VALUE` \| `FORMULA`, default FORMATTED), `major_dimension` (`ROWS` \| `COLUMNS`) |
| **Returns** | `{range, values[][], row_count, cell_count, truncated?}` — truncate at `SHEETS_MAX_CELLS` (default 10000) |
| **Examples** | "read cells A1 to D10", "get values from sheet range", "read spreadsheet column B" |

#### `google.sheets.read_sheet`

| | |
|---|---|
| **Когда** | Прочитать **всю вкладку** или большой блок одним вызовом. Sugar: `range={tab_title}!A1:ZZ` или used range. |
| **НЕ когда** | Один маленький range → `get_values`. Несколько несмежных ranges → `batch_get_values`. |
| **API** | `values.get` (wrapper) |
| **Tags** | `google`, `sheets`, `read`, `values`, `sugar` |
| **Params** | `spreadsheet_id`, `sheet_title` or `sheet_id`, `max_rows?` (cap, default 1000) |
| **Returns** | same as `get_values` + `{sheet_title}` |
| **Examples** | "read entire sheet", "dump worksheet data", "show all rows in Sheet1" |

#### `google.sheets.batch_get_values`

| | |
|---|---|
| **Когда** | Прочитать **несколько ranges** за один API call (эффективнее). |
| **НЕ когда** | Один range → `get_values`. |
| **API** | `values.batchGet` |
| **Tags** | `google`, `sheets`, `read`, `values` |
| **Params** | `spreadsheet_id`, `ranges[]` (required), `value_render_option`, `major_dimension` |
| **Returns** | `{value_ranges: [{range, values[][], cell_count, truncated?}], range_count}` |
| **Examples** | "read multiple ranges", "get headers and totals from different sheets" |

---

### 6.3 Values — write (5)

#### `google.sheets.update_values`

| | |
|---|---|
| **Когда** | **Перезаписать** диапазон ячеек (overwrite). Записать таблицу, обновить одну ячейку, формулы. |
| **НЕ когда** | Добавить строки в конец → `append_values`. Несколько ranges → `batch_update_values`. |
| **API** | `values.update` |
| **Tags** | `google`, `sheets`, `write`, `values` |
| **Params** | `spreadsheet_id`, `range`, `values` (2D array), `value_input_option` (`USER_ENTERED` default — parses formulas/dates; `RAW` — literal) |
| **Returns** | `{updated_range, updated_rows, updated_columns, updated_cells}` |
| **Examples** | "write to cells", "update spreadsheet range", "set cell B5 to 100", "put formula in C1" |

#### `google.sheets.append_values`

| | |
|---|---|
| **Когда** | **Добавить строки** в конец таблицы (log, новая запись, import row). |
| **НЕ когда** | Overwrite existing cells → `update_values`. Insert blank rows → `insert_dimension`. |
| **API** | `values.append` |
| **Tags** | `google`, `sheets`, `write`, `values` |
| **Params** | `spreadsheet_id`, `values` (2D), `range?` (anchor tab, default `Sheet1`), `value_input_option`, `insert_data_option` (`INSERT_ROWS` \| `OVERWRITE`) |
| **Returns** | `{table_range, updated_range, updated_rows, updated_cells}` |
| **Examples** | "append row to sheet", "add new entry to spreadsheet", "log data to google sheet" |

#### `google.sheets.clear_values`

| | |
|---|---|
| **Когда** | Очистить **значения** в range (форматирование остаётся). |
| **НЕ когда** | Удалить строки физически → `delete_dimension`. Удалить вкладку → `delete_sheet`. |
| **API** | `values.clear` |
| **Tags** | `google`, `sheets`, `write`, `values` |
| **Params** | `spreadsheet_id`, `range` |
| **Returns** | `{cleared_range}` |
| **Examples** | "clear cells", "erase range A2:D100" |

#### `google.sheets.batch_update_values`

| | |
|---|---|
| **Когда** | Записать **несколько несмежных ranges** atomically. |
| **НЕ когда** | Один range → `update_values`. |
| **API** | `values.batchUpdate` |
| **Tags** | `google`, `sheets`, `write`, `values` |
| **Params** | `spreadsheet_id`, `data: [{range, values}]`, `value_input_option` |
| **Returns** | `{total_updated_cells, responses[]}` |
| **Examples** | "update multiple ranges", "write headers and footer in one call" |

#### `google.sheets.batch_clear_values`

| | |
|---|---|
| **Когда** | Clear нескольких ranges за раз. |
| **API** | `values.batchClear` |
| **Tags** | `google`, `sheets`, `write`, `values` |
| **Params** | `spreadsheet_id`, `ranges[]` |
| **Returns** | `{cleared_ranges[]}` |
| **Examples** | "clear multiple ranges", "reset several sections" |

---

### 6.4 Sheet tabs & dimensions (8)

#### `google.sheets.add_sheet`

| | |
|---|---|
| **Когда** | Новая **вкладка** в существующей таблице. |
| **НЕ когда** | Новый файл → `create_spreadsheet`. Копия вкладки → `duplicate_sheet`. |
| **API** | `batchUpdate` addSheet |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `title?`, `row_count?`, `column_count?`, `index?` |
| **Returns** | `{sheet_id, title}` |
| **Examples** | "add worksheet tab", "new sheet March" |

#### `google.sheets.delete_sheet`

| | |
|---|---|
| **Когда** | Удалить вкладку **навсегда**. |
| **Guard** | `confirm=true` required |
| **API** | batchUpdate deleteSheet |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `sheet_id`, `confirm` |
| **Examples** | "delete worksheet tab" |

#### `google.sheets.duplicate_sheet`

| | |
|---|---|
| **Когда** | Копия вкладки **внутри** того же файла. |
| **НЕ когда** | Копия в другой файл → `copy_sheet_to_spreadsheet`. |
| **API** | batchUpdate duplicateSheet |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `sheet_id`, `new_sheet_name?`, `insert_sheet_index?` |
| **Returns** | `{new_sheet_id, new_sheet_title}` |
| **Examples** | "duplicate sheet tab", "copy worksheet template" |

#### `google.sheets.copy_sheet_to_spreadsheet`

| | |
|---|---|
| **Когда** | Скопировать вкладку **в другую** таблицу. |
| **API** | `spreadsheets.sheets.copyTo` |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `source_spreadsheet_id`, `sheet_id`, `destination_spreadsheet_id` |
| **Returns** | `{destination_sheet_id, destination_spreadsheet_id}` |
| **Examples** | "copy sheet to another spreadsheet", "move tab to different file" |

#### `google.sheets.update_sheet_properties`

| | |
|---|---|
| **Когда** | Rename tab, hide/show, reorder, freeze header rows/cols. |
| **API** | batchUpdate updateSheetProperties |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `sheet_id`, `title?`, `hidden?`, `index?`, `frozen_row_count?`, `frozen_column_count?` |
| **Examples** | "rename sheet tab", "hide worksheet", "freeze first row" |

#### `google.sheets.insert_dimension`

| | |
|---|---|
| **Когда** | Вставить **пустые** строки или столбцы (shift existing). |
| **НЕ когда** | Append data rows → `append_values`. |
| **API** | batchUpdate insertDimension |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `sheet_id`, `dimension` (`ROWS`\|`COLUMNS`), `start_index`, `end_index`, `inherit_from_before?` |
| **Examples** | "insert rows", "add blank columns" |

#### `google.sheets.delete_dimension`

| | |
|---|---|
| **Когда** | Удалить строки/столбцы (сдвигает остальное). |
| **Guard** | `confirm=true` |
| **API** | batchUpdate deleteDimension |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `sheet_id`, `dimension`, `start_index`, `end_index`, `confirm` |
| **Examples** | "delete rows 5-10", "remove column C" |

#### `google.sheets.move_dimension`

| | |
|---|---|
| **Когда** | Переместить block строк/столбцов. |
| **API** | batchUpdate moveDimension |
| **Tags** | `google`, `sheets`, `write`, `structure` |
| **Params** | `spreadsheet_id`, `sheet_id`, `source_start`, `source_end`, `destination_index`, `dimension` |
| **Examples** | "move rows", "reorder columns" |

#### `google.sheets.update_dimension_properties`

| | |
|---|---|
| **Когда** | Row height, column width (pixels). |
| **API** | batchUpdate updateDimensionProperties |
| **Tags** | `google`, `sheets`, `write`, `structure`, `format` |
| **Params** | `spreadsheet_id`, `sheet_id`, `dimension`, `start_index`, `end_index`, `pixel_size?`, `hidden?` |
| **Examples** | "set column width", "hide columns D-F" |

---

### 6.5 Formatting (8)

#### `google.sheets.merge_cells`

| | |
|---|---|
| **Когда** | Merge rectangular range (header cells). |
| **API** | batchUpdate mergeCells |
| **Tags** | `google`, `sheets`, `write`, `format` |
| **Params** | `spreadsheet_id`, `sheet_id`, grid indices, `merge_type` (`MERGE_ALL`\|`MERGE_COLUMNS`\|`MERGE_ROWS`) |
| **Examples** | "merge header cells", "merge cells A1:D1" |

#### `google.sheets.unmerge_cells`

| | |
|---|---|
| **Когда** | Split merged cells. |
| **Tags** | `google`, `sheets`, `write`, `format` |

#### `google.sheets.format_cells`

| | |
|---|---|
| **Когда** | Bold, italic, font size, text/background color, number format (currency, percent, date). |
| **НЕ когда** | Только borders → `set_borders`. Только column width → `update_dimension_properties`. |
| **API** | batchUpdate repeatCell |
| **Tags** | `google`, `sheets`, `write`, `format` |
| **Params** | grid range + `bold?`, `italic?`, `font_size?`, `number_format_type?`, `number_format_pattern?`, `background_color?` `{red,green,blue}` 0..1 |
| **Examples** | "bold header row", "format as currency", "highlight cells yellow" |

#### `google.sheets.set_borders`

| | |
|---|---|
| **Когда** | Borders around cells (table grid lines). |
| **API** | batchUpdate updateBorders |
| **Tags** | `google`, `sheets`, `write`, `format` |
| **Params** | grid range + border style per side |
| **Examples** | "add borders to table", "grid lines around range" |

#### `google.sheets.auto_resize_columns`

| | |
|---|---|
| **Когда** | Auto-fit column width to content. |
| **API** | batchUpdate autoResizeDimensions (COLUMNS) |
| **Tags** | `google`, `sheets`, `write`, `format` |
| **Examples** | "auto fit columns", "resize columns to content" |

#### `google.sheets.auto_resize_rows`

| | |
|---|---|
| **Когда** | Auto-fit row height. |
| **API** | autoResizeDimensions (ROWS) |
| **Tags** | `google`, `sheets`, `write`, `format` |

#### `google.sheets.copy_paste_range`

| | |
|---|---|
| **Когда** | Copy block → paste elsewhere (values, format, or formulas). |
| **API** | batchUpdate copyPaste |
| **Tags** | `google`, `sheets`, `write`, `format`, `data` |
| **Params** | source grid + dest grid + `paste_type` (`PASTE_NORMAL`\|`PASTE_VALUES`\|`PASTE_FORMAT`\|`PASTE_FORMULA`) |
| **Examples** | "copy range to another place", "duplicate table block" |

#### `google.sheets.cut_paste_range`

| | |
|---|---|
| **Когда** | Move block (cut + paste). |
| **API** | batchUpdate cutPaste |
| **Tags** | `google`, `sheets`, `write`, `data` |

---

### 6.6 Data operations (5)

#### `google.sheets.sort_range`

| | |
|---|---|
| **Когда** | Sort table by column(s) ASC/DESC. |
| **API** | batchUpdate sortRange |
| **Tags** | `google`, `sheets`, `write`, `data` |
| **Params** | grid range + `sort_specs: [{dimension_index, sort_order}]` |
| **Examples** | "sort by column B descending", "sort table alphabetically" |

#### `google.sheets.find_replace`

| | |
|---|---|
| **Когда** | Bulk find/replace text (one sheet or all). |
| **API** | batchUpdate findReplace |
| **Tags** | `google`, `sheets`, `write`, `data` |
| **Params** | `find`, `replace`, `sheet_id?`, `match_case?`, `match_entire_cell?`, `search_by_regex?` |
| **Returns** | `{occurrences_changed}` |
| **Examples** | "replace all USD with UZS", "find and replace in sheet" |

#### `google.sheets.add_named_range`

| | |
|---|---|
| **Когда** | Create named range for formulas (`=SUM(Budget_Q1)`). |
| **API** | batchUpdate addNamedRange |
| **Tags** | `google`, `sheets`, `write`, `data` |
| **Params** | `name`, grid range |
| **Examples** | "create named range", "define range name Totals" |

#### `google.sheets.delete_named_range`

| | |
|---|---|
| **Когда** | Remove named range. |
| **API** | batchUpdate deleteNamedRange |
| **Tags** | `google`, `sheets`, `write`, `data` |

---

### 6.7 Validation (2)

#### `google.sheets.set_data_validation`

| | |
|---|---|
| **Когда** | Dropdown list, number range, date validation on cells. |
| **API** | batchUpdate setDataValidation |
| **Tags** | `google`, `sheets`, `write`, `validation` |
| **Params** | grid range + `condition_type` (`ONE_OF_LIST`, `NUMBER_BETWEEN`, …) + `values[]` for dropdown |
| **Examples** | "add dropdown to column", "validate numbers 1-100", "dropdown Active/Inactive" |

#### `google.sheets.clear_data_validation`

| | |
|---|---|
| **Когда** | Remove validation rules from range. |
| **Tags** | `google`, `sheets`, `write`, `validation` |

---

### 6.8 Conditional formatting (2)

#### `google.sheets.add_conditional_format_rule`

| | |
|---|---|
| **Когда** | Highlight cells by rule (value > X, text contains, color scale). |
| **API** | batchUpdate addConditionalFormatRule |
| **Tags** | `google`, `sheets`, `write`, `format` |
| **Params** | grid range + rule definition (booleanRule or gradientRule) |
| **Examples** | "highlight negative numbers red", "conditional formatting" |

#### `google.sheets.delete_conditional_format_rule`

| | |
|---|---|
| **Когда** | Remove rule by index. |
| **API** | batchUpdate deleteConditionalFormatRule |
| **Tags** | `google`, `sheets`, `write`, `format` |

---

### 6.9 Filters (2)

#### `google.sheets.set_basic_filter`

| | |
|---|---|
| **Когда** | Enable auto-filter on header row (dropdown filters in UI). |
| **API** | batchUpdate setBasicFilter |
| **Tags** | `google`, `sheets`, `write`, `filters` |
| **Examples** | "enable filter on table", "add autofilter to header" |

#### `google.sheets.clear_basic_filter`

| | |
|---|---|
| **Когда** | Remove auto-filter. |
| **API** | batchUpdate clearBasicFilter |
| **Tags** | `google`, `sheets`, `write`, `filters` |

---

### 6.10 Charts (3)

#### `google.sheets.add_chart`

| | |
|---|---|
| **Когда** | Insert chart from data range (bar, line, pie). |
| **API** | batchUpdate addChart |
| **Tags** | `google`, `sheets`, `write`, `charts` |
| **Params** | `chart_type`, source data range, position |
| **Returns** | `{chart_id}` |
| **Examples** | "create chart from data", "add pie chart" |

#### `google.sheets.update_chart`

| | |
|---|---|
| **Когда** | Change chart type, data range, title. |
| **API** | batchUpdate updateChartSpec |
| **Tags** | `google`, `sheets`, `write`, `charts` |

#### `google.sheets.delete_chart`

| | |
|---|---|
| **Когда** | Remove embedded chart. |
| **API** | batchUpdate deleteEmbeddedObject |
| **Tags** | `google`, `sheets`, `write`, `charts` |

---

### 6.11 Protection (2)

#### `google.sheets.add_protected_range`

| | |
|---|---|
| **Когда** | Lock range from editing (except specified editors). |
| **API** | batchUpdate addProtectedRange |
| **Tags** | `google`, `sheets`, `write`, `protection` |
| **Params** | grid range + `description?`, `warning_only?` |
| **Examples** | "protect header row", "lock formula cells" |

#### `google.sheets.delete_protected_range`

| | |
|---|---|
| **Когда** | Remove protection. |
| **API** | batchUpdate deleteProtectedRange |
| **Tags** | `google`, `sheets`, `write`, `protection` |

---

## 7. Типовые workflows (для agent prompt)

### Read table

```
drive.search_files(q="name contains 'Budget' and mimeType='application/vnd.google-apps.spreadsheet'")
→ sheets.get_spreadsheet(spreadsheet_id)  # tab names + sheet_ids
→ sheets.get_values(range="Sheet1!A1:F100")  # or read_sheet
```

### Append log row

```
drive.search_files → spreadsheet_id
→ sheets.append_values(values=[["2026-07-03", "100", "done"]])
```

### Update cell + format

```
sheets.update_values(range="B5", values=[[1500]])
→ sheets.format_cells(..., number_format_type="CURRENCY")
```

### Create report from scratch

```
sheets.create_spreadsheet(title="Report July")
→ sheets.update_values(range="Sheet1!A1:C1", values=[["Date","Amount","Status"]])
→ sheets.format_cells(bold=true, ...)
→ drive.share_file(file_id=spreadsheet_id, ...)
```

---

## 8. Волны реализации

| Wave | Tools | Count |
|------|-------|-------|
| **Sheets-1** | metadata (3) + values (7) + `read_sheet` | 11 | ✅ shipped |
| **Sheets-2** | tabs + dimensions (9) | 9 | ✅ shipped |
| **Sheets-3** | format (8) + data ops (4) | 12 | ✅ shipped |
| **Sheets-4** | validation + conditional + filters + charts + protection | 11 | ✅ shipped |
| **Total** | | **43** |

**Все 43 tools зарегистрированы** — полный production catalog.

---

## 9. Limits & config

| Env | Default | Purpose |
|-----|---------|---------|
| `SHEETS_MAX_CELLS` | 10000 | truncate read responses |
| `SHEETS_RATE_LIMIT_READ` | 60/60 | per-user read |
| `SHEETS_RATE_LIMIT_WRITE` | 30/60 | per-user write |

Guards: `delete_sheet`, `delete_dimension` → `confirm=true`.

---

## 10. Что сознательно НЕ включаем

| Item | Why |
|------|-----|
| `developerMetadata.*` | internal, не для чат-бота |
| `batchUpdateByDataFilter` | advanced, rare |
| `spreadsheets.values.batchUpdateByDataFilter` | same |
| Pivot tables API | нет dedicated API — manual via values |
| Apps Script execution | out of scope |

---

## 11. Checklist перед merge

- [ ] Ревью каталога (этот файл)
- [ ] Enable Sheets API in GCP
- [ ] OAuth scope + re-consent
- [ ] Реализация по волнам Sheets-1…4
- [ ] Handler tests (как `test_google_drive.py`)
- [ ] Live smoke: search → read → append → update
- [ ] `BOT_STATUS.md` update
- [ ] Embedding index rebuild (auto on bot start)

---

## 12. Сравнение с Maps (discovery)

| Aspect | Maps | Sheets |
|--------|------|--------|
| Auth | API key | OAuth `spreadsheets` |
| Baseline tags | `google`, `maps` | `google`, `sheets` |
| Family tags | geocoding, places, routes, static | values, structure, format, validation, charts |
| Catalog query | `{"mode":"catalog","tags":["google","maps","places"]}` | `{"mode":"catalog","tags":["google","sheets","values"]}` |
| Sugar tools | directions, travel_time, maps_link | read_sheet |
| Cross-service | standalone | **requires Drive** for file discovery |
