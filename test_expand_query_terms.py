import unittest

from tools.keyword_index import expand_query_terms


class ExpandQueryTermsTests(unittest.TestCase):
    def test_skips_bare_search_in_multiword_query(self) -> None:
        terms = expand_query_terms("search gmail messages")
        self.assertIn("search gmail messages", terms)
        self.assertIn("gmail", terms)
        self.assertNotIn("search", terms)

    def test_keeps_search_for_single_word_query(self) -> None:
        terms = expand_query_terms("search")
        self.assertEqual(terms, ["search"])


if __name__ == "__main__":
    unittest.main()
