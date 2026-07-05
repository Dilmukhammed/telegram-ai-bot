from __future__ import annotations


class YandexMusicError(RuntimeError):
    """Base Yandex Music integration error."""


class YandexNotConnectedError(YandexMusicError):
    """User has not connected Yandex Music."""


class YandexDeviceAuthPendingError(YandexMusicError):
    """Device OAuth flow is still waiting for user confirmation."""
