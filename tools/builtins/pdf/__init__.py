from __future__ import annotations

from typing import Any

from tools.builtins.pdf.extract import (
    _extract_images_handler,
    _extract_tables_handler,
    _extract_text_handler,
)
from tools.builtins.pdf.metadata import (
    _extract_links_handler,
    _get_outline_handler,
    _get_page_info_handler,
    _read_metadata_handler,
)
from tools.builtins.pdf.search import (
    _extract_forms_handler,
    _search_text_handler,
)
from tools.builtins.pdf.ocr import (
    _ocr_handler,
    _is_scanned_handler,
)
from tools.builtins.pdf.render import _render_handler
from tools.builtins.pdf.pages import (
    _split_handler,
    _extract_pages_handler,
    _merge_handler,
    _rotate_pages_handler,
    _delete_pages_handler,
    _reorder_pages_handler,
)
from tools.builtins.pdf.edit import (
    _overlay_handler,
    _redact_text_handler,
    _add_image_handler,
    _add_annotations_handler,
)
from tools.builtins.pdf.forms import (
    _fill_form_handler,
    _flatten_form_handler,
    _create_form_handler,
    _reset_form_handler,
)
from tools.builtins.pdf.security import (
    _encrypt_handler,
    _decrypt_handler,
    _get_permissions_handler,
)
from tools.builtins.pdf.optimize import (
    _optimize_handler,
    _repair_handler,
)
from tools.builtins.pdf.metadata_write import (
    _set_metadata_handler,
    _set_outline_handler,
    _add_bookmark_handler,
)
from tools.builtins.pdf.create import (
    _create_handler,
    _create_from_images_handler,
    _create_blank_handler,
)
from tools.schema import ToolSpec

_FILE_REF_PARAM = {
    "type": "string",
    "description": "file_ref from a previous tool call (e.g. google.drive.download_file, google.drive.export_file, google.gmail.get_attachment).",
}
_PATH_PARAM = {
    "type": "string",
    "description": "Path relative to user workspace root (e.g. uploads/doc.pdf).",
}
_PAGES_PARAM = {
    "type": "string",
    "description": "Page range, 1-indexed. Examples: '1-5', '1,3,7', '1-3,7-10'. Omit for all pages.",
}

_PDF_RATE_LIMIT = (30, 60)

PDF_EXTRACT_TEXT = ToolSpec(
    name="pdf.extract_text",
    description=(
        "Extract text from a PDF document. Returns text per page with page numbers. "
        "Use 'pages' to extract specific pages only. Set preserve_layout=false for plain text. "
        "Input: file_ref (from drive download/export) or path (workspace)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
            "preserve_layout": {
                "type": "boolean",
                "default": True,
                "description": "Preserve visual layout (columns, spacing) when extracting text.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters per page (default 8000).",
            },
        },
    },
    handler=_extract_text_handler,
    tags=("pdf", "read", "text"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "extract text from pdf",
        "read pdf content",
        "get text from page 3 of pdf",
        "read specific pages of pdf document",
    ),
)

PDF_EXTRACT_TABLES = ToolSpec(
    name="pdf.extract_tables",
    description=(
        "Extract tables from a PDF document. Returns tables as rows of cells with page numbers. "
        "Strategy 'lines' uses table borders, 'text' uses text alignment. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
            "strategy": {
                "type": "string",
                "enum": ["lines", "text", "strings"],
                "default": "lines",
                "description": "Table detection strategy: 'lines' (borders), 'text' (alignment), 'strings' (text position).",
            },
            "min_rows": {
                "type": "integer",
                "default": 2,
                "description": "Minimum rows for a valid table.",
            },
            "min_cols": {
                "type": "integer",
                "default": 2,
                "description": "Minimum columns for a valid table.",
            },
        },
    },
    handler=_extract_tables_handler,
    tags=("pdf", "read", "tables"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "extract tables from pdf",
        "find tables in pdf document",
        "get table data from pdf",
    ),
)

