import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from config import get_settings
from tools.builtins.pdf import PDF_TOOLS
from tools.builtins.pdf.pdf_checker import (
    PDF_CHECKER_ALL_TOOL_NAMES,
    PDF_CHECKER_QUESTIONS_BY_TOOL,
    PDF_CHECKER_READ_TOOL_NAMES,
    PDF_CHECKER_WRITE_TOOL_NAMES,
    PDF_FILL_FORM_QUESTIONS,
    PDF_MERGE_QUESTIONS,
    PDF_OCR_QUESTIONS,
    PDF_REDACT_TEXT_QUESTIONS,
)
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH


class PdfCheckerPackTests(unittest.TestCase):
    def test_all_37_pdf_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in PDF_TOOLS}
        self.assertEqual(len(PDF_CHECKER_ALL_TOOL_NAMES), 37)
        self.assertEqual(len(PDF_TOOLS), 37)
        for name in PDF_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, PDF_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_read_write_partitions(self) -> None:
        self.assertEqual(
            set(PDF_CHECKER_READ_TOOL_NAMES) | set(PDF_CHECKER_WRITE_TOOL_NAMES),
            set(PDF_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(PDF_CHECKER_READ_TOOL_NAMES), 13)
        self.assertEqual(len(PDF_CHECKER_WRITE_TOOL_NAMES), 24)

    def test_merge_has_live_metadata_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in PDF_MERGE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("pdf_read_metadata", fetches)

    def test_ocr_has_scan_justification_question(self) -> None:
        self.assertIn("ocr_justified", {q.id for q in PDF_OCR_QUESTIONS})

    def test_fill_form_field_values_question(self) -> None:
        self.assertIn("field_values_match", {q.id for q in PDF_FILL_FORM_QUESTIONS})

    def test_redact_irreversible_question(self) -> None:
        self.assertIn("redact_irreversible", {q.id for q in PDF_REDACT_TEXT_QUESTIONS})

    def test_read_tools_no_live_fetch(self) -> None:
        for name in PDF_CHECKER_READ_TOOL_NAMES:
            fetches = {
                ref.fetch
                for q in PDF_CHECKER_QUESTIONS_BY_TOOL[name]
                for ref in q.evidence
                if ref.kind == EVIDENCE_LIVE_FETCH
            }
            self.assertEqual(fetches, set(), msg=name)

    def test_allowlist_glob_matches_pdf(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="pdf.*",
        )
        tool = next(t for t in PDF_TOOLS if t.name == "pdf.extract_text")
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="pdf.extract_text",
            arguments_raw={},
            arguments_normalized={"path": "uploads/doc.pdf"},
            result_ok=True,
            result_json=json.dumps({"pages": [{"page": 1, "text": "hi"}]}),
        )
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))


if __name__ == "__main__":
    unittest.main()
