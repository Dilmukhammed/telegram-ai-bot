from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.graph_lab import GraphLab, INDEX_HTML


class GraphLabPR14V2Tests(unittest.TestCase):
    def test_ui_exposes_v2_lifecycle_and_trace_contract(self) -> None:
        for marker in (
            'id="nAttachReverted"',
            'id="nAttachConstraints"',
            'id="nAttachDependencies"',
            'id="attachmentTrace"',
            "accepted_hypotheses",
            "PR14 v2",
        ):
            self.assertIn(marker, INDEX_HTML)

    def test_lab_keeps_committee_models_for_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lab = GraphLab(Path(tmp))
            self.assertEqual(lab.attachment_models, {})
            self.assertTrue(hasattr(lab, "attach_dry_run"))
            self.assertTrue(hasattr(lab, "attach_events_payload"))


if __name__ == "__main__":
    unittest.main()