PDF_EXTRACT_IMAGES = ToolSpec(
    name="pdf.extract_images",
    description=(
        "Extract embedded images from a PDF document. "
        "output='vision' (default) loads images directly into agent vision context. "
        "output='file_ref' returns file_refs for telegram.send_file. "
        "output='both' does both. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
            "min_size": {
                "type": "integer",
                "default": 50,
                "description": "Minimum image size in bytes (skip tiny images).",
            },
            "output": {
                "type": "string",
                "enum": ["vision", "file_ref", "both"],
                "default": "vision",
                "description": "vision = load into agent context, file_ref = return refs for sending, both = do both.",
            },
        },
    },
    handler=_extract_images_handler,
    tags=("pdf", "read", "images"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=False,
    examples=(
        "extract images from pdf",
        "get pictures from pdf",
        "view images embedded in pdf",
    ),
)

PDF_READ_METADATA = ToolSpec(
    name="pdf.read_metadata",
    description=(
        "Read PDF metadata: title, author, subject, keywords, creator, producer, "
        "creation/modification dates, page count, encryption status, PDF version. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
        },
    },
    handler=_read_metadata_handler,
    tags=("pdf", "read", "metadata"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "get pdf metadata",
        "check pdf title and author",
        "is pdf encrypted",
        "how many pages in pdf",
    ),
)

PDF_GET_OUTLINE = ToolSpec(
    name="pdf.get_outline",
    description=(
        "Get PDF outline / table of contents (bookmarks). Returns a flat list with "
        "title, page number, and nesting level. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
        },
    },
    handler=_get_outline_handler,
    tags=("pdf", "read", "outline"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "get pdf table of contents",
        "list bookmarks in pdf",
        "show pdf outline",
    ),
)

PDF_SEARCH_TEXT = ToolSpec(
    name="pdf.search_text",
    description=(
        "Search for text in a PDF document. Returns matches with page numbers, "
        "matched text, and surrounding context snippet. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "query": {
                "type": "string",
                "description": "Text to search for.",
            },
            "pages": _PAGES_PARAM,
            "case_sensitive": {
                "type": "boolean",
                "default": False,
                "description": "Case-sensitive search.",
            },
            "whole_words": {
                "type": "boolean",
                "default": False,
                "description": "Match whole words only.",
            },
            "max_results": {
                "type": "integer",
                "default": 50,
                "description": "Maximum number of matches to return.",
            },
        },
        "required": ["query"],
    },
    handler=_search_text_handler,
    tags=("pdf", "read", "search"),
    cache_ttl_seconds=120,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "search text in pdf",
        "find word in pdf document",
        "look for specific text in pdf",
    ),
)

PDF_GET_PAGE_INFO = ToolSpec(
    name="pdf.get_page_info",
    description=(
        "Get detailed information about PDF pages: dimensions (width x height in points), "
        "rotation, character count, has_text, has_images. "
        "Input: file_ref or path. Use 'pages' for specific pages only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
        },
    },
    handler=_get_page_info_handler,
    tags=("pdf", "read", "page_info"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "get pdf page info",
        "check page dimensions in pdf",
        "which pages have images in pdf",
    ),
)

PDF_EXTRACT_LINKS = ToolSpec(
    name="pdf.extract_links",
    description=(
        "Extract hyperlinks from a PDF document. Returns internal page links and "
        "external URI links with page numbers and bounding boxes. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
        },
    },
    handler=_extract_links_handler,
    tags=("pdf", "read", "links"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "extract links from pdf",
        "find urls in pdf",
        "get hyperlinks from pdf document",
    ),
)

PDF_EXTRACT_FORMS = ToolSpec(
    name="pdf.extract_forms",
    description=(
        "Extract AcroForm fields from a PDF document. Returns field names, types "
        "(text/checkbox/radio/dropdown), current values, page numbers, required flag, "
        "and options for choice fields. Use pdf.fill_form to fill the fields. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
        },
    },
    handler=_extract_forms_handler,
    tags=("pdf", "read", "forms"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "extract form fields from pdf",
        "check pdf form fields",
        "what fields are in pdf form",
        "get acroform fields from pdf",
    ),
)

