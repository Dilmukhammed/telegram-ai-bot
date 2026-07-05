---
skill_id: pdf
description: PDF tools — extract text, tables, images, metadata, search, forms from PDF documents
tags: pdf, read
---

# PDF skill

Use when the user works with **PDF documents** — reading content, extracting tables, images, searching text, checking metadata, or inspecting forms.

**Input:** all PDF tools accept either `file_ref` (from `google.drive.download_file`, `google.drive.export_file`, `google.gmail.get_attachment`) or `path` (workspace relative path like `uploads/report.pdf`).

**Output:** extract tools return text/data inline. Tools that produce new PDFs return `file_ref` for `telegram.send_file`.

## Discovery

Load once per run: `skills.load` → `skill_id: "pdf"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full PDF catalog | `{"mode":"catalog","tags":["pdf"]}` |
| Read tools only | `{"mode":"catalog","tags":["pdf","read"]}` |
| Rank by task | `{"mode":"rank","query":"extract text from pdf","tags":["pdf","read"]}` |

## Read tools (Category 1)

| Tool | When to use |
|------|-------------|
| `pdf.extract_text` | Get text content from PDF (all pages or specific pages) |
| `pdf.extract_tables` | Extract tables as rows of cells |
| `pdf.extract_images` | Get embedded images — `output: "vision"` loads into agent context, `output: "file_ref"` for sending |
| `pdf.read_metadata` | Title, author, dates, page count, encryption status |
| `pdf.get_outline` | Table of contents / bookmarks |
| `pdf.search_text` | Find specific text in PDF with context snippets |
| `pdf.get_page_info` | Page dimensions, rotation, has_text, has_images |
| `pdf.extract_links` | Hyperlinks (internal and external URLs) |
| `pdf.extract_forms` | AcroForm fields — names, types, values, options |

## Common workflows

### Read a PDF from Google Drive
1. `google.drive.download_file` or `google.drive.export_file` → get `file_ref`
2. `pdf.extract_text` with `file_ref` → read content
3. If tables needed: `pdf.extract_tables` with same `file_ref`

### Read a PDF uploaded to Telegram
1. User sends document → saved to `uploads/` in workspace
2. `pdf.extract_text` with `path: "uploads/filename.pdf"`

### Search in a PDF
1. `pdf.search_text` with `query` → find matches with page numbers and context
2. `pdf.extract_text` with `pages` to read specific pages around matches

### Extract images from PDF
1. `pdf.extract_images` with `output: "vision"` → images loaded into agent context
2. Or `output: "file_ref"` → use `telegram.send_file` to send to user

### Check PDF forms
1. `pdf.extract_forms` → list all fields, types, current values
2. `pdf.fill_form` (Category 6) → fill the fields
