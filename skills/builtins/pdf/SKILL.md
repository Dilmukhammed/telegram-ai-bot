---
skill_id: pdf
description: PDF tools — read, OCR, render, edit pages, forms, security, create PDFs
tags: pdf, read, write
---

# PDF skill

Use when the user works with **PDF documents** — reading, searching, OCR, rendering, editing pages, forms, encryption, or creating new PDFs.

**Input:** all PDF tools accept either `file_ref` (from `google.drive.download_file`, `google.drive.export_file`, `google.gmail.get_attachment`, or a previous PDF tool) or `path` (workspace relative path like `uploads/report.pdf`).

**Output:** read tools return text/data inline. Write/create tools return `file_ref` → `telegram.send_file`.

## Discovery

Load once per run: `skills.load` → `skill_id: "pdf"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full PDF catalog | `{"mode":"catalog","tags":["pdf"]}` |
| Read tools only | `{"mode":"catalog","tags":["pdf","read"]}` |
| Write tools only | `{"mode":"catalog","tags":["pdf","write"]}` |
| Rank by task | `{"mode":"rank","query":"merge pdf pages","tags":["pdf","write"]}` |

## Read — extract content (9 tools)

| Tool | When to use |
|------|-------------|
| `pdf.extract_text` | Text from all pages or `pages: "1-5,8"`; `preserve_layout` for columns |
| `pdf.extract_tables` | Tables as rows; `strategy`: lines/strings/text |
| `pdf.extract_images` | Embedded images — `output: "vision"` (agent sees them), `"file_ref"`, or `"both"` |
| `pdf.read_metadata` | Title, author, dates, page count, encryption |
| `pdf.get_outline` | Table of contents / bookmarks tree |
| `pdf.search_text` | Find text with page + snippet context |
| `pdf.get_page_info` | Width, height, rotation, has_text, has_images |
| `pdf.extract_links` | Hyperlinks (internal + external) |
| `pdf.extract_forms` | AcroForm fields — names, types, values, options |

## OCR (2 tools)

Uses **Mistral OCR 4** (`POST /v1/ocr`, model `mistral-ocr-latest`). Configure `OCR_API_KEY` + `OCR_MODEL` in `.env`.

| Tool | When to use |
|------|-------------|
| `pdf.is_scanned` | Check if PDF is image-based before OCR |
| `pdf.ocr` | Mistral OCR for scanned PDFs; `pages` optional (1-indexed) |

## Render (1 tool)

| Tool | When to use |
|------|-------------|
| `pdf.render` | Pages → PNG; `dpi`, `scale` for thumbnails; `output: vision/file_ref/both` |

## Pages — manipulate (6 tools)

All return `file_ref` (new PDF).

| Tool | When to use |
|------|-------------|
| `pdf.split` | Split by `pages: "1-5,6-10"` or `every_n_pages` |
| `pdf.extract_pages` | Keep only `pages: "1-3,7"` |
| `pdf.merge` | Combine `file_refs: [ref1, ref2, ...]` |
| `pdf.rotate_pages` | `pages: {"1-3": 90, "5": 180}` |
| `pdf.delete_pages` | Remove `pages: "5,8-10"` |
| `pdf.reorder_pages` | `order: [3,1,2]` or `swap: [2,5]` |

## Edit content (4 tools)

| Tool | When to use |
|------|-------------|
| `pdf.overlay` | Watermark, header, footer, page numbers, custom text |
| `pdf.redact_text` | Black out text by `query` (irreversible) |
| `pdf.add_image` | Insert image via `image_file_ref` on a page |
| `pdf.add_annotations` | Highlight/strikethrough/underline/squiggly by text query |

## Forms — AcroForm (4 tools)

| Tool | When to use |
|------|-------------|
| `pdf.extract_forms` | List fields first |
| `pdf.fill_form` | `fields: {name: value}`; optional `flatten` |
| `pdf.flatten_form` | Make form read-only |
| `pdf.create_form` | Add fields to existing PDF |
| `pdf.reset_form` | Clear field values |

## Security (3 tools)

| Tool | When to use |
|------|-------------|
| `pdf.encrypt` | Password + optional permissions |
| `pdf.decrypt` | Remove encryption with password |
| `pdf.get_permissions` | Check encryption and permissions |

## Optimize (2 tools)

| Tool | When to use |
|------|-------------|
| `pdf.optimize` | `level`: light/medium/aggressive; optional `linearize` |
| `pdf.repair` | Fix corrupted PDF structure |

## Metadata & structure (3 tools)

| Tool | When to use |
|------|-------------|
| `pdf.set_metadata` | Title, author, subject, keywords, etc. |
| `pdf.set_outline` | Replace full bookmark tree |
| `pdf.add_bookmark` | Add single bookmark |

## Create (3 tools)

| Tool | When to use |
|------|-------------|
| `pdf.create` | Text or markdown → PDF |
| `pdf.create_from_images` | Images → multi-page PDF |
| `pdf.create_blank` | Empty PDF with N pages |

## Common workflows

### Read PDF from Google Drive
1. `google.drive.download_file` or `google.drive.export_file` → `file_ref`
2. `pdf.extract_text` with `file_ref`
3. Tables: `pdf.extract_tables`; scanned: `pdf.is_scanned` → `pdf.ocr`

### Read PDF from Telegram upload
1. User sends document → `uploads/filename.pdf` in workspace
2. `pdf.extract_text` with `path: "uploads/filename.pdf"`

### Merge and send
1. Download/export PDFs → `file_ref`s
2. `pdf.merge` → `file_ref`
3. `telegram.send_file` with that `file_ref`

### Fill a form
1. `pdf.extract_forms` → field names
2. `pdf.fill_form` with `fields: {"Name": "Alice", ...}`
3. `telegram.send_file` or `pdf.flatten_form` then send

### Redact sensitive data
1. `pdf.search_text` to locate
2. `pdf.redact_text` with `query`
3. `pdf.render` to verify visually
