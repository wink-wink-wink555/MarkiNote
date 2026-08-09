from unittest import mock

import pytest

from markinote_api.modules.agent.provider import (
    PROVIDERS,
    stream_chat_completion,
    validate_api_key,
)
from markinote_api.modules.agent.schemas import ChatRequest


class _ContextResponse:
    def __init__(self, *, status_code=200, payload=None, lines=None):
        self.status_code = status_code
        self._payload = payload
        self._lines = lines or []
        self.encoding = "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_lines(self, *, decode_unicode=True):
        assert decode_unicode
        yield from self._lines


def test_provider_registry_defaults_use_reviewed_current_models():
    assert ChatRequest(message="hello").model == "deepseek-v4-flash"
    assert PROVIDERS["deepseek"]["default_model"] == "deepseek-v4-flash"
    assert PROVIDERS["kimi"]["default_model"] == "kimi-k2.6"
    configured = {
        model["id"]
        for provider in PROVIDERS.values()
        for model in provider["models"]
    }
    assert "deepseek-" + "chat" not in configured
    assert not any(model.startswith("moonshot-v1-") for model in configured)


@pytest.mark.parametrize(
    ("provider_id", "model_id"),
    (("deepseek", "deepseek-v4-flash"), ("kimi", "kimi-k2.6")),
)
def test_provider_chat_requests_disable_thinking_without_invalid_temperature(
    provider_id,
    model_id,
):
    response = _ContextResponse(lines=["data: [DONE]"])
    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post",
        return_value=response,
    ) as post:
        events = list(
            stream_chat_completion(
                [{"role": "user", "content": "hello"}],
                [],
                "transient-provider-key",
                provider_id,
                model_id,
            )
        )

    assert events == [{"type": "done"}]
    body = post.call_args.kwargs["json"]
    assert body["model"] == model_id
    assert body["thinking"] == {"type": "disabled"}
    assert "temperature" not in body


def test_key_validation_requires_a_reviewed_model_intersection():
    response = _ContextResponse(
        payload={"data": [{"id": "deepseek-v4-flash"}, {"id": "future-unknown-model"}]},
    )
    with mock.patch(
        "markinote_api.modules.agent.provider.requests.get",
        return_value=response,
    ):
        assert validate_api_key("deepseek", "transient-provider-key") == (True, "连接成功")


@pytest.mark.parametrize(
    "payload",
    (
        {"data": [{"id": "future-unknown-model"}]},
        {"data": []},
    ),
)
def test_key_validation_fails_closed_without_a_compatible_model(payload):
    response = _ContextResponse(payload=payload)
    with mock.patch(
        "markinote_api.modules.agent.provider.requests.get",
        return_value=response,
    ):
        ok, message = validate_api_key("deepseek", "transient-provider-key")
    assert not ok
    assert "兼容模型" in message


def test_key_validation_fails_closed_on_malformed_model_response():
    response = _ContextResponse(payload=ValueError("invalid json"))
    with mock.patch(
        "markinote_api.modules.agent.provider.requests.get",
        return_value=response,
    ):
        assert validate_api_key("deepseek", "transient-provider-key") == (
            False,
            "模型列表响应无效",
        )
