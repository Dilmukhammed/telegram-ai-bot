import unittest

from rich_demo import build_rich_blocks_demo_markdown


class RichDemoTests(unittest.TestCase):
    def test_demo_contains_media_blocks(self) -> None:
        md = build_rich_blocks_demo_markdown()
        self.assertIn("![](https://telegram.org/example/photo.jpg", md)
        self.assertIn("<tg-collage>", md)
        self.assertIn("<tg-slideshow>", md)
        self.assertNotIn("<figcaption>", md)
        self.assertIn("<details>", md)
        self.assertIn("$$", md)


if __name__ == "__main__":
    unittest.main()
