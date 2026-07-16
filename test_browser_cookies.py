from __future__ import annotations

import unittest

from tools.builtins.browser.cookies import cookies_summary, normalize_cookie, parse_cookies_payload


class BrowserCookiesTests(unittest.TestCase):
    def test_editthiscookie_normalize(self) -> None:
        raw = {
            "domain": ".google.com",
            "expirationDate": 2000000000,
            "httpOnly": True,
            "name": "SID",
            "path": "/",
            "sameSite": "no_restriction",
            "secure": True,
            "value": "abc",
        }
        cookie = normalize_cookie(raw)
        assert cookie is not None
        self.assertEqual(cookie["domain"], ".google.com")
        self.assertEqual(cookie["sameSite"], "None")
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["expires"], 2000000000.0)

    def test_parse_array_and_summary(self) -> None:
        payload = [
            {"name": "A", "value": "1", "domain": ".google.com", "path": "/"},
            {"name": "B", "value": "2", "url": "https://mail.google.com/"},
            {"name": "bad"},
        ]
        cookies = parse_cookies_payload(payload)
        self.assertEqual(len(cookies), 2)
        summary = cookies_summary(cookies)
        self.assertEqual(summary["count"], 2)

    def test_ms_expiry(self) -> None:
        cookie = normalize_cookie(
            {
                "name": "X",
                "value": "y",
                "domain": ".example.com",
                "path": "/",
                "expirationDate": 2000000000000,
            }
        )
        assert cookie is not None
        self.assertEqual(cookie["expires"], 2000000000.0)


if __name__ == "__main__":
    unittest.main()