PDF_OCR = ToolSpec(
    name="pdf.ocr",
    description=(
        "Run OCR on a PDF document using a vision model. Renders pages to images "
        "and extracts text via API. Use for scanned PDFs or image-based PDFs where "
        "pdf.extract_text returns empty or garbled text. "
        "Requires OCR_API_KEY and OCR_MODEL configured. "
        "Input: file_ref or path. Use 'pages' for specific pages only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
            "lang": {
                "type": "string",
                "default": "auto",
                "description": "Language hint for OCR (e.g. 'ru', 'en', 'auto').",
            },
            "dpi": {
                "type": "integer",
                "default": 200,
                "description": "Render DPI (72-300). Higher = better quality but slower.",
            },
        },
    },
    handler=_ocr_handler,
    tags=("pdf", "read", "ocr"),
    cache_ttl_seconds=None,
    rate_limit=(10, 60),
    parallel_safe=False,
    examples=(
        "ocr scanned pdf",
        "extract text from scanned document",
        "read text from image pdf",
        "ocr specific pages of pdf",
    ),
)

PDF_IS_SCANNED = ToolSpec(
    name="pdf.is_scanned",
    description=(
        "Check whether a PDF is scanned (image-based) or has extractable text. "
        "Returns per-page analysis: character count, has_images, scanned flag. "
        "Use before pdf.ocr to decide if OCR is needed. "
        "Input: file_ref or path. Use 'pages' to check specific pages."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
        },
    },
    handler=_is_scanned_handler,
    tags=("pdf", "read", "ocr"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "check if pdf is scanned",
        "is pdf image-based or text-based",
        "does pdf need ocr",
        "check specific pages for scan",
    ),
)

PDF_RENDER = ToolSpec(
    name="pdf.render",
    description=(
        "Render PDF pages to PNG images. output='vision' (default) loads images "
        "directly into agent vision context — the agent can 'see' the page. "
        "output='file_ref' returns file_refs for telegram.send_file. "
        "output='both' does both. Use 'scale' (0.3-0.5) for thumbnails, "
        "'dpi' (72-300) for quality. 'width'/'height' for custom sizing. "
        "Input: file_ref or path. Max 20 pages per call."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": _PAGES_PARAM,
            "dpi": {
                "type": "integer",
                "default": 150,
                "description": "Render DPI (72-300). Higher = better quality but larger images.",
            },
            "scale": {
                "type": "number",
                "description": "Scale factor (e.g. 0.3 for thumbnail, 2.0 for high-res). Overrides dpi.",
            },
            "width": {
                "type": "integer",
                "description": "Target width in pixels (auto-scales height). Overrides dpi/scale.",
            },
            "height": {
                "type": "integer",
                "description": "Target height in pixels (auto-scales width). Overrides dpi/scale.",
            },
            "output": {
                "type": "string",
                "enum": ["vision", "file_ref", "both"],
                "default": "vision",
                "description": "vision = load into agent context, file_ref = return refs for sending, both = do both.",
            },
        },
    },
    handler=_render_handler,
    tags=("pdf", "read", "render"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=False,
    examples=(
        "render pdf page to image",
        "view pdf page visually",
        "show pdf page as picture",
        "render pdf thumbnail",
        "see what pdf page looks like",
    ),
)

PDF_SPLIT = ToolSpec(
    name="pdf.split",
    description=(
        "Split a PDF into multiple files. Use 'pages' to define groups "
        "(e.g. '1-5,6-10,11-end') or 'every_n_pages' to split uniformly. "
        "Returns a list of file_refs. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": {
                "type": "string",
                "description": "Page groups separated by commas, e.g. '1-5,6-10,11-end'.",
            },
            "every_n_pages": {
                "type": "integer",
                "description": "Split every N pages (alternative to 'pages').",
            },
        },
    },
    handler=_split_handler,
    tags=("pdf", "write", "pages"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "split pdf into parts",
        "divide pdf by pages",
        "split pdf every 5 pages",
    ),
)

PDF_EXTRACT_PAGES = ToolSpec(
    name="pdf.extract_pages",
    description=(
        "Extract specific pages from a PDF into a single new PDF. "
        "Example: pages='1-3,7,10-12' → one PDF with those pages. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": {
                "type": "string",
                "description": "Pages to extract, e.g. '1-3,7,10-12'.",
            },
        },
        "required": ["pages"],
    },
    handler=_extract_pages_handler,
    tags=("pdf", "write", "pages"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "extract pages from pdf",
        "get specific pages as new pdf",
        "pull pages 1-5 from pdf",
    ),
)

