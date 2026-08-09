from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_non_streaming_latency_alert_excludes_every_sse_route() -> None:
    rules = (
        REPOSITORY_ROOT / "infra/prometheus/rules/markinote.yaml"
    ).read_text(encoding="utf-8")

    assert 'route!="/api/ai/chat"' not in rules
    assert 'route!="/api/v1/agent/chat"' in rules
    assert "runbook_path:" not in rules
    assert rules.count("runbook_url: https://github.com/wink-wink-wink555/MarkiNote#") == 4
