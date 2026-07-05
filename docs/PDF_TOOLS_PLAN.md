# PDF Tools — Implementation Plan

## Overview

50 инструментов для работы с PDF в `tools/builtins/pdf/`. Каждая категория обсуждается отдельно, после согласования добавляется в план.

## Dependencies

```
pypdf>=5.0          # BSD — манипуляция, метаданные, формы, шифрование
pdfplumber>=0.11    # MIT — текст, таблицы, координаты
reportlab>=4.0      # BSD — создание PDF
Pillow>=10.0        # MIT — изображения
pytesseract>=0.3.13 # Apache — OCR (system: tesseract-ocr)
pdf2image>=1.17     # MIT — рендер страниц (system: poppler-utils)
pypdfium2>=4.0      # BSD — альтернативный рендер без system dep
```

## Architecture

```
tools/builtins/pdf/
  __init__.py              # PDF_TOOLS tuple
  detect.py                # валидация PDF
  io.py                    # read/save → file_ref
  async_wrap.py            # asyncio.to_thread helper
  extract.py               # Category 1
  ocr.py                   # Category 2
  render.py                # Category 3
  pages.py                 # Category 4
  edit.py                  # Category 5
  forms_write.py           # Category 6
  security.py              # Category 7
  optimize.py              # Category 8
  metadata_write.py        # Category 9
  create.py                # Category 10
  convert.py               # Category 11
```

## Categories