PDF_MERGE = ToolSpec(
    name="pdf.merge",
    description=(
        "Merge multiple PDFs into one. Pass a list of file_refs "
        "(from google.drive.download_file, pdf.split, etc.). "
        "Order is preserved in the output."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file_refs to merge (in order).",
            },
        },
        "required": ["file_refs"],
    },
    handler=_merge_handler,
    tags=("pdf", "write", "pages"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "merge pdfs together",
        "combine multiple pdf files",
        "join pdf documents",
    ),
)

PDF_ROTATE_PAGES = ToolSpec(
    name="pdf.rotate_pages",
    description=(
        "Rotate pages in a PDF. Pass 'pages' as an object mapping page ranges "
        "to rotation angles (90, 180, 270). Example: {\"1-3\": 90, \"5\": 180}. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": {
                "type": "object",
                "description": "Object mapping page ranges to angles. Example: {\"1-3\": 90, \"5\": 180}.",
            },
        },
        "required": ["pages"],
    },
    handler=_rotate_pages_handler,
    tags=("pdf", "write", "pages"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "rotate pdf pages",
        "turn page 90 degrees",
        "rotate pages 1-5 by 180",
    ),
)

PDF_DELETE_PAGES = ToolSpec(
    name="pdf.delete_pages",
    description=(
        "Delete pages from a PDF. Example: pages='5,8-10' removes pages 5, 8, 9, 10. "
        "Returns a new PDF without the specified pages. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "pages": {
                "type": "string",
                "description": "Pages to delete, e.g. '5,8-10'.",
            },
        },
        "required": ["pages"],
    },
    handler=_delete_pages_handler,
    tags=("pdf", "write", "pages"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "delete pages from pdf",
        "remove page 5 from pdf",
        "delete pages 8-10",
    ),
)

PDF_REORDER_PAGES = ToolSpec(
    name="pdf.reorder_pages",
    description=(
        "Reorder pages in a PDF. Use 'order' for full permutation "
        "(e.g. [3,1,2,5,4] — must list all pages exactly once) "
        "or 'swap' to swap two pages (e.g. [2,5] — swaps pages 2 and 5). "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "order": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Full page permutation, e.g. [3,1,2,5,4]. Must include all pages exactly once.",
            },
            "swap": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Swap two pages, e.g. [2,5]. Exactly 2 page numbers.",
            },
        },
    },
    handler=_reorder_pages_handler,
    tags=("pdf", "write", "pages"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "reorder pdf pages",
        "swap pages in pdf",
        "reverse page order in pdf",
        "move page 5 to position 1",
    ),
)

PDF_OVERLAY = ToolSpec(
    name="pdf.overlay",
    description=(
        "Add text overlay on PDF pages. mode='watermark' (diagonal centered, semi-transparent), "
        "'header' (top), 'footer' (bottom), 'page_numbers' (auto 'N / total'), 'text' (custom position). "
        "Supports {n}, {total}, {title}, {date} in content/format. "
        "position: 'top left', 'bottom center', 'top right', etc. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "content": {
                "type": "string",
                "description": "Text to overlay. Supports {n}, {total}, {title}, {date} placeholders.",
            },
            "mode": {
                "type": "string",
                "enum": ["watermark", "header", "footer", "page_numbers", "text"],
                "default": "text",
            },
            "pages": _PAGES_PARAM,
            "position": {
                "type": "string",
                "default": "bottom center",
                "description": "Position: 'top left', 'top center', 'top right', 'bottom left', 'bottom center', 'bottom right'.",
            },
            "margin": {
                "type": "number",
                "default": 36,
                "description": "Margin from edge in points (1 pt = 1/72 inch).",
            },
            "opacity": {
                "type": "number",
                "default": 1.0,
                "description": "Text opacity 0-1 (use 0.3 for watermark).",
            },
            "rotation": {
                "type": "number",
                "default": 0,
                "description": "Rotation in degrees (45 for watermark).",
            },
            "font_size": {
                "type": "number",
                "default": 12,
                "description": "Font size in points (40 for watermark).",
            },
            "color": {
                "type": "string",
                "default": "black",
                "description": "Color name (red, black, blue, gray, yellow, green) or hex (#FF0000).",
            },
            "format": {
                "type": "string",
                "description": "Format template for page_numbers mode, e.g. 'Page {n} of {total}'.",
            },
        },
        "required": ["content"],
    },
    handler=_overlay_handler,
    tags=("pdf", "write", "overlay"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "add watermark to pdf",
        "add page numbers to pdf",
        "add header to pdf",
        "add footer text to pdf",
        "stamp text on pdf pages",
    ),
)

