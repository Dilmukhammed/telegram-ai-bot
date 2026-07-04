import json
import unittest

from agent.sources import SourceCollector, append_sources


class SourceCollectorTests(unittest.TestCase):
    def test_ingest_web_search_results(self) -> None:
        collector = SourceCollector()
        payload = {
            "ok": True,
            "tool_name": "exa.web_search",
            "result": {
                "results": [
                    {"url": "https://example.com/a", "title": "Example A"},
                    {"url": "https://example.com/b", "title": "Example B"},
                ]
            },
        }
        collector.ingest_tool_result_json(json.dumps(payload))
        self.assertEqual(len(collector.items), 2)

    def test_deduplicates_urls(self) -> None:
        collector = SourceCollector()
        collector.add("https://example.com/a", "A")
        collector.add("https://example.com/a", "A again")
        self.assertEqual(len(collector.items), 1)

    def test_format_collapsed_sources_block(self) -> None:
        collector = SourceCollector()
        collector.add("https://example.com/news", "News")
        appendix = collector.format_appendix()
        self.assertIn("<details>", appendix)
        self.assertIn("<summary>Источники</summary>", appendix)
        self.assertIn("https://example.com/news", appendix)
        self.assertNotIn("open", appendix)

    def test_append_sources_to_reply(self) -> None:
        collector = SourceCollector()
        collector.add("https://example.com/x", "X")
        reply = append_sources("Answer text", collector)
        self.assertTrue(reply.startswith("Answer text"))
        self.assertIn("Источники", reply)


if __name__ == "__main__":
    unittest.main()