### Category 1 — Извлечение контента (read) — 9 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 1 | `pdf.extract_text` | `file_ref` или `path`, `pages` (опц. `"1-5,8"` или `null` = весь PDF), `preserve_layout` (bool, default true), `max_chars` (опц.) | text постранично + page_count |
| 2 | `pdf.extract_tables` | `file_ref`/`path`, `pages`, `strategy` (lines/strings/text), `min_rows`, `min_cols` | `[{page, rows, bbox}]` |
| 3 | `pdf.extract_images` | `file_ref`/`path`, `pages`, `min_size`, `output` ("vision" — default, в контекст агента; "file_ref" — вернуть file_ref'ы; "both") | `[{page, file_ref?, data_url?, width, height, format}]` |
| 4 | `pdf.read_metadata` | `file_ref`/`path` | title, author, subject, keywords, creator, producer, dates, pages, encrypted, pdf_version |
| 5 | `pdf.get_outline` | `file_ref`/`path` | `[{title, page, level, children}]` |
| 6 | `pdf.search_text` | `file_ref`/`path`, `query`, `case_sensitive`, `whole_words`, `max_results` | `[{page, snippet, context}]` |
| 7 | `pdf.get_page_info` | `file_ref`/`path`, `pages` (опц.) | `[{page, width, height, rotation, num_chars, has_images, has_text}]` |
| 8 | `pdf.extract_links` | `file_ref`/`path`, `pages` | `[{page, type, uri/target, bbox}]` |
| 9 | `pdf.extract_forms` | `file_ref`/`path` | `[{name, type, value, page, required, options}]` |

### Category 2 — OCR — 2 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 10 | `pdf.ocr` | `file_ref`/`path`, `pages` (опц. `"1-5,8"` или `null` = весь PDF), `lang` (default "auto") | text постранично + page_count |
| 11 | `pdf.is_scanned` | `file_ref`/`path`, `pages` (опц., конкретная страница или диапазон) | `scanned: bool, text_ratio, image_pages: [...], pages_checked` |

### Category 3 — Рендеринг — 1 tool
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 12 | `pdf.render` | `file_ref`/`path`, `pages` (опц., одна или несколько, или весь PDF), `dpi` (72-300, default 150), `scale` (опц., для thumbnail — 0.3-0.5), `width`/`height` (опц. auto-scale), `output` ("vision" — default, "file_ref", "both") | `[{page, file_ref?, data_url?, width, height}]` |

### Category 4 — Манипуляция страницами — 6 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 13 | `pdf.split` | `file_ref`/`path`, `pages` ("1-5,6-10,11-end") или `every_n_pages` | `[{file_ref, pages, filename}]` |
| 14 | `pdf.extract_pages` | `file_ref`/`path`, `pages: "1-3,7,10-12"` | `file_ref` (1 PDF) |
| 15 | `pdf.merge` | `file_refs: [ref1, ref2, ...]` | `file_ref` (1 PDF) |
| 16 | `pdf.rotate_pages` | `file_ref`/`path`, `pages` (объект: `{"1-3": 90, "5": 180}`) | `file_ref` |
| 17 | `pdf.delete_pages` | `file_ref`/`path`, `pages: "5,8-10"` | `file_ref` |
| 18 | `pdf.reorder_pages` | `file_ref`/`path`, `order: [3,1,2,5,4]` (полная перестановка) ИЛИ `swap: [2,5]` (поменять две страницы местами) | `file_ref` |

### Category 5 — Редактирование контента — 5 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 19 | `pdf.overlay` | `file_ref`/`path`, `content` (текст), `pages`, `mode` ("watermark"/"header"/"footer"/"page_numbers"/"text"), `position` (top/bottom/left/right + margin или x,y pt), `opacity` (0-1), `rotation`, `font_size`, `color`, `format` ("{n}", "{total}", "{date}", "{title}") | `file_ref` |
| 20 | `pdf.redact_text` | `file_ref`/`path`, `query`, `pages` | `file_ref` (необратимо) |
| 21 | `pdf.add_image` | `file_ref`/`path`, `image_file_ref`, `page`, `position`, `width`/`height` (или auto) | `file_ref` |
| 22 | `pdf.add_annotations` | `file_ref`/`path`, `type` (highlight/strikethrough/underline/squiggly), `text`/`query`, `page`, `color` | `file_ref` |

### Category 6 — Формы (AcroForm) — 4 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 23 | `pdf.fill_form` | `file_ref`/`path`, `fields: {name: value}`, `flatten` (bool) | `file_ref` |
| 24 | `pdf.flatten_form` | `file_ref`/`path` | `file_ref` (read-only) |
| 25 | `pdf.create_form` | `file_ref`/`path` (существующий PDF), `fields: [{name, type, page, position, options, default_value}]` | `file_ref` |
| 26 | `pdf.reset_form` | `file_ref`/`path`, `fields` (опц., все если не указано) | `file_ref` |

### Category 7 — Безопасность — 3 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 27 | `pdf.encrypt` | `file_ref`/`path`, `password`, `owner_password` (опц.), `permissions` (print/copy/modify/annotate — bool each) | `file_ref` |
| 28 | `pdf.decrypt` | `file_ref`/`path`, `password` | `file_ref` |
| 29 | `pdf.get_permissions` | `file_ref`/`path`, `password` (опц.) | encrypted, permissions, needs_password |

### Category 8 — Оптимизация и ремонт — 2 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 30 | `pdf.optimize` | `file_ref`/`path`, `level` ("light"/"medium"/"aggressive"), `linearize` (bool, web fast-view) | `file_ref` + old_size/new_size |
| 31 | `pdf.repair` | `file_ref`/`path` | `file_ref` + report (что исправлено) |

### Category 9 — Метаданные и структура — 3 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 32 | `pdf.set_metadata` | `file_ref`/`path`, `title`, `author`, `subject`, `keywords`, `creator`, `producer` | `file_ref` |
| 33 | `pdf.set_outline` | `file_ref`/`path`, `outline: [{title, page, level}]` | `file_ref` |
| 34 | `pdf.add_bookmark` | `file_ref`/`path`, `title`, `page`, `level` | `file_ref` |

### Category 10 — Создание PDF — 3 tools
**Status:** ✅ agreed

| # | Tool | Параметры | Возвращает |
|---|------|-----------|-----------|
| 35 | `pdf.create` | `content` (text или Markdown), `format` ("text"/"markdown", default "markdown"), `page_size` (A4/Letter/Legal), `font`, `font_size`, `margins`, `title` | `file_ref` |
| 36 | `pdf.create_from_images` | `image_file_refs: [...]`, `page_size`, `fit` (contain/stretch), `orientation` | `file_ref` |
| 37 | `pdf.create_blank` | `pages` (count), `page_size` | `file_ref` |

### ~~Category 11 — Конвертация~~ — removed (overlaps with Categories 1, 3, 10)

## Progress

**Total: 37 инструментов**

| Category | Status | Tools |
|----------|--------|-------|
| 1 — Извлечение контента | ✅ | 9 |
| 2 — OCR | ✅ | 2 |
| 3 — Рендеринг | ✅ | 1 |
| 4 — Манипуляция страницами | ✅ | 6 |
| 5 — Редактирование контента | ✅ | 4 |
| 6 — Формы | ✅ | 4 |
| 7 — Безопасность | ✅ | 3 |
| 8 — Оптимизация | ✅ | 2 |
| 9 — Метаданные | ✅ | 3 |
| 10 — Создание | ✅ | 3 |
| ~~11 — Конвертация~~ | ❌ removed | 0 |
