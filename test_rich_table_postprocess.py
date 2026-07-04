import unittest

from rich_format import prepare_telegram_rich_markdown
from rich_table_postprocess import normalize_table_cell


class TableCellPostprocessTests(unittest.TestCase):
    def test_single_temperature(self) -> None:
        raw = r"$ +19^\circ\mathrm{C}$"
        self.assertEqual(normalize_table_cell(raw), "+19 °C")

    def test_temperature_range(self) -> None:
        raw = r"$ +32^\circ\mathrm{C}$ ... $ +34^\circ\mathrm{C}$"
        self.assertEqual(normalize_table_cell(raw), "+32 °C … +34 °C")

    def test_wind_with_typo_and_number(self) -> None:
        raw = r"Северо-западный, \appro $4$ м/с"
        self.assertEqual(normalize_table_cell(raw), "Северо-западный, ≈ 4 м/с")

    def test_plain_text_unchanged(self) -> None:
        text = "Ясно, без осадков"
        self.assertEqual(normalize_table_cell(text), text)

    def test_weather_table_in_prepare_pipeline(self) -> None:
        source = """| Город | Температура днем | Ветер |
|-------|------------------|-------|
| Ташкент | $ +32^\\circ\\mathrm{C}$ ... $ +34^\\circ\\mathrm{C}$ | Северо-западный, \\appro $4$ м/с |"""
        result = prepare_telegram_rich_markdown(source)
        self.assertIn("<table bordered striped>", result)
        self.assertIn("+32 °C … +34 °C", result)
        self.assertIn("≈ 4 м/с", result)
        self.assertNotIn("$", result)
        self.assertNotIn("\\circ", result)
        self.assertNotIn("\\appro", result)


if __name__ == "__main__":
    unittest.main()
