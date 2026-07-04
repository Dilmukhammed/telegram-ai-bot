from config import (
    DEFAULT_DRIVE_MAX_DOWNLOAD_BYTES,
    DEFAULT_DRIVE_MAX_EXPORT_BYTES,
    DEFAULT_GMAIL_MAX_ATTACHMENT_BYTES,
    GOOGLE_DRIVE_MAX_BLOB_BYTES,
    GOOGLE_DRIVE_MAX_EXPORT_BYTES,
    GOOGLE_GMAIL_MAX_ATTACHMENT_BYTES,
    google_limit_label,
)


def test_defaults_match_google_limits():
    assert DEFAULT_GMAIL_MAX_ATTACHMENT_BYTES == GOOGLE_GMAIL_MAX_ATTACHMENT_BYTES
    assert DEFAULT_DRIVE_MAX_EXPORT_BYTES == GOOGLE_DRIVE_MAX_EXPORT_BYTES
    assert DEFAULT_DRIVE_MAX_DOWNLOAD_BYTES == GOOGLE_DRIVE_MAX_BLOB_BYTES


def test_google_limit_labels():
    assert "10 MB" in google_limit_label("drive_export")
    assert "25 MB" in google_limit_label("gmail_attachment")
    assert "5 TiB" in google_limit_label("drive_blob")
