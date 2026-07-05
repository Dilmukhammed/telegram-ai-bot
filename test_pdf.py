import io
import os
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    PageBreak,
)

from tools.builtins.pdf.io import parse_pages_spec
from tools.context import RunContext, set_run_context, reset_run_context
from tools.run_files import RunFileStore, set_run_file_store, reset_run_file_store
from tools.workspace.vision_pending import clear_pending_vision, take_pending_vision


def _make_test_pdf() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Hello PDF Test Document", styles["Title"]),
        Spacer(1, 12),
        Paragraph("This is page one with some text to search for.", styles["Normal"]),
        Spacer(1, 20),
        Table(
            [["Name", "Age", "City"], ["Alice", "30", "Tashkent"], ["Bob", "25", "Samarkand"]],
            style=[("Grid", (0, 0), (-1, -1), 0.5, colors.black)],
        ),
        Spacer(1, 20),
        Paragraph("Another paragraph with keyword: unicorn.", styles["Normal"]),
        PageBreak(),
        Paragraph("Page Two", styles["Heading1"]),
        Spacer(1, 12),
        Paragraph("Second page content with another keyword: dragon.", styles["Normal"]),
        PageBreak(),
        Paragraph("Page Three", styles["Heading1"]),
        Spacer(1, 12),
        Paragraph("Final page with unicorn again.", styles["Normal"]),
    ]
    doc.build(story)
    return buf.getvalue()


class PdfToolsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._pdf_data = _make_test_pdf()
        self._ctx_token = set_run_context(RunContext(user_id=1))
        self._store = RunFileStore(run_id="testrun01", user_id=1)
        self._store_token = set_run_file_store(self._store)
        clear_pending_vision()

        stored = self._store.save(
            self._pdf_data, filename="test.pdf", mime_type="application/pdf"
        )
        self._file_ref = stored["file_ref"]

    async def asyncTearDown(self) -> None:
        reset_run_context(self._ctx_token)
        reset_run_file_store(self._store_token)
        self._store.cleanup()
        clear_pending_vision()

    async def test_extract_text_all_pages(self) -> None:
        from tools.builtins.pdf.extract import _extract_text_handler

        result = await _extract_text_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["pages_extracted"], 3)
        texts = [p["text"] for p in result["pages"]]
        self.assertTrue(any("Hello PDF" in t for t in texts))
        self.assertTrue(any("Page Two" in t for t in texts))
        self.assertTrue(any("Page Three" in t for t in texts))

    async def test_extract_text_specific_pages(self) -> None:
        from tools.builtins.pdf.extract import _extract_text_handler

        result = await _extract_text_handler(
            {"file_ref": self._file_ref, "pages": "2-3"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pages_extracted"], 2)
        page_nums = [p["page"] for p in result["pages"]]
        self.assertEqual(page_nums, [2, 3])

    async def test_extract_text_single_page(self) -> None:
        from tools.builtins.pdf.extract import _extract_text_handler

        result = await _extract_text_handler(
            {"file_ref": self._file_ref, "pages": "1"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pages_extracted"], 1)
        self.assertEqual(result["pages"][0]["page"], 1)

    async def test_extract_text_preserve_layout(self) -> None:
        from tools.builtins.pdf.extract import _extract_text_handler

        result_plain = await _extract_text_handler(
            {"file_ref": self._file_ref, "preserve_layout": False}
        )
        result_layout = await _extract_text_handler(
            {"file_ref": self._file_ref, "preserve_layout": True}
        )
        self.assertTrue(result_plain["ok"])
        self.assertTrue(result_layout["ok"])
        self.assertEqual(result_plain["page_count"], 3)
        self.assertEqual(result_layout["page_count"], 3)

    async def test_extract_text_no_input_error(self) -> None:
        from tools.builtins.pdf.extract import _extract_text_handler

        result = await _extract_text_handler({})
        self.assertFalse(result.get("ok", False))

    async def test_extract_tables(self) -> None:
        from tools.builtins.pdf.extract import _extract_tables_handler

        result = await _extract_tables_handler(
            {"file_ref": self._file_ref, "strategy": "text"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertGreaterEqual(result["tables_found"], 1)
        table = result["tables"][0]
        self.assertEqual(table["page"], 1)
        self.assertGreaterEqual(table["row_count"], 2)
        self.assertGreaterEqual(table["col_count"], 2)

    async def test_extract_tables_min_rows(self) -> None:
        from tools.builtins.pdf.extract import _extract_tables_handler

        result = await _extract_tables_handler(
            {"file_ref": self._file_ref, "min_rows": 10}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["tables_found"], 0)

    async def test_extract_images(self) -> None:
        from tools.builtins.pdf.extract import _extract_images_handler

        result = await _extract_images_handler(
            {"file_ref": self._file_ref, "output": "file_ref"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)

    async def test_extract_images_vision_mode(self) -> None:
        from tools.builtins.pdf.extract import _extract_images_handler

        result = await _extract_images_handler(
            {"file_ref": self._file_ref, "output": "vision"}
        )
        self.assertTrue(result["ok"])

    async def test_read_metadata(self) -> None:
        from tools.builtins.pdf.metadata import _read_metadata_handler

        result = await _read_metadata_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertFalse(result["encrypted"])

    async def test_get_outline(self) -> None:
        from tools.builtins.pdf.metadata import _get_outline_handler

        result = await _get_outline_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertIsInstance(result["outline"], list)

    async def test_get_page_info(self) -> None:
        from tools.builtins.pdf.metadata import _get_page_info_handler

        result = await _get_page_info_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(len(result["pages"]), 3)
        page1 = result["pages"][0]
        self.assertEqual(page1["page"], 1)
        self.assertGreater(page1["width_pt"], 0)
        self.assertGreater(page1["height_pt"], 0)
        self.assertTrue(page1["has_text"])

    async def test_get_page_info_specific_pages(self) -> None:
        from tools.builtins.pdf.metadata import _get_page_info_handler

        result = await _get_page_info_handler(
            {"file_ref": self._file_ref, "pages": "1"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["pages"]), 1)
        self.assertEqual(result["pages"][0]["page"], 1)

    async def test_extract_links(self) -> None:
        from tools.builtins.pdf.metadata import _extract_links_handler

        result = await _extract_links_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertIsInstance(result["links"], list)

    async def test_search_text_found(self) -> None:
        from tools.builtins.pdf.search import _search_text_handler

        result = await _search_text_handler(
            {"file_ref": self._file_ref, "query": "unicorn"}
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["results_found"], 2)
        pages_found = [r["page"] for r in result["results"]]
        self.assertIn(1, pages_found)
        self.assertIn(3, pages_found)

    async def test_search_text_not_found(self) -> None:
        from tools.builtins.pdf.search import _search_text_handler

        result = await _search_text_handler(
            {"file_ref": self._file_ref, "query": "nonexistentwordxyz"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["results_found"], 0)

    async def test_search_text_case_sensitive(self) -> None:
        from tools.builtins.pdf.search import _search_text_handler

        result = await _search_text_handler(
            {"file_ref": self._file_ref, "query": "UNICORN", "case_sensitive": True}
        )
        self.assertEqual(result["results_found"], 0)

        result_ci = await _search_text_handler(
            {"file_ref": self._file_ref, "query": "UNICORN", "case_sensitive": False}
        )
        self.assertGreaterEqual(result_ci["results_found"], 1)

    async def test_search_text_empty_query(self) -> None:
        from tools.builtins.pdf.search import _search_text_handler

        result = await _search_text_handler({"file_ref": self._file_ref, "query": ""})
        self.assertFalse(result["ok"])

    async def test_search_text_specific_pages(self) -> None:
        from tools.builtins.pdf.search import _search_text_handler

        result = await _search_text_handler(
            {"file_ref": self._file_ref, "query": "dragon", "pages": "2"}
        )
        self.assertGreaterEqual(result["results_found"], 1)
        self.assertEqual(result["results"][0]["page"], 2)

    async def test_extract_forms_no_forms(self) -> None:
        from tools.builtins.pdf.search import _extract_forms_handler

        result = await _extract_forms_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertFalse(result["has_forms"])
        self.assertEqual(result["fields"], [])

    async def test_extract_text_via_path(self) -> None:
        from tools.builtins.pdf.extract import _extract_text_handler
        from tools.workspace.store import save_bytes

        save_bytes(1, relative="uploads/test.pdf", data=self._pdf_data, mime_type="application/pdf")
        result = await _extract_text_handler({"path": "uploads/test.pdf"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)

    async def test_is_scanned_text_pdf(self) -> None:
        from tools.builtins.pdf.ocr import _is_scanned_handler

        result = await _is_scanned_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertFalse(result["scanned"])
        self.assertGreater(result["text_ratio"], 0)

    async def test_is_scanned_specific_page(self) -> None:
        from tools.builtins.pdf.ocr import _is_scanned_handler

        result = await _is_scanned_handler(
            {"file_ref": self._file_ref, "pages": "1"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pages_checked"], 1)
        self.assertFalse(result["scanned"])

    async def test_is_scanned_no_input(self) -> None:
        from tools.builtins.pdf.ocr import _is_scanned_handler

        result = await _is_scanned_handler({})
        self.assertFalse(result["ok"])

    async def test_ocr_not_configured(self) -> None:
        from tools.builtins.pdf.ocr import _ocr_handler

        result = await _ocr_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])
        self.assertIn("not configured", result["error"])

    async def test_ocr_no_input(self) -> None:
        from tools.builtins.pdf.ocr import _ocr_handler

        result = await _ocr_handler({})
        self.assertFalse(result["ok"])
        self.assertNotIn("not configured", result.get("error", ""))

    async def test_render_single_page(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result = await _render_handler(
            {"file_ref": self._file_ref, "pages": "1", "output": "file_ref"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["pages_rendered"], 1)
        page = result["pages"][0]
        self.assertEqual(page["page"], 1)
        self.assertGreater(page["width"], 0)
        self.assertGreater(page["height"], 0)
        self.assertIn("file_ref", page)

    async def test_render_all_pages(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result = await _render_handler(
            {"file_ref": self._file_ref, "output": "file_ref"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pages_rendered"], 3)

    async def test_render_specific_pages(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result = await _render_handler(
            {"file_ref": self._file_ref, "pages": "2-3", "output": "file_ref"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pages_rendered"], 2)
        page_nums = [p["page"] for p in result["pages"]]
        self.assertEqual(page_nums, [2, 3])

    async def test_render_vision_mode(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result = await _render_handler(
            {"file_ref": self._file_ref, "pages": "1", "output": "vision"}
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["pages"][0]["vision_injected"])

    async def test_render_both_mode(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result = await _render_handler(
            {"file_ref": self._file_ref, "pages": "1", "output": "both"}
        )
        self.assertTrue(result["ok"])
        page = result["pages"][0]
        self.assertIn("file_ref", page)
        self.assertTrue(page["vision_injected"])

    async def test_render_thumbnail_scale(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result_full = await _render_handler(
            {"file_ref": self._file_ref, "pages": "1", "output": "file_ref", "dpi": 150}
        )
        result_thumb = await _render_handler(
            {"file_ref": self._file_ref, "pages": "1", "output": "file_ref", "scale": 0.3}
        )
        self.assertTrue(result_full["ok"])
        self.assertTrue(result_thumb["ok"])
        self.assertLess(
            result_thumb["pages"][0]["size_bytes"],
            result_full["pages"][0]["size_bytes"],
        )

    async def test_render_custom_width(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result = await _render_handler(
            {"file_ref": self._file_ref, "pages": "1", "output": "file_ref", "width": 400}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pages"][0]["width"], 400)

    async def test_render_no_input(self) -> None:
        from tools.builtins.pdf.render import _render_handler

        result = await _render_handler({})
        self.assertFalse(result["ok"])

    async def test_split_by_pages(self) -> None:
        from tools.builtins.pdf.pages import _split_handler

        result = await _split_handler(
            {"file_ref": self._file_ref, "pages": "1,2-3"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["parts"], 2)
        self.assertEqual(result["outputs"][0]["pages"], [1])
        self.assertEqual(result["outputs"][1]["pages"], [2, 3])

    async def test_split_every_n(self) -> None:
        from tools.builtins.pdf.pages import _split_handler

        result = await _split_handler(
            {"file_ref": self._file_ref, "every_n_pages": 2}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["parts"], 2)
        self.assertEqual(result["outputs"][0]["pages"], [1, 2])
        self.assertEqual(result["outputs"][1]["pages"], [3])

    async def test_split_no_spec(self) -> None:
        from tools.builtins.pdf.pages import _split_handler

        result = await _split_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_extract_pages(self) -> None:
        from tools.builtins.pdf.pages import _extract_pages_handler

        result = await _extract_pages_handler(
            {"file_ref": self._file_ref, "pages": "1,3"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["extracted_pages"], 2)
        self.assertEqual(result["pages"], [1, 3])
        self.assertIn("file_ref", result)

    async def test_extract_pages_no_pages(self) -> None:
        from tools.builtins.pdf.pages import _extract_pages_handler

        result = await _extract_pages_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_merge(self) -> None:
        from tools.builtins.pdf.pages import _split_handler, _merge_handler

        split = await _split_handler(
            {"file_ref": self._file_ref, "pages": "1,2-3"}
        )
        refs = [o["file_ref"] for o in split["outputs"]]
        result = await _merge_handler({"file_refs": refs})
        self.assertTrue(result["ok"])
        self.assertEqual(result["inputs"], 2)
        self.assertEqual(result["total_pages"], 3)
        self.assertIn("file_ref", result)

    async def test_merge_empty(self) -> None:
        from tools.builtins.pdf.pages import _merge_handler

        result = await _merge_handler({"file_refs": []})
        self.assertFalse(result["ok"])

    async def test_rotate_pages(self) -> None:
        from tools.builtins.pdf.pages import _rotate_pages_handler

        result = await _rotate_pages_handler(
            {"file_ref": self._file_ref, "pages": {"1-2": 90, "3": 180}}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["rotated_pages"], 3)
        rotations = {r["page"]: r["angle"] for r in result["rotations"]}
        self.assertEqual(rotations[1], 90)
        self.assertEqual(rotations[2], 90)
        self.assertEqual(rotations[3], 180)
        self.assertIn("file_ref", result)

    async def test_rotate_no_pages(self) -> None:
        from tools.builtins.pdf.pages import _rotate_pages_handler

        result = await _rotate_pages_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_delete_pages(self) -> None:
        from tools.builtins.pdf.pages import _delete_pages_handler

        result = await _delete_pages_handler(
            {"file_ref": self._file_ref, "pages": "2"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["deleted_pages"], 1)
        self.assertEqual(result["remaining_pages"], 2)
        self.assertIn("file_ref", result)

    async def test_delete_all_pages_error(self) -> None:
        from tools.builtins.pdf.pages import _delete_pages_handler

        result = await _delete_pages_handler(
            {"file_ref": self._file_ref, "pages": "1-3"}
        )
        self.assertFalse(result["ok"])

    async def test_reorder_order(self) -> None:
        from tools.builtins.pdf.pages import _reorder_pages_handler

        result = await _reorder_pages_handler(
            {"file_ref": self._file_ref, "order": [3, 1, 2]}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "order")
        self.assertEqual(result["detail"], [3, 1, 2])
        self.assertIn("file_ref", result)

    async def test_reorder_swap(self) -> None:
        from tools.builtins.pdf.pages import _reorder_pages_handler

        result = await _reorder_pages_handler(
            {"file_ref": self._file_ref, "swap": [1, 3]}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "swap")
        self.assertEqual(result["detail"], [1, 3])

    async def test_reorder_invalid_order(self) -> None:
        from tools.builtins.pdf.pages import _reorder_pages_handler

        result = await _reorder_pages_handler(
            {"file_ref": self._file_ref, "order": [1, 2]}
        )
        self.assertFalse(result["ok"])

    async def test_reorder_invalid_swap(self) -> None:
        from tools.builtins.pdf.pages import _reorder_pages_handler

        result = await _reorder_pages_handler(
            {"file_ref": self._file_ref, "swap": [1]}
        )
        self.assertFalse(result["ok"])

    async def test_reorder_no_input(self) -> None:
        from tools.builtins.pdf.pages import _reorder_pages_handler

        result = await _reorder_pages_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_overlay_text(self) -> None:
        from tools.builtins.pdf.edit import _overlay_handler

        result = await _overlay_handler(
            {"file_ref": self._file_ref, "content": "CONFIDENTIAL", "mode": "text"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["pages_modified"], 3)
        self.assertIn("file_ref", result)

    async def test_overlay_watermark(self) -> None:
        from tools.builtins.pdf.edit import _overlay_handler

        result = await _overlay_handler(
            {"file_ref": self._file_ref, "content": "DRAFT", "mode": "watermark",
             "opacity": 0.3, "rotation": 45, "font_size": 40}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "watermark")

    async def test_overlay_page_numbers(self) -> None:
        from tools.builtins.pdf.edit import _overlay_handler

        result = await _overlay_handler(
            {"file_ref": self._file_ref, "content": "", "mode": "page_numbers"}
        )
        self.assertTrue(result["ok"])

    async def test_overlay_header_footer(self) -> None:
        from tools.builtins.pdf.edit import _overlay_handler

        result_h = await _overlay_handler(
            {"file_ref": self._file_ref, "content": "My Document", "mode": "header",
             "position": "top center"}
        )
        self.assertTrue(result_h["ok"])

        result_f = await _overlay_handler(
            {"file_ref": self._file_ref, "content": "Page {n}", "mode": "footer",
             "position": "bottom center", "format": "Page {n} of {total}"}
        )
        self.assertTrue(result_f["ok"])

    async def test_overlay_specific_pages(self) -> None:
        from tools.builtins.pdf.edit import _overlay_handler

        result = await _overlay_handler(
            {"file_ref": self._file_ref, "content": "TEST", "pages": "1-2"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pages_modified"], 2)

    async def test_overlay_no_content(self) -> None:
        from tools.builtins.pdf.edit import _overlay_handler

        result = await _overlay_handler({"file_ref": self._file_ref, "content": ""})
        self.assertFalse(result["ok"])

    async def test_redact_text(self) -> None:
        from tools.builtins.pdf.edit import _redact_text_handler

        result = await _redact_text_handler(
            {"file_ref": self._file_ref, "query": "unicorn"}
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["redactions"], 1)
        self.assertIn("file_ref", result)

    async def test_redact_text_not_found(self) -> None:
        from tools.builtins.pdf.edit import _redact_text_handler

        result = await _redact_text_handler(
            {"file_ref": self._file_ref, "query": "nonexistentxyz"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["redactions"], 0)

    async def test_redact_no_query(self) -> None:
        from tools.builtins.pdf.edit import _redact_text_handler

        result = await _redact_text_handler({"file_ref": self._file_ref, "query": ""})
        self.assertFalse(result["ok"])

    async def test_add_image(self) -> None:
        from tools.builtins.pdf.edit import _add_image_handler

        png = io.BytesIO()
        from PIL import Image as PILImage
        PILImage.new("RGB", (100, 50), "red").save(png, format="PNG")
        stored = self._store.save(png.getvalue(), filename="test_img.png", mime_type="image/png")
        result = await _add_image_handler({
            "file_ref": self._file_ref,
            "image_file_ref": stored["file_ref"],
            "page": 1,
            "position": "bottom right",
            "width": 80,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_modified"], 1)
        self.assertIn("file_ref", result)

    async def test_add_image_no_image_ref(self) -> None:
        from tools.builtins.pdf.edit import _add_image_handler

        result = await _add_image_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_add_annotations(self) -> None:
        from tools.builtins.pdf.edit import _add_annotations_handler

        result = await _add_annotations_handler(
            {"file_ref": self._file_ref, "query": "unicorn", "page": 1, "type": "highlight"}
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["annotations"], 1)
        self.assertIn("file_ref", result)

    async def test_add_annotations_not_found(self) -> None:
        from tools.builtins.pdf.edit import _add_annotations_handler

        result = await _add_annotations_handler(
            {"file_ref": self._file_ref, "query": "nonexistentxyz", "page": 1}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["annotations"], 0)

    async def test_add_annotations_no_query(self) -> None:
        from tools.builtins.pdf.edit import _add_annotations_handler

        result = await _add_annotations_handler(
            {"file_ref": self._file_ref, "query": ""}
        )
        self.assertFalse(result["ok"])

    async def test_fill_form_no_form(self) -> None:
        from tools.builtins.pdf.forms import _fill_form_handler

        result = await _fill_form_handler(
            {"file_ref": self._file_ref, "fields": {"name": "test"}}
        )
        self.assertFalse(result["ok"])
        self.assertIn("no AcroForm", result["error"])

    async def test_fill_form_no_fields_arg(self) -> None:
        from tools.builtins.pdf.forms import _fill_form_handler

        result = await _fill_form_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_flatten_form_no_form(self) -> None:
        from tools.builtins.pdf.forms import _flatten_form_handler

        result = await _flatten_form_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_reset_form_no_form(self) -> None:
        from tools.builtins.pdf.forms import _reset_form_handler

        result = await _reset_form_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_create_form(self) -> None:
        from tools.builtins.pdf.forms import _create_form_handler

        result = await _create_form_handler({
            "file_ref": self._file_ref,
            "fields": [
                {"name": "username", "type": "text", "page": 1,
                 "position": {"x": 50, "y": 700, "width": 200, "height": 20},
                 "default_value": "Alice"},
                {"name": "agree", "type": "checkbox", "page": 1,
                 "position": {"x": 50, "y": 650, "width": 15, "height": 15},
                 "default_value": "true"},
                {"name": "country", "type": "dropdown", "page": 1,
                 "position": {"x": 50, "y": 600, "width": 150, "height": 20},
                 "options": ["UZ", "RU", "US"]},
            ],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["fields_created"], 3)
        self.assertIn("file_ref", result)

    async def test_create_form_no_fields(self) -> None:
        from tools.builtins.pdf.forms import _create_form_handler

        result = await _create_form_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_fill_form_after_create(self) -> None:
        from tools.builtins.pdf.forms import _create_form_handler, _fill_form_handler

        created = await _create_form_handler({
            "file_ref": self._file_ref,
            "fields": [
                {"name": "username", "type": "text", "page": 1,
                 "position": {"x": 50, "y": 700, "width": 200, "height": 20}},
                {"name": "agree", "type": "checkbox", "page": 1,
                 "position": {"x": 50, "y": 650, "width": 15, "height": 15}},
            ],
        })
        self.assertTrue(created["ok"])

        filled = await _fill_form_handler({
            "file_ref": created["file_ref"],
            "fields": {"username": "Bob", "agree": True},
        })
        self.assertTrue(filled["ok"])
        self.assertEqual(filled["fields_filled"], 2)
        self.assertEqual(filled["fields_not_found"], [])

    async def test_fill_form_with_flatten(self) -> None:
        from tools.builtins.pdf.forms import _create_form_handler, _fill_form_handler

        created = await _create_form_handler({
            "file_ref": self._file_ref,
            "fields": [
                {"name": "email", "type": "text", "page": 1,
                 "position": {"x": 50, "y": 700, "width": 200, "height": 20}},
            ],
        })
        filled = await _fill_form_handler({
            "file_ref": created["file_ref"],
            "fields": {"email": "test@example.com"},
            "flatten": True,
        })
        self.assertTrue(filled["ok"])
        self.assertTrue(filled["flattened"])

    async def test_reset_form_after_fill(self) -> None:
        from tools.builtins.pdf.forms import _create_form_handler, _fill_form_handler, _reset_form_handler

        created = await _create_form_handler({
            "file_ref": self._file_ref,
            "fields": [
                {"name": "username", "type": "text", "page": 1,
                 "position": {"x": 50, "y": 700, "width": 200, "height": 20}},
            ],
        })
        await _fill_form_handler({
            "file_ref": created["file_ref"],
            "fields": {"username": "Charlie"},
        })
        reset = await _reset_form_handler({"file_ref": created["file_ref"]})
        self.assertTrue(reset["ok"])
        self.assertGreaterEqual(reset["fields_reset"], 1)

    async def test_reset_form_specific_fields(self) -> None:
        from tools.builtins.pdf.forms import _create_form_handler, _reset_form_handler

        created = await _create_form_handler({
            "file_ref": self._file_ref,
            "fields": [
                {"name": "field_a", "type": "text", "page": 1,
                 "position": {"x": 50, "y": 700, "width": 100, "height": 20}},
                {"name": "field_b", "type": "text", "page": 1,
                 "position": {"x": 50, "y": 600, "width": 100, "height": 20}},
            ],
        })
        reset = await _reset_form_handler({
            "file_ref": created["file_ref"],
            "fields": ["field_a"],
        })
        self.assertTrue(reset["ok"])
        self.assertEqual(reset["fields_reset"], 1)

    async def test_flatten_form_after_create(self) -> None:
        from tools.builtins.pdf.forms import _create_form_handler, _flatten_form_handler

        created = await _create_form_handler({
            "file_ref": self._file_ref,
            "fields": [
                {"name": "test_field", "type": "text", "page": 1,
                 "position": {"x": 50, "y": 700, "width": 200, "height": 20},
                 "default_value": "Hello"},
            ],
        })
        result = await _flatten_form_handler({"file_ref": created["file_ref"]})
        self.assertTrue(result["ok"])
        self.assertTrue(result["flattened"])

    async def test_encrypt(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler

        result = await _encrypt_handler(
            {"file_ref": self._file_ref, "password": "secret123"}
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["encrypted"])
        self.assertIn("file_ref", result)
        self.assertTrue(result["permissions"]["print"])

    async def test_encrypt_with_restrictions(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler

        result = await _encrypt_handler({
            "file_ref": self._file_ref,
            "password": "secret",
            "allow_print": False,
            "allow_copy": False,
        })
        self.assertTrue(result["ok"])
        self.assertFalse(result["permissions"]["print"])
        self.assertFalse(result["permissions"]["copy"])

    async def test_encrypt_no_password(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler

        result = await _encrypt_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_decrypt(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler, _decrypt_handler

        encrypted = await _encrypt_handler(
            {"file_ref": self._file_ref, "password": "secret123"}
        )
        result = await _decrypt_handler({
            "file_ref": encrypted["file_ref"],
            "password": "secret123",
        })
        self.assertTrue(result["ok"])
        self.assertTrue(result["decrypted"])
        self.assertEqual(result["page_count"], 3)
        self.assertIn("file_ref", result)

    async def test_decrypt_wrong_password(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler, _decrypt_handler

        encrypted = await _encrypt_handler(
            {"file_ref": self._file_ref, "password": "secret123"}
        )
        result = await _decrypt_handler({
            "file_ref": encrypted["file_ref"],
            "password": "wrong",
        })
        self.assertFalse(result["ok"])
        self.assertIn("Invalid password", result["error"])

    async def test_decrypt_not_encrypted(self) -> None:
        from tools.builtins.pdf.security import _decrypt_handler

        result = await _decrypt_handler({
            "file_ref": self._file_ref,
            "password": "any",
        })
        self.assertFalse(result["ok"])
        self.assertIn("not encrypted", result["error"])

    async def test_get_permissions_not_encrypted(self) -> None:
        from tools.builtins.pdf.security import _get_permissions_handler

        result = await _get_permissions_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertFalse(result["encrypted"])
        self.assertFalse(result["needs_password"])
        self.assertTrue(result["permissions"]["print"])

    async def test_get_permissions_encrypted_no_password(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler, _get_permissions_handler

        encrypted = await _encrypt_handler(
            {"file_ref": self._file_ref, "password": "secret"}
        )
        result = await _get_permissions_handler({"file_ref": encrypted["file_ref"]})
        self.assertTrue(result["ok"])
        self.assertTrue(result["encrypted"])
        self.assertTrue(result["needs_password"])

    async def test_get_permissions_encrypted_with_password(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler, _get_permissions_handler

        encrypted = await _encrypt_handler(
            {"file_ref": self._file_ref, "password": "secret"}
        )
        result = await _get_permissions_handler({
            "file_ref": encrypted["file_ref"],
            "password": "secret",
        })
        self.assertTrue(result["ok"])
        self.assertTrue(result["encrypted"])
        self.assertFalse(result["needs_password"])

    async def test_get_permissions_wrong_password(self) -> None:
        from tools.builtins.pdf.security import _encrypt_handler, _get_permissions_handler

        encrypted = await _encrypt_handler(
            {"file_ref": self._file_ref, "password": "secret"}
        )
        result = await _get_permissions_handler({
            "file_ref": encrypted["file_ref"],
            "password": "wrong",
        })
        self.assertTrue(result["ok"])
        self.assertIn("Invalid password", result.get("error", ""))

    async def test_optimize_light(self) -> None:
        from tools.builtins.pdf.optimize import _optimize_handler

        result = await _optimize_handler(
            {"file_ref": self._file_ref, "level": "light"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["level"], "light")
        self.assertIn("old_size", result)
        self.assertIn("new_size", result)
        self.assertIn("file_ref", result)

    async def test_optimize_medium(self) -> None:
        from tools.builtins.pdf.optimize import _optimize_handler

        result = await _optimize_handler(
            {"file_ref": self._file_ref, "level": "medium"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], "medium")

    async def test_optimize_aggressive(self) -> None:
        from tools.builtins.pdf.optimize import _optimize_handler

        result = await _optimize_handler(
            {"file_ref": self._file_ref, "level": "aggressive"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], "aggressive")
        self.assertIn("old_size", result)
        self.assertIn("new_size", result)
        self.assertIn("saved_percent", result)

    async def test_optimize_invalid_level_defaults(self) -> None:
        from tools.builtins.pdf.optimize import _optimize_handler

        result = await _optimize_handler(
            {"file_ref": self._file_ref, "level": "invalid"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], "medium")

    async def test_optimize_no_input(self) -> None:
        from tools.builtins.pdf.optimize import _optimize_handler

        result = await _optimize_handler({})
        self.assertFalse(result["ok"])

    async def test_repair_valid_pdf(self) -> None:
        from tools.builtins.pdf.optimize import _repair_handler

        result = await _repair_handler({"file_ref": self._file_ref})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count_original"], 3)
        self.assertEqual(result["page_count_repaired"], 3)
        self.assertEqual(result["pages_failed"], 0)
        self.assertIn("file_ref", result)
        self.assertIsInstance(result["repairs"], list)

    async def test_repair_no_input(self) -> None:
        from tools.builtins.pdf.optimize import _repair_handler

        result = await _repair_handler({})
        self.assertFalse(result["ok"])

    async def test_repair_corrupt_pdf(self) -> None:
        from tools.builtins.pdf.optimize import _repair_handler

        corrupt_data = b"%PDF-1.4\nbroken content\n%%EOF"
        stored = self._store.save(
            corrupt_data, filename="corrupt.pdf", mime_type="application/pdf"
        )
        result = await _repair_handler({"file_ref": stored["file_ref"]})
        self.assertFalse(result["ok"])

    async def test_set_metadata(self) -> None:
        from tools.builtins.pdf.metadata_write import _set_metadata_handler

        result = await _set_metadata_handler({
            "file_ref": self._file_ref,
            "title": "My Document",
            "author": "Test Author",
            "keywords": "test, pdf, metadata",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 3)
        self.assertIn("Title", result["updated_fields"])
        self.assertEqual(result["updated_fields"]["Title"], "My Document")
        self.assertIn("file_ref", result)

    async def test_set_metadata_no_fields(self) -> None:
        from tools.builtins.pdf.metadata_write import _set_metadata_handler

        result = await _set_metadata_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_set_metadata_verify(self) -> None:
        from tools.builtins.pdf.metadata_write import _set_metadata_handler
        from tools.builtins.pdf.metadata import _read_metadata_handler

        updated = await _set_metadata_handler({
            "file_ref": self._file_ref,
            "title": "Verified Title",
            "author": "Verified Author",
        })
        result = await _read_metadata_handler({"file_ref": updated["file_ref"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["title"], "Verified Title")
        self.assertEqual(result["author"], "Verified Author")

    async def test_set_outline(self) -> None:
        from tools.builtins.pdf.metadata_write import _set_outline_handler

        result = await _set_outline_handler({
            "file_ref": self._file_ref,
            "outline": [
                {"title": "Introduction", "page": 1, "level": 0},
                {"title": "Second Section", "page": 2, "level": 0},
                {"title": "Conclusion", "page": 3, "level": 0},
            ],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["bookmarks_added"], 3)
        self.assertIn("file_ref", result)

    async def test_set_outline_nested(self) -> None:
        from tools.builtins.pdf.metadata_write import _set_outline_handler

        result = await _set_outline_handler({
            "file_ref": self._file_ref,
            "outline": [
                {"title": "Chapter 1", "page": 1, "level": 0, "children": [
                    {"title": "Section 1.1", "page": 1, "level": 1},
                    {"title": "Section 1.2", "page": 2, "level": 1},
                ]},
                {"title": "Chapter 2", "page": 3, "level": 0},
            ],
        })
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["bookmarks_added"], 3)

    async def test_set_outline_empty(self) -> None:
        from tools.builtins.pdf.metadata_write import _set_outline_handler

        result = await _set_outline_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_set_outline_verify(self) -> None:
        from tools.builtins.pdf.metadata_write import _set_outline_handler
        from tools.builtins.pdf.metadata import _get_outline_handler

        updated = await _set_outline_handler({
            "file_ref": self._file_ref,
            "outline": [
                {"title": "First", "page": 1, "level": 0},
                {"title": "Last", "page": 3, "level": 0},
            ],
        })
        result = await _get_outline_handler({"file_ref": updated["file_ref"]})
        self.assertTrue(result["ok"])
        titles = [o["title"] for o in result["outline"]]
        self.assertIn("First", titles)
        self.assertIn("Last", titles)

    async def test_add_bookmark(self) -> None:
        from tools.builtins.pdf.metadata_write import _add_bookmark_handler

        result = await _add_bookmark_handler({
            "file_ref": self._file_ref,
            "title": "My Bookmark",
            "page": 2,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["bookmark"]["title"], "My Bookmark")
        self.assertEqual(result["bookmark"]["page"], 2)
        self.assertIn("file_ref", result)

    async def test_add_bookmark_invalid_page(self) -> None:
        from tools.builtins.pdf.metadata_write import _add_bookmark_handler

        result = await _add_bookmark_handler({
            "file_ref": self._file_ref,
            "title": "Bad",
            "page": 99,
        })
        self.assertFalse(result["ok"])

    async def test_add_bookmark_no_title(self) -> None:
        from tools.builtins.pdf.metadata_write import _add_bookmark_handler

        result = await _add_bookmark_handler({"file_ref": self._file_ref})
        self.assertFalse(result["ok"])

    async def test_create_from_text(self) -> None:
        from tools.builtins.pdf.create import _create_handler

        result = await _create_handler({
            "content": "Hello World\nThis is a test PDF.\nThird line.",
            "format": "text",
            "title": "Test Doc",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["format"], "text")
        self.assertIn("file_ref", result)
        self.assertGreater(result["size_bytes"], 0)

    async def test_create_from_markdown(self) -> None:
        from tools.builtins.pdf.create import _create_handler

        md = "# Title\n\nSome **bold** text.\n\n## Subheading\n\n- Item 1\n- Item 2\n\n| Col A | Col B |\n|-------|-------|\n| 1 | 2 |\n"
        result = await _create_handler({
            "content": md,
            "format": "markdown",
            "title": "Markdown Doc",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["format"], "markdown")
        self.assertIn("file_ref", result)

    async def test_create_markdown_with_code(self) -> None:
        from tools.builtins.pdf.create import _create_handler

        md = "# Code Example\n\n```python\nprint('hello')\n```\n\nEnd."
        result = await _create_handler({"content": md, "format": "markdown"})
        self.assertTrue(result["ok"])

    async def test_create_no_content(self) -> None:
        from tools.builtins.pdf.create import _create_handler

        result = await _create_handler({"content": ""})
        self.assertFalse(result["ok"])

    async def test_create_page_size(self) -> None:
        from tools.builtins.pdf.create import _create_handler

        result = await _create_handler({
            "content": "Test",
            "page_size": "Letter",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_size"], "Letter")

    async def test_create_from_images(self) -> None:
        from PIL import Image as PILImage
        from tools.builtins.pdf.create import _create_from_images_handler

        images = []
        for color in ("red", "blue", "green"):
            buf = io.BytesIO()
            PILImage.new("RGB", (200, 300), color).save(buf, format="PNG")
            stored = self._store.save(buf.getvalue(), filename=f"img_{color}.png", mime_type="image/png")
            images.append(stored["file_ref"])

        result = await _create_from_images_handler({
            "image_file_refs": images,
            "page_size": "A4",
            "fit": "contain",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["images_used"], 3)
        self.assertIn("file_ref", result)

    async def test_create_from_images_empty(self) -> None:
        from tools.builtins.pdf.create import _create_from_images_handler

        result = await _create_from_images_handler({"image_file_refs": []})
        self.assertFalse(result["ok"])

    async def test_create_blank(self) -> None:
        from tools.builtins.pdf.create import _create_blank_handler

        result = await _create_blank_handler({"pages": 5, "page_size": "A4"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 5)
        self.assertIn("file_ref", result)
        self.assertGreater(result["size_bytes"], 0)

    async def test_create_blank_default(self) -> None:
        from tools.builtins.pdf.create import _create_blank_handler

        result = await _create_blank_handler({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_count"], 1)

    async def test_create_blank_too_many(self) -> None:
        from tools.builtins.pdf.create import _create_blank_handler

        result = await _create_blank_handler({"pages": 2000})
        self.assertFalse(result["ok"])

    async def test_create_then_verify_text(self) -> None:
        from tools.builtins.pdf.create import _create_handler
        from tools.builtins.pdf.extract import _extract_text_handler

        created = await _create_handler({
            "content": "Verify me please",
            "format": "text",
        })
        result = await _extract_text_handler({"file_ref": created["file_ref"]})
        self.assertTrue(result["ok"])
        all_text = " ".join(p["text"] for p in result["pages"])
        self.assertIn("Verify", all_text)


class ParsePagesSpecTests(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(parse_pages_spec(None, 10))
        self.assertIsNone(parse_pages_spec("", 10))

    def test_single_page(self) -> None:
        self.assertEqual(parse_pages_spec("5", 10), [5])

    def test_range(self) -> None:
        self.assertEqual(parse_pages_spec("2-5", 10), [2, 3, 4, 5])

    def test_mixed(self) -> None:
        self.assertEqual(parse_pages_spec("1-3,7,10", 10), [1, 2, 3, 7, 10])

    def test_open_ended_range(self) -> None:
        self.assertEqual(parse_pages_spec("8-", 10), [8, 9, 10])

    def test_end_keyword(self) -> None:
        self.assertEqual(parse_pages_spec("1,end", 3), [1, 3])

    def test_out_of_range(self) -> None:
        self.assertEqual(parse_pages_spec("15", 10), None)

    def test_clamped_range(self) -> None:
        self.assertEqual(parse_pages_spec("8-15", 10), [8, 9, 10])


class PdfToolsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_finds_pdf_tools(self) -> None:
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            from tools.bootstrap import create_tool_runtime

            runtime = await create_tool_runtime()
            result = await runtime.search_tools("extract text from pdf", top_k=10)
            names = [t["name"] for t in result["tools"]]
            self.assertIn("pdf.extract_text", names)

    async def test_runtime_catalog_pdf_tags(self) -> None:
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            from tools.bootstrap import create_tool_runtime

            runtime = await create_tool_runtime()
            result = await runtime.search_tools(
                "", mode="catalog", tags=["pdf", "read"]
            )
            names = [t["name"] for t in result["tools"]]
            self.assertIn("pdf.extract_text", names)
            self.assertIn("pdf.read_metadata", names)
            self.assertIn("pdf.search_text", names)
            self.assertIn("pdf.ocr", names)
            self.assertIn("pdf.is_scanned", names)


if __name__ == "__main__":
    unittest.main()
