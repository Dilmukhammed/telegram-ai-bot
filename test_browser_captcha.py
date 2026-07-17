from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.builtins.browser.captcha_detect import (
    classify_solve_backend,
    normalize_detect_result,
)
from tools.builtins.browser.captcha_token import CapSolverProvider, _extract_token


class CaptchaDetectNormalizeTests(unittest.TestCase):
    def test_turnstile_normalize(self) -> None:
        raw = {
            "present": True,
            "kind": "turnstile",
            "sitekey": "0x4AAAAAAAtest",
            "action": "login",
            "iframe_url": "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x",
            "selector": ".cf-turnstile",
            "bbox": {"x": 10, "y": 20, "width": 300, "height": 65},
            "confidence": 0.95,
            "candidates": [
                {
                    "kind": "turnstile",
                    "sitekey": "0x4AAAAAAAtest",
                    "confidence": 0.95,
                }
            ],
            "url": "https://example.com/login",
            "title": "Login",
        }
        out = normalize_detect_result(raw)
        self.assertTrue(out["present"])
        self.assertEqual(out["kind"], "turnstile")
        self.assertEqual(out["sitekey"], "0x4AAAAAAAtest")
        self.assertEqual(out["confidence"], 0.95)
        self.assertEqual(len(out["candidates"]), 1)

    def test_empty_raw(self) -> None:
        out = normalize_detect_result(None, page_url="https://x.test/")
        self.assertFalse(out["present"])
        self.assertIsNone(out["kind"])
        self.assertEqual(out["url"], "https://x.test/")

    def test_unknown_kind_mapped(self) -> None:
        out = normalize_detect_result({"present": True, "kind": "weird", "confidence": 0.5})
        self.assertEqual(out["kind"], "unknown")

    def test_classify_backend(self) -> None:
        self.assertEqual(classify_solve_backend("image"), "ocr")
        self.assertEqual(classify_solve_backend("slider"), "ocr")
        self.assertEqual(classify_solve_backend("turnstile"), "token")
        self.assertEqual(classify_solve_backend("recaptcha_v2"), "token")
        self.assertEqual(classify_solve_backend("hcaptcha"), "token")
        self.assertEqual(classify_solve_backend(None), "hitl")


class CapSolverProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_until_ready(self) -> None:
        provider = CapSolverProvider("k", poll_interval=0.01)
        calls: list[str] = []
        payloads = [
            {"errorId": 0, "taskId": "t1", "status": "idle"},
            {"errorId": 0, "status": "processing"},
            {
                "errorId": 0,
                "status": "ready",
                "solution": {"gRecaptchaResponse": "gr-1"},
            },
        ]

        def fake_post(url: str, body: dict) -> dict:
            calls.append(url)
            return payloads.pop(0)

        import urllib.request

        class FakeResp:
            def __init__(self, data: dict):
                self._data = json.dumps(data).encode()

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=30):
            body = json.loads(req.data.decode())
            data = fake_post(req.full_url, body)
            return FakeResp(data)

        with patch.object(urllib.request, "urlopen", urlopen):
            token = await provider.solve(
                kind="recaptcha_v2",
                website_url="https://example.com",
                website_key="6Lxx",
                timeout_seconds=5,
            )
        self.assertEqual(token, "gr-1")
        self.assertEqual(len(calls), 3)

    async def test_turnstile_ready_immediate(self) -> None:
        provider = CapSolverProvider("test-key", poll_interval=0.01)

        import urllib.request

        class FakeResp:
            def __init__(self, data: dict):
                self._data = json.dumps(data).encode()

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=30):
            body = json.loads(req.data.decode())
            self.assertEqual(body["task"]["type"], "AntiTurnstileTaskProxyLess")
            return FakeResp(
                {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"token": "tok-abc"},
                }
            )

        with patch.object(urllib.request, "urlopen", urlopen):
            token = await provider.solve(
                kind="turnstile",
                website_url="https://example.com",
                website_key="0xKEY",
                timeout_seconds=5,
            )
        self.assertEqual(token, "tok-abc")

    def test_task_payload_kinds(self) -> None:
        p = CapSolverProvider("k")
        self.assertEqual(
            p._task_payload(
                kind="turnstile",
                website_url="https://a",
                website_key="0x1",
                action="login",
            )["type"],
            "AntiTurnstileTaskProxyLess",
        )
        self.assertEqual(
            p._task_payload(
                kind="hcaptcha",
                website_url="https://a",
                website_key="x",
                action=None,
            )["type"],
            "HCaptchaTaskProxyLess",
        )
        self.assertEqual(
            p._task_payload(
                kind="recaptcha_v3",
                website_url="https://a",
                website_key="6L",
                action="submit",
            )["pageAction"],
            "submit",
        )
        self.assertEqual(_extract_token({"token": "a"}), "a")
        self.assertIsNone(_extract_token({}))


class CaptchaOcrMockTests(unittest.TestCase):
    def test_recognize_text_mocked(self) -> None:
        from tools.builtins.browser import captcha_ocr as ocr_mod

        class FakeOcr:
            def classification(self, data: bytes) -> str:
                assert data
                return "AB12"

        with patch.object(ocr_mod, "_ensure_ocr", return_value=FakeOcr()):
            text = ocr_mod.recognize_text(b"PNGDATA")
        self.assertEqual(text, "AB12")


if __name__ == "__main__":
    unittest.main()