PDF_REDACT_TEXT = ToolSpec(
    name="pdf.redact_text",
    description=(
        "Redact (black out) text in a PDF by searching for a query string. "
        "Applies a black overlay on matching text. This is irreversible in the output. "
        "Use pdf.render to verify redaction visually. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "query": {
                "type": "string",
                "description": "Text to find and redact.",
            },
            "pages": _PAGES_PARAM,
            "case_sensitive": {
                "type": "boolean",
                "default": False,
            },
        },
        "required": ["query"],
    },
    handler=_redact_text_handler,
    tags=("pdf", "write", "redact"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "redact text in pdf",
        "black out sensitive text in pdf",
        "censor text in pdf document",
    ),
)

PDF_ADD_IMAGE = ToolSpec(
    name="pdf.add_image",
    description=(
        "Insert an image onto a PDF page. The image is overlaid at the specified position. "
        "Use width/height to scale, or leave unset for original size. "
        "Input: file_ref or path (PDF) + image_file_ref (image from workspace/download)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "image_file_ref": {
                "type": "string",
                "description": "file_ref of the image to insert (from workspace, drive download, etc.).",
            },
            "page": {
                "type": "integer",
                "default": 1,
                "description": "Page number to add image to (1-indexed).",
            },
            "position": {
                "type": "string",
                "default": "bottom right",
                "description": "Position on page: 'top left', 'top center', 'bottom right', 'center', etc.",
            },
            "margin": {
                "type": "number",
                "default": 36,
                "description": "Margin from edge in points.",
            },
            "width": {
                "type": "number",
                "description": "Target width in points (auto-scales height).",
            },
            "height": {
                "type": "number",
                "description": "Target height in points (auto-scales width).",
            },
        },
        "required": ["image_file_ref"],
    },
    handler=_add_image_handler,
    tags=("pdf", "write", "image"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "add image to pdf page",
        "insert logo into pdf",
        "stamp image on pdf",
        "put picture on pdf page",
    ),
)

PDF_ADD_ANNOTATIONS = ToolSpec(
    name="pdf.add_annotations",
    description=(
        "Add annotations (highlight, strikethrough, underline, squiggly) to a PDF page "
        "by searching for text. The query text is found on the page and the annotation "
        "is applied. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "type": {
                "type": "string",
                "enum": ["highlight", "strikethrough", "underline", "squiggly"],
                "default": "highlight",
            },
            "query": {
                "type": "string",
                "description": "Text to find and annotate on the page.",
            },
            "page": {
                "type": "integer",
                "default": 1,
                "description": "Page number (1-indexed).",
            },
            "color": {
                "type": "string",
                "default": "yellow",
                "description": "Annotation color: yellow, red, green, blue, or hex (#FFFF00).",
            },
            "case_sensitive": {
                "type": "boolean",
                "default": False,
            },
        },
        "required": ["query"],
    },
    handler=_add_annotations_handler,
    tags=("pdf", "write", "annotations"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "highlight text in pdf",
        "underline text in pdf",
        "strikethrough text in pdf",
        "add highlight annotation to pdf",
    ),
)

PDF_FILL_FORM = ToolSpec(
    name="pdf.fill_form",
    description=(
        "Fill AcroForm fields in a PDF. Pass field name → value pairs. "
        "Checkbox: true/false. Radio/Dropdown: option value. Text: string. "
        "Set flatten=true to make fields read-only after filling. "
        "Use pdf.extract_forms first to get field names. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "fields": {
                "type": "object",
                "description": "Object mapping field names to values, e.g. {\"name\": \"Alice\", \"agree\": true}.",
            },
            "flatten": {
                "type": "boolean",
                "default": False,
                "description": "Make fields read-only after filling (cannot edit again).",
            },
        },
        "required": ["fields"],
    },
    handler=_fill_form_handler,
    tags=("pdf", "write", "forms"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "fill pdf form fields",
        "complete pdf application form",
        "set form field values in pdf",
    ),
)

