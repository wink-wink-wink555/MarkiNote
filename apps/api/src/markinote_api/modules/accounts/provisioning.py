"""Idempotent default content for a newly created account workspace."""
from __future__ import annotations

from contextlib import suppress

from markinote_api.modules.documents.errors import DocumentAlreadyExists
from markinote_api.modules.documents.service import DocumentService

DEFAULT_FOLDER = "Getting Started"
DEFAULT_DOCUMENTS = {
    "Welcome.md": (
        "# Welcome to MarkiNote\n\n"
        "Your workspace is isolated from every other account and stored in the database.\n\n"
        "- Document quota: 30 MiB\n"
        "- FinanceMCP tools are available to the AI assistant by default.\n"
        "- Configure personal API credentials from Settings; values are encrypted at rest.\n"
    ),
    "FinanceMCP.md": (
        "# FinanceMCP\n\n"
        "Ask the assistant for stock, fund, macroeconomic, futures, news, money-flow, "
        "and company-performance analysis. Tushare and Qveris credentials belong to "
        "your account and are never shared with another workspace.\n"
    ),
}


def provision_default_workspace(documents: DocumentService) -> None:
    with suppress(DocumentAlreadyExists):
        documents.create_folder("", DEFAULT_FOLDER)
    for filename, content in DEFAULT_DOCUMENTS.items():
        with suppress(DocumentAlreadyExists):
            documents.create_file(DEFAULT_FOLDER, filename, content)
