"""Stable, transport-neutral errors for the documents module."""

from __future__ import annotations

from collections.abc import Mapping


class DocumentError(Exception):
    """An expected document operation failure safe to expose to clients."""

    code = "document_error"
    status_code = 400

    def __init__(self, message: str, *, details: Mapping | None = None):
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class DocumentValidationError(DocumentError):
    code = "invalid_document_request"


class DocumentPathError(DocumentError):
    code = "invalid_path"
    status_code = 403


class DocumentNotFound(DocumentError):
    code = "document_not_found"
    status_code = 404


class DocumentAlreadyExists(DocumentError):
    # Name collisions are client errors with a stable machine-readable code.
    code = "document_already_exists"
    status_code = 400


class DocumentConflict(DocumentError):
    code = "document_version_conflict"
    status_code = 409


class DocumentCapacityExceeded(DocumentError):
    code = "document_capacity_exceeded"
    status_code = 413


class DocumentPermissionDenied(DocumentError):
    code = "document_permission_denied"
    status_code = 403