PDF_FLATTEN_FORM = ToolSpec(
    name="pdf.flatten_form",
    description=(
        "Flatten AcroForm fields in a PDF — make all form fields read-only. "
        "Field values become permanent content. Use after pdf.fill_form. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
        },
    },
    handler=_flatten_form_handler,
    tags=("pdf", "write", "forms"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "flatten pdf form",
        "make pdf form read-only",
        "lock pdf form fields",
    ),
)

PDF_CREATE_FORM = ToolSpec(
    name="pdf.create_form",
    description=(
        "Add AcroForm fields to an existing PDF. Define fields with name, type, "
        "page, position (x, y, width, height), default_value, and options. "
        "Types: text, checkbox, dropdown, radio. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Field name (unique)."},
                        "type": {
                            "type": "string",
                            "enum": ["text", "checkbox", "dropdown", "radio"],
                            "default": "text",
                        },
                        "page": {"type": "integer", "default": 1},
                        "position": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                            },
                        },
                        "default_value": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Options for dropdown/radio.",
                        },
                    },
                },
                "description": "Array of field definitions.",
            },
        },
        "required": ["fields"],
    },
    handler=_create_form_handler,
    tags=("pdf", "write", "forms"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "create pdf form fields",
        "add text field to pdf",
        "add checkbox to pdf",
        "create dropdown in pdf",
    ),
)

PDF_RESET_FORM = ToolSpec(
    name="pdf.reset_form",
    description=(
        "Reset AcroForm field values in a PDF. Clears all fields or specific ones. "
        "Checkbox → false, text → empty, dropdown → empty. "
        "Input: file_ref or path. Pass 'fields' to reset specific fields only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific field names to reset. Omit to reset all fields.",
            },
        },
    },
    handler=_reset_form_handler,
    tags=("pdf", "write", "forms"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "reset pdf form",
        "clear form fields in pdf",
        "blank out pdf form values",
    ),
)

PDF_ENCRYPT = ToolSpec(
    name="pdf.encrypt",
    description=(
        "Encrypt a PDF with a password. Set permissions: print, copy, modify, annotate. "
        "owner_password is optional (defaults to user password). "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "password": {
                "type": "string",
                "description": "User password required to open the PDF.",
            },
            "owner_password": {
                "type": "string",
                "description": "Owner password (full access). Defaults to user password.",
            },
            "allow_print": {"type": "boolean", "default": True},
            "allow_copy": {"type": "boolean", "default": True},
            "allow_modify": {"type": "boolean", "default": True},
            "allow_annotate": {"type": "boolean", "default": True},
        },
        "required": ["password"],
    },
    handler=_encrypt_handler,
    tags=("pdf", "write", "security"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "encrypt pdf with password",
        "protect pdf with password",
        "add password to pdf",
        "restrict pdf permissions",
    ),
)

PDF_DECRYPT = ToolSpec(
    name="pdf.decrypt",
    description=(
        "Remove password protection from a PDF. Requires the correct password. "
        "Returns an unencrypted PDF. Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "password": {
                "type": "string",
                "description": "Password to decrypt the PDF.",
            },
        },
        "required": ["password"],
    },
    handler=_decrypt_handler,
    tags=("pdf", "write", "security"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "decrypt pdf",
        "remove password from pdf",
        "unlock pdf",
    ),
)

PDF_GET_PERMISSIONS = ToolSpec(
    name="pdf.get_permissions",
    description=(
        "Check PDF encryption status and permissions. Returns: encrypted, needs_password, "
        "permissions (print/copy/modify/annotate). Pass password to check with decryption. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "password": {
                "type": "string",
                "description": "Optional password to check permissions when encrypted.",
            },
        },
    },
    handler=_get_permissions_handler,
    tags=("pdf", "read", "security"),
    cache_ttl_seconds=300,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "check pdf permissions",
        "is pdf encrypted",
        "what permissions does pdf have",
        "check pdf password protection",
    ),
)

