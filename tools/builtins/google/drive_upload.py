from __future__ import annotations

import io
from typing import Any

from googleapiclient.http import MediaIoBaseUpload

from tools.builtins.google.drive_client import drive_support_kwargs
from tools.builtins.google.drive_serialize import CREATE_FILE_FIELDS


def create_metadata_file(service, *, metadata: dict[str, Any]) -> dict[str, Any]:
    return (
        service.files()
        .create(
            body=metadata,
            fields=CREATE_FILE_FIELDS,
            **drive_support_kwargs(),
        )
        .execute()
    )


def create_file_with_content(
    service,
    *,
    metadata: dict[str, Any],
    content: bytes,
    mime_type: str,
) -> dict[str, Any]:
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    return (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields=CREATE_FILE_FIELDS,
            **drive_support_kwargs(),
        )
        .execute()
    )


def update_file_with_content(
    service,
    *,
    file_id: str,
    content: bytes,
    mime_type: str,
) -> dict[str, Any]:
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    return (
        service.files()
        .update(
            fileId=file_id,
            media_body=media,
            fields=CREATE_FILE_FIELDS,
            **drive_support_kwargs(),
        )
        .execute()
    )
