"""Domain errors for the signals module."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://agripulse.cloud/problems/signals"


class SignalDefinitionNotFoundError(APIError):
    def __init__(self, ref: str | UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Signal definition not found",
            detail=f"No signal definition with ref {ref!r} in this tenant.",
            type_=f"{_TYPE_BASE}/definition-not-found",
            extras={"ref": str(ref)},
        )


class SignalCodeAlreadyExistsError(APIError):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Signal code already exists",
            detail=f"An active signal definition with code {code!r} already exists.",
            type_=f"{_TYPE_BASE}/code-exists",
            extras={"code": code},
        )


class SignalAssignmentNotFoundError(APIError):
    def __init__(self, assignment_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Signal assignment not found",
            detail=f"No signal assignment with id {assignment_id} in this tenant.",
            type_=f"{_TYPE_BASE}/assignment-not-found",
            extras={"assignment_id": str(assignment_id)},
        )


class InvalidSignalValueError(APIError):
    """An observation's value violates the definition's constraints
    (wrong kind, out of range, not in categorical_values, etc.)."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid signal value",
            detail=detail,
            type_=f"{_TYPE_BASE}/invalid-value",
        )


class AttachmentNotPermittedError(APIError):
    def __init__(self, *, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Attachment not permitted",
            detail=f"Signal {code!r} does not allow attachments.",
            type_=f"{_TYPE_BASE}/attachment-not-permitted",
            extras={"code": code},
        )


class AttachmentMissingError(APIError):
    def __init__(self, *, key: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Attachment not uploaded",
            detail=(
                "The referenced attachment_s3_key was not found in object "
                "storage. Upload the file via the presigned URL first."
            ),
            type_=f"{_TYPE_BASE}/attachment-missing",
            extras={"attachment_s3_key": key},
        )


# ---- CS-2/3: signal templates ----------------------------------------------


class SignalTemplateNotFoundError(APIError):
    def __init__(self, template_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Signal template not found",
            detail=f"No signal template with id {template_id} in this tenant.",
            type_=f"{_TYPE_BASE}/template-not-found",
            extras={"template_id": str(template_id)},
        )


class SignalTemplateCodeAlreadyExistsError(APIError):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Signal template code already exists",
            detail=f"An active signal template with code {code!r} already exists.",
            type_=f"{_TYPE_BASE}/template-code-exists",
            extras={"code": code},
        )


class SignalTemplateMembersInvalidError(APIError):
    """Catch-all for template-member shape errors caught pre-DB:
    duplicate definition_ids, duplicate positions, or member rows
    pointing at definitions that don't exist (or are soft-deleted)."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid template members",
            detail=detail,
            type_=f"{_TYPE_BASE}/template-members-invalid",
        )


class CsvImportFailedError(APIError):
    """CS-7: strict-mode CSV import rejected the whole batch because at
    least one row failed validation. The ``errors`` extras carry a list
    of ``{row_number, field, message}`` dicts the FE can render inline
    next to the rows the operator uploaded."""

    def __init__(self, *, errors: list[dict[str, object]]) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Signal CSV import rejected",
            detail=(
                f"{len(errors)} row(s) failed validation; no observations were "
                f"inserted. Fix the rows and re-upload."
            ),
            type_=f"{_TYPE_BASE}/csv-import-failed",
            extras={"errors": errors},
        )


class CsvImportTooLargeError(APIError):
    """File exceeded the byte cap. Distinct from CsvImportFailedError
    so the FE can render a specific message ("file too large") vs the
    per-row validation list."""

    def __init__(self, *, size_bytes: int, limit_bytes: int) -> None:
        super().__init__(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            title="Signal CSV import too large",
            detail=(
                f"Uploaded file ({size_bytes} bytes) exceeds the " f"{limit_bytes}-byte limit."
            ),
            type_=f"{_TYPE_BASE}/csv-import-too-large",
            extras={"size_bytes": size_bytes, "limit_bytes": limit_bytes},
        )