PDF_OPTIMIZE = ToolSpec(
    name="pdf.optimize",
    description=(
        "Compress and optimize a PDF. level='light' (fast, dedupe), "
        "'medium' (compress content streams), 'aggressive' (remove images, full compression). "
        "Set linearize=true for web fast-view. Returns old/new size and savings. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "level": {
                "type": "string",
                "enum": ["light", "medium", "aggressive"],
                "default": "medium",
                "description": "light = dedupe only, medium = compress streams, aggressive = remove images + full compress.",
            },
            "linearize": {
                "type": "boolean",
                "default": False,
                "description": "Linearize for web fast-view.",
            },
        },
    },
    handler=_optimize_handler,
    tags=("pdf", "write", "optimize"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "compress pdf",
        "reduce pdf file size",
        "optimize pdf for web",
        "shrink pdf",
    ),
)

PDF_REPAIR = ToolSpec(
    name="pdf.repair",
    description=(
        "Attempt to repair a damaged or corrupted PDF. Rebuilds page structure, "
        "skips corrupt pages, copies metadata. Returns a report of what was fixed. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
        },
    },
    handler=_repair_handler,
    tags=("pdf", "write", "optimize"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "repair damaged pdf",
        "fix corrupted pdf",
        "recover broken pdf file",
    ),
)

PDF_SET_METADATA = ToolSpec(
    name="pdf.set_metadata",
    description=(
        "Set PDF metadata fields: title, author, subject, keywords, creator, producer. "
        "Only provided fields are updated; others remain unchanged. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "title": {"type": "string", "description": "Document title."},
            "author": {"type": "string", "description": "Author name."},
            "subject": {"type": "string", "description": "Subject description."},
            "keywords": {"type": "string", "description": "Keywords (comma-separated)."},
            "creator": {"type": "string", "description": "Creator application."},
            "producer": {"type": "string", "description": "Producer application."},
        },
    },
    handler=_set_metadata_handler,
    tags=("pdf", "write", "metadata"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "set pdf title and author",
        "update pdf metadata",
        "change pdf document title",
        "set pdf keywords",
    ),
)

PDF_SET_OUTLINE = ToolSpec(
    name="pdf.set_outline",
    description=(
        "Set PDF outline / table of contents. Replaces existing outline. "
        "Pass an array of {title, page, level, children} entries. "
        "level=0 for top-level, 1+ for nested. page is 1-indexed. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "outline": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "page": {"type": "integer", "default": 1},
                        "level": {"type": "integer", "default": 0},
                        "children": {"type": "array", "items": {}},
                    },
                },
                "description": "Outline entries: [{title, page, level, children}].",
            },
        },
        "required": ["outline"],
    },
    handler=_set_outline_handler,
    tags=("pdf", "write", "outline"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "set pdf table of contents",
        "create pdf bookmarks",
        "add outline to pdf",
        "build pdf toc",
    ),
)

PDF_ADD_BOOKMARK = ToolSpec(
    name="pdf.add_bookmark",
    description=(
        "Add a single bookmark to a PDF. Does not replace existing outline. "
        "Use level=0 for top-level, 1+ for nested under existing bookmarks. "
        "Input: file_ref or path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": _FILE_REF_PARAM,
            "path": _PATH_PARAM,
            "title": {"type": "string", "description": "Bookmark title."},
            "page": {"type": "integer", "default": 1, "description": "Page number (1-indexed)."},
            "level": {"type": "integer", "default": 0, "description": "Nesting level (0=top)."},
        },
        "required": ["title"],
    },
    handler=_add_bookmark_handler,
    tags=("pdf", "write", "outline"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "add bookmark to pdf",
        "add single bookmark to pdf page",
        "bookmark page 5 in pdf",
    ),
)

