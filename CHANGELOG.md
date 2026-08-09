# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The repository uses semantic versioning for released API and container artifacts.

## [Unreleased]

> The repository has not yet created its first immutable release tag. The
> entries below describe the `4.0.0` candidate and must stay unreleased until
> the full release workflow, external approvals, and image digests exist.
> The candidate does not yet have successful remote workflow or release evidence.
> Local Chromium and WebKit validation does not stand in for a successful
> remote Chromium/Firefox/WebKit matrix; Firefox could not launch reliably in
> this Windows graphics environment.
> GitHub Actions still use version tags and base images use exact patch tags,
> not reviewed commit SHAs or image digests; Dependabot covers both ecosystems.

### Added

- Independent branch-aware coverage gates for the FastAPI backend and React application.
- Repository definitions for Windows/Linux validation, release evidence, SBOM generation, container security checks, and self-contained README operational guidance; remote execution is not yet evidenced.
- React 19, TypeScript, Vite, TanStack Query, CodeMirror, generated OpenAPI client, and desktop/mobile browser tests.
- FastAPI modular monolith with versioned REST/SSE contracts, RFC 9457 errors, health/readiness, Prometheus metrics, and optional OpenTelemetry export.
- PostgreSQL/Alembic profile alongside the local JSON/SQLite profile, including metadata-only agent-run lifecycle auditing.
- Non-root, read-only API and NGINX images plus Compose profiles for PostgreSQL, Redis, and observability.
- Durable AI command leases, owner fencing, crash recovery, capacity-bounded before-image backups, and conflict-safe compensation.
- Conversation-scoped command identifiers and strict `(run_id, conversation_id, tool_name)` ownership validation across JSON and SQL journals.
- Dry-run-first, bounded agent-run crash reconciliation guarded by explicit single-writer acknowledgement.
- Dry-run-first, bounded SQL command/audit retention with separate TTLs and protection for active, recoverable, and snapshot-backed records.
- Configurable provider frame/event/byte/time, content, tool-argument, downstream SSE-event, and browser SSE parser budgets.
- A dedicated API egress network and test-only incremental `fake-provider` fixture so container SSE checks do not contact a real AI provider.
- Full local-volume restore rehearsal for library, backups, trash, JSON conversations, and SQLite state, alongside the isolated PostgreSQL restore rehearsal.
- Repository definitions for gateway SSE, PostgreSQL/document restore, and scheduled Chromium/Firefox/WebKit regression jobs; remote execution remains an external acceptance item.
- A real BuildKit context probe and final-image filesystem scans that reject nested environment files, package-manager credentials, private-key material, databases, logs, secrets, and runtime payloads.

### Changed

- The only application entry point is now NGINX + FastAPI + React, with the repository-root Compose model providing the default local experience.
- Document mutations now use portable path validation, atomic writes, optimistic versions, quotas, trash retention, and explicit recovery semantics.
- Browser access tokens and transient AI credentials are memory-only.
- AI document-write permission now defaults to disabled. Any mutation after
  `fetch_url` or `web_search` requires one-time approval bound to the exact
  tool name and arguments, and external content retains an explicit untrusted boundary.
- Updated the reviewed provider allowlist to DeepSeek V4 Flash/Pro and Kimi
  K2.6, disabled thinking for the current tool protocol, and made key validation
  fail closed when `/models` has no compatible model.
- Rollback requests now require an explicit operation index; the public API no
  longer exposes non-atomic whole-group rollback.
- Retired the compatibility facade, its browser asset pipeline, transitional configuration, route contracts, tests, and image payloads.
- Image release automation now builds to a run-scoped quarantine tag, scans both final platform images by manifest digest, and promotes formal tags only after those scans pass; no formal release has been published yet.
- Release publication is serialized per repository and uses the full source SHA tag, closing the check-then-promote race between concurrent SemVer tag runs.
- Production preflight now requires an exact stable `vMAJOR.MINOR.PATCH` application version, so development labels cannot be promoted as a release artifact.
- Folder upload now applies an eight-starts-per-second client throttle, bounded `429` retry, overlap locking, and an explicit unsupported-file error without changing accepted document types.
- Agent tool results are durably attached to the conversation before streaming, and canonical argument/frame admission runs before any command claim or mutation so a rollback handle cannot be lost to JSON expansion or a combined SSE-frame limit.
- Conversation truncation now returns success only after its file rollback and conversation commit both succeed; an uncommitted Saga returns a stable `409` and the React client keeps its current history.
- Trash restore now treats the payload move as its commit point: post-commit metadata cleanup failures are logged for maintenance but no longer report a false restore failure.
- Python project builds use separately hash-locked build/runtime environments, offline no-build-isolation wheel construction, and a runtime image with Python packaging tools removed.

### Security

- Added Trusted Host, Origin, rate/body limits, safe Markdown rendering, SSRF redirect/DNS/peer validation, secret redaction tests, dependency audits, CodeQL, Trivy, and SBOMs.
- The React application and gateway now provide the sole browser security policy; `script-src` remains self-only and no transitional page assets enter either image.
- API structured logs now use an explicit metadata allowlist, avoid arbitrary argument interpolation, redact credential-shaped text, and omit exception messages and user payloads.
- Problem/SSE responses, command journals, backup manifests, and compensation results use stable public errors instead of raw exception text or local paths.
- OpenTelemetry removes query strings and sensitive header attributes before export and sanitizes URL, span, event, and exception data across FastAPI, HTTPX, and `requests` instrumentation.
- `fetch_url` keeps its raw query string only for the in-memory outbound request; SSE events, conversation/tool-call records, command results, errors, and subagent prompts retain only a query/fragment-free display URL.
- Migration and restore-rehearsal failure paths emit bounded operator-safe evidence without reflecting database identifiers, local paths, or raw exception text.
- Prometheus AI tool labels use a fixed allowlist and collapse provider-controlled unknown names to `unknown`.
- Refreshed the Web test-tool lock from `glob` 10.4.5 to 10.5.0 within its existing semver range, closing GHSA-5j98-mcp5-4vw2; full and production-only npm audits now report zero known vulnerabilities locally.
- Refreshed Mermaid/DOMPurify, PostCSS, Nano ID, YAML, and glob-matching
  transitive patches; full and production-only audits for both Node dependency
  units now report zero known vulnerabilities locally.
- Upgraded the Python test toolchain to pytest 9.1.1 and pytest-asyncio 1.4.0, closing PYSEC-2026-1845; the frozen all-extras `pip-audit` now reports no known vulnerabilities locally and audits the complete uv export without re-resolving dependencies.
