from __future__ import annotations

import unittest

from tools.builtins.browser.playwright_bridge import (
    PlaywrightSession,
    _guess_selector,
    _split_nth,
)


class BrowserClickRefTests(unittest.TestCase):
    def test_guess_selector_includes_nth(self) -> None:
        s0 = _guess_selector("button", "Sign in with Google", None, nth=0)
        s1 = _guess_selector("button", "Sign in with Google", None, nth=1)
        self.assertEqual(s0, 'role=button[name="Sign in with Google"]>>nth=0')
        self.assertEqual(s1, 'role=button[name="Sign in with Google"]>>nth=1')

    def test_split_nth(self) -> None:
        base, nth = _split_nth('role=button[name="X"]>>nth=2')
        self.assertEqual(base, 'role=button[name="X"]')
        self.assertEqual(nth, 2)
        base2, nth2 = _split_nth("css=button.primary")
        self.assertEqual(base2, "css=button.primary")
        self.assertEqual(nth2, 0)

    def test_refs_store_css_prefix(self) -> None:
        session = PlaywrightSession(
            playwright=None,
            browser=None,
            context=None,
            page=None,
        )
        session.refs["e1"] = "css=form > button:nth-of-type(2)"
        self.assertTrue(session.refs["e1"].startswith("css="))
        # Must NOT look like the old broken global counter pattern alone.
        self.assertNotRegex(session.refs["e1"], r"^button:nth-of-type\(\d+\)$")


if __name__ == "__main__":
    unittest.main()