PDF_CREATE = ToolSpec(
    name="pdf.create",
    description=(
        "Create a new PDF from text or Markdown content. format='markdown' (default) "
        "supports: headings (#/##/###), lists (-/*), bold (**), italic (*), code (```), "
        "tables (| col | col |), blockquotes (>), page breaks (---). "
        "format='text' renders plain text. Input: content string."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Text or Markdown content for the PDF.",
            },
            "format": {
                "type": "string",
                "enum": ["text", "markdown"],
                "default": "markdown",
            },
            "page_size": {
                "type": "string",
                "enum": ["A4", "Letter", "Legal", "A3", "A5"],
                "default": "A4",
            },
            "font": {
                "type": "string",
                "default": "Helvetica",
            },
            "font_size": {
                "type": "number",
                "default": 12,
            },
            "margin": {
                "type": "number",
                "default": 36,
                "description": "Page margin in points.",
            },
            "title": {
                "type": "string",
                "description": "PDF document title (metadata).",
            },
        },
        "required": ["content"],
    },
    handler=_create_handler,
    tags=("pdf", "write", "create"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "create pdf from text",
        "create pdf from markdown",
        "generate pdf document",
        "make pdf report",
    ),
)

PDF_CREATE_FROM_IMAGES = ToolSpec(
    name="pdf.create_from_images",
    description=(
        "Create a PDF from images — each image becomes one page. "
        "fit='contain' (default, fit within page) or 'stretch' (fill page). "
        "Pass image_file_refs (from workspace, drive download, etc.)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_file_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of image file_refs (in order, one per page).",
            },
            "page_size": {
                "type": "string",
                "enum": ["A4", "Letter", "Legal", "A3", "A5"],
                "default": "A4",
            },
            "fit": {
                "type": "string",
                "enum": ["contain", "stretch"],
                "default": "contain",
            },
        },
        "required": ["image_file_refs"],
    },
    handler=_create_from_images_handler,
    tags=("pdf", "write", "create"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "create pdf from images",
        "convert images to pdf",
        "make pdf from photos",
        "combine pictures into pdf",
    ),
)

PDF_CREATE_BLANK = ToolSpec(
    name="pdf.create_blank",
    description=(
        "Create a blank PDF with N empty pages. Useful as a template for "
        "subsequent pdf.overlay, pdf.add_text, pdf.create_form operations. "
        "page_size: A4, Letter, Legal, A3, A5."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pages": {
                "type": "integer",
                "default": 1,
                "description": "Number of blank pages (max 1000).",
            },
            "page_size": {
                "type": "string",
                "enum": ["A4", "Letter", "Legal", "A3", "A5"],
                "default": "A4",
            },
        },
    },
    handler=_create_blank_handler,
    tags=("pdf", "write", "create"),
    cache_ttl_seconds=None,
    rate_limit=_PDF_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "create blank pdf",
        "create empty pdf template",
        "make blank pdf with 5 pages",
    ),
)

PDF_TOOLS: tuple[ToolSpec, ...] = (
    PDF_EXTRACT_TEXT,
    PDF_EXTRACT_TABLES,
    PDF_EXTRACT_IMAGES,
    PDF_READ_METADATA,
    PDF_GET_OUTLINE,
    PDF_SEARCH_TEXT,
    PDF_GET_PAGE_INFO,
    PDF_EXTRACT_LINKS,
    PDF_EXTRACT_FORMS,
    PDF_OCR,
    PDF_IS_SCANNED,
    PDF_RENDER,
    PDF_SPLIT,
    PDF_EXTRACT_PAGES,
    PDF_MERGE,
    PDF_ROTATE_PAGES,
    PDF_DELETE_PAGES,
    PDF_REORDER_PAGES,
    PDF_OVERLAY,
    PDF_REDACT_TEXT,
    PDF_ADD_IMAGE,
    PDF_ADD_ANNOTATIONS,
    PDF_FILL_FORM,
    PDF_FLATTEN_FORM,
    PDF_CREATE_FORM,
    PDF_RESET_FORM,
    PDF_ENCRYPT,
    PDF_DECRYPT,
    PDF_GET_PERMISSIONS,
    PDF_OPTIMIZE,
    PDF_REPAIR,
    PDF_SET_METADATA,
    PDF_SET_OUTLINE,
    PDF_ADD_BOOKMARK,
    PDF_CREATE,
    PDF_CREATE_FROM_IMAGES,
    PDF_CREATE_BLANK,
)
