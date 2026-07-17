from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "steel_live: live Steel API smoke tests (requires STEEL_API_KEY)",
    )
