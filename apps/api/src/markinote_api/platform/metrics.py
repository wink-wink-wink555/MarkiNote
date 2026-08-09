"""Low-cardinality application metrics.

Metric labels are deliberately limited to server-controlled enumerations.  In
particular, paths, conversation ids, model ids, command ids, and user-provided
values must never become labels.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

AI_PROVIDER_TIME_TO_FIRST_CONTENT = Histogram(
    "markinote_ai_provider_time_to_first_content_seconds",
    (
        "Accumulated time blocked on the upstream provider until the first "
        "non-empty content chunk. Client backpressure and tool execution are excluded."
    ),
    ("provider",),
)

AI_PROVIDER_UPSTREAM_WAIT = Histogram(
    "markinote_ai_provider_upstream_wait_seconds",
    (
        "Accumulated time blocked on the upstream provider connection and stream "
        "chunks for one provider request. Client backpressure and tool execution are excluded."
    ),
    ("provider", "outcome"),
)

OPERATION_ROLLBACK_ATTEMPTS = Counter(
    "markinote_operation_rollback_attempts_total",
    "Backup rollback executions by fixed call site and storage outcome.",
    ("source", "outcome"),
)

DOCUMENT_CONFLICTS = Counter(
    "markinote_document_conflicts_total",
    "Optimistic document save conflicts by HTTP adapter.",
    ("adapter",),
)
