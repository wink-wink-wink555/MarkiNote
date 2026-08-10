from __future__ import annotations

import runpy
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = runpy.run_path(
    str(REPOSITORY_ROOT / "infra/ci/production-compose-preflight.py"),
    run_name="production_compose_preflight_contract",
)
PreflightFailure = PREFLIGHT["PreflightFailure"]
validate_release_version = PREFLIGHT["validate_release_version"]


def test_release_tags_are_created_only_after_both_final_digest_scans() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release-images.yml").read_text(
        encoding="utf-8"
    )

    quarantine = workflow.index("Build, attest, and push quarantine manifest")
    amd64_scan = workflow.index("Scan final published linux/amd64 manifest by digest")
    arm64_scan = workflow.index("Scan final published linux/arm64 manifest by digest")
    promotion = workflow.index("Promote both scanned digests to formal tags")
    assert quarantine < amd64_scan < arm64_scan < promotion
    assert "tags: ${{ steps.image_repository.outputs.value }}:quarantine-" in workflow
    assert "promote-release-pair:" in workflow
    assert "needs: publish" in workflow
    assert "pattern: release-*-quarantine" in workflow
    assert '"api", "gateway"' in workflow
    assert 'docker buildx imagetools create \\' in workflow
    assert '"$image_repository@$digest"' in workflow
    assert "Promote scanned digest to immutable formal tags" not in workflow


def test_release_manifest_has_one_unambiguous_promotion_status() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release-images.yml").read_text(
        encoding="utf-8"
    )

    assert "publication_stage=quarantine_pending_scan" in workflow
    assert "promotion_status=pending_scan" not in workflow
    assert workflow.count("promotion_status=complete") == 1


def test_releases_are_repository_serialized_and_use_the_full_source_sha_tag() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release-images.yml").read_text(
        encoding="utf-8"
    )

    assert "group: release-images-${{ github.repository }}" in workflow
    assert "group: release-images-${{ github.ref }}" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "type=sha,prefix=sha-,format=long" in workflow


def test_release_image_repositories_are_lowercase_normalized_for_ghcr() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release-images.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count('repository="${SOURCE_REPOSITORY,,}"') == 2
    assert workflow.count("SOURCE_REPOSITORY: ${{ github.repository }}") == 2
    assert "ghcr.io/${{ github.repository }}" not in workflow
    assert "images: ${{ steps.image_repository.outputs.value }}" in workflow
    assert "RELEASE_REPOSITORY: ${{ steps.repository_prefix.outputs.value }}" in workflow


def test_release_tag_is_bound_to_the_packaged_project_version() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release-images.yml").read_text(
        encoding="utf-8"
    )

    assert "import tomllib" in workflow
    assert '["project"]["version"]' in workflow
    assert '[[ "$GITHUB_REF_NAME" != "v$project_version" ]]' in workflow


def test_formal_tag_preflight_is_pair_wide_and_lookup_failures_fail_closed() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release-images.yml").read_text(
        encoding="utf-8"
    )

    preflight = workflow.index("Fail closed unless every formal tag is absent")
    promotion = workflow.index("Promote both scanned digests to formal tags")
    assert preflight < promotion
    assert 'test "${#formal_tags[@]}" -eq 4' in workflow
    assert '*"manifest unknown"*|*"not found"*' in workflow
    assert "without an authoritative not-found response" in workflow
    assert "Refusing to overwrite an existing immutable formal tag" in workflow
    assert workflow.count("docker buildx imagetools create") == 1


def test_pair_promotion_validates_both_digests_platform_reports_and_hashes() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/release-images.yml").read_text(
        encoding="utf-8"
    )

    assert 'for image_name in ("api", "gateway")' in workflow
    assert '{"linux/amd64", "linux/arm64"}' in workflow
    assert "hashlib.sha256(report_bytes).hexdigest()" in workflow
    assert 'evidence.get("manifestDigest") != digest' in workflow
    assert 'evidence.get("formalTagsCreated") is not False' in workflow
    assert "api-and-gateway-both-platform-final-digest-scans-passed" in workflow


@pytest.mark.parametrize("version", ("local", "ci", "unknown", "4.0.0", "v4.0", "v04.0.0"))
def test_production_preflight_rejects_non_release_versions(version: str) -> None:
    with pytest.raises(PreflightFailure, match=r"vMAJOR\.MINOR\.PATCH"):
        validate_release_version(version)


def test_production_preflight_accepts_an_exact_stable_release_version() -> None:
    assert validate_release_version("v4.0.0") == "v4.0.0"


def test_ci_production_preflight_uses_and_negatively_tests_a_release_version() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Validate digest-only production Compose model", 1)[1].split(
        "- name: Build images",
        1,
    )[0]
    assert "MARKINOTE_VERSION: v4.0.0" in step
    assert "if MARKINOTE_VERSION=local" in step


def test_ci_exposes_one_stable_aggregate_required_status() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = workflow.split("\n  required:\n", 1)[1]

    assert "name: CI required" in required
    assert "if: always()" in required
    assert "name: Require every CI job to succeed" in required
    for job in (
        "backend",
        "windows-compatibility",
        "frontend",
        "contract",
        "e2e",
        "postgres-integration",
        "image",
        "security",
    ):
        assert f"      - {job}" in required
        assert f"needs.{job}.result" in required
