"""AI API 提供商适配层 — DeepSeek / Kimi (Moonshot)"""
import json
import logging
import time

import requests

from markinote_api.platform.metrics import (
    AI_PROVIDER_TIME_TO_FIRST_CONTENT,
    AI_PROVIDER_UPSTREAM_WAIT,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_PROVIDER_FRAME_BYTES = 256 * 1024
DEFAULT_MAX_PROVIDER_EVENTS = 4_096
DEFAULT_MAX_PROVIDER_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_PROVIDER_ELAPSED_SECONDS = 10 * 60


class _ProviderStreamBoundaryError(RuntimeError):
    """Stable internal signal for an untrusted upstream stream boundary."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.public_message = message


def _iter_bounded_sse_lines(response, max_frame_bytes):
    """Yield decoded lines without allowing ``requests`` to build an unbounded frame."""
    if hasattr(response, 'iter_content'):
        pending = bytearray()
        frame_bytes = 0
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
            if not chunk:
                continue
            raw_chunk = chunk.encode('utf-8') if isinstance(chunk, str) else bytes(chunk)
            pending.extend(raw_chunk)
            while True:
                newline = pending.find(b'\n')
                if newline < 0:
                    break
                raw_line = bytes(pending[:newline])
                del pending[:newline + 1]
                if raw_line.endswith(b'\r'):
                    raw_line = raw_line[:-1]
                frame_bytes += len(raw_line) + 1
                if frame_bytes > max_frame_bytes:
                    raise _ProviderStreamBoundaryError(
                        'provider_frame_limit_exceeded',
                        'AI provider sent an oversized stream frame.',
                    )
                yield raw_line.decode('utf-8', errors='replace')
                if not raw_line:
                    frame_bytes = 0
            if frame_bytes + len(pending) > max_frame_bytes:
                raise _ProviderStreamBoundaryError(
                    'provider_frame_limit_exceeded',
                    'AI provider sent an oversized stream frame.',
                )
        if pending:
            frame_bytes += len(pending)
            if frame_bytes > max_frame_bytes:
                raise _ProviderStreamBoundaryError(
                    'provider_frame_limit_exceeded',
                    'AI provider sent an oversized stream frame.',
                )
            yield bytes(pending).decode('utf-8', errors='replace')
        return

    # Small response doubles used by unit tests expose only ``iter_lines``.
    frame_bytes = 0
    for line in response.iter_lines(decode_unicode=True):
        text = line if isinstance(line, str) else bytes(line).decode('utf-8', errors='replace')
        frame_bytes += len(text.encode('utf-8')) + 1
        if frame_bytes > max_frame_bytes:
            raise _ProviderStreamBoundaryError(
                'provider_frame_limit_exceeded',
                'AI provider sent an oversized stream frame.',
            )
        yield text
        if not text:
            frame_bytes = 0


PROVIDERS = {
    'deepseek': {
        'name': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'default_model': 'deepseek-v4-flash',
        'request_options': {'thinking': {'type': 'disabled'}},
        'models': [
            {'id': 'deepseek-v4-flash', 'name': 'DeepSeek V4 Flash'},
            {'id': 'deepseek-v4-pro', 'name': 'DeepSeek V4 Pro'},
        ]
    },
    'kimi': {
        'name': 'Kimi (Moonshot 中国区)',
        'base_url': 'https://api.moonshot.cn/v1',
        'default_model': 'kimi-k2.6',
        'request_options': {'thinking': {'type': 'disabled'}},
        'models': [
            {'id': 'kimi-k2.6', 'name': 'Kimi K2.6'},
        ]
    }
}
TITLE_PROMPTS = {
    'zh-CN': '根据以下对话生成不超过15个字的中文标题，只返回标题。',
    'en': 'Generate a short English title of at most 8 words. Return only the title.',
    'fr': 'Générez un titre français court de 8 mots maximum. Retournez uniquement le titre.',
    'ja': '会話に基づき15文字以内の日本語タイトルだけを返してください。',
}


def get_providers_info():
    return {k: {'name': v['name'], 'models': v['models']} for k, v in PROVIDERS.items()}


def _provider_model_ids(provider):
    models = provider.get('models', [])
    return {
        str(model['id'])
        for model in models
        if isinstance(model, dict) and isinstance(model.get('id'), str)
    }


def _resolve_provider_model(provider, requested_model):
    if requested_model in _provider_model_ids(provider):
        return requested_model
    return str(provider['default_model'])


def _provider_request_options(provider):
    options = provider.get('request_options', {})
    # The registry is process-owned, but return a fresh nested mapping so a
    # request builder can never mutate the capability definition accidentally.
    return {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in options.items()
    } if isinstance(options, dict) else {}


def validate_api_key(provider_id, api_key):
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return False, '未知提供商'
    try:
        url = f"{provider['base_url']}/models"
        with requests.get(url, headers={'Authorization': f'Bearer {api_key}'}, timeout=(5, 10)) as resp:
            if resp.status_code == 200:
                try:
                    payload = resp.json()
                    remote_models = payload.get('data', [])
                    remote_ids = {
                        str(model['id'])
                        for model in remote_models
                        if isinstance(model, dict) and isinstance(model.get('id'), str)
                    }
                except (AttributeError, TypeError, ValueError):
                    return False, '模型列表响应无效'
                if remote_ids & _provider_model_ids(provider):
                    return True, '连接成功'
                return False, 'API Key 有效，但未发现当前兼容模型'
            if resp.status_code == 401:
                return False, 'API Key 无效'
            return False, f'请求失败: HTTP {resp.status_code}'
    except requests.Timeout:
        return False, '连接超时'
    except requests.RequestException:
        LOGGER.warning('AI key validation request failed')
        return False, '连接失败，请检查网络或服务地址'


def generate_conversation_title(user_message, assistant_message, api_key, provider_id, model_id, language):
    """Generate a bounded optional title without leaking credentials on failure."""
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return None
    title_model = _resolve_provider_model(provider, model_id)
    body = {
        'model': title_model,
        'messages': [
            {'role': 'system', 'content': TITLE_PROMPTS.get(language, TITLE_PROMPTS['zh-CN'])},
            {
                'role': 'user',
                'content': f'User: {user_message[:200]}\nAI: {(assistant_message or "")[:300]}',
            },
        ],
        'max_tokens': 30,
    }
    body.update(_provider_request_options(provider))
    try:
        with requests.post(
            f"{provider['base_url']}/chat/completions",
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=body,
            timeout=(5, 10),
        ) as response:
            if response.status_code != 200:
                return None
            title = response.json()['choices'][0]['message']['content']
            return str(title).strip().strip('"\'“”')[:50] or None
    except (KeyError, TypeError, ValueError, requests.RequestException):
        LOGGER.warning('Automatic conversation title generation failed')
        return None


def stream_chat_completion(
    messages,
    tools,
    api_key,
    provider_id,
    model_id,
    *,
    base_url_override=None,
    max_frame_bytes=DEFAULT_MAX_PROVIDER_FRAME_BYTES,
    max_events=DEFAULT_MAX_PROVIDER_EVENTS,
    max_total_bytes=DEFAULT_MAX_PROVIDER_BYTES,
    max_elapsed_seconds=DEFAULT_MAX_PROVIDER_ELAPSED_SECONDS,
):
    """
    流式调用 AI API，yield 解析后的事件字典:
      {"type": "content", "content": "..."}
      {"type": "tool_call_start", "index": 0, "id": "...", "name": "..."}
      {"type": "tool_call_args", "index": 0, "arguments": "..."}
      {"type": "done"}
      {"type": "error", "message": "..."}
    """
    provider = PROVIDERS.get(provider_id)
    if not provider:
        yield {'type': 'error', 'message': f'未知提供商: {provider_id}'}
        return

    if min(max_frame_bytes, max_events, max_total_bytes, max_elapsed_seconds) <= 0:
        raise ValueError('provider stream limits must be positive')

    # ``base_url_override`` is injected only by the typed test-only Settings
    # guard. Production always uses the reviewed provider registry above.
    provider_base_url = base_url_override or provider['base_url']
    url = f"{provider_base_url}/chat/completions"
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    body = {
        'model': model_id,
        'messages': messages,
        'stream': True,
    }
    body.update(_provider_request_options(provider))

    if tools:
        body['tools'] = tools
        body['tool_choice'] = 'auto'

    # This synchronous generator is suspended whenever its consumer applies
    # backpressure.  Wall-clock time between the first and last ``yield`` would
    # therefore mix provider latency with client/network time.  Accumulate only
    # the blocking calls into ``requests`` and ``iter_lines`` instead.
    upstream_wait = 0.0
    first_content_observed = False
    outcome = 'cancelled'
    stream_started = time.monotonic()
    upstream_events = 0
    upstream_bytes = 0

    def next_upstream_line(lines):
        nonlocal upstream_wait
        started = time.perf_counter()
        try:
            return next(lines)
        finally:
            upstream_wait += time.perf_counter() - started

    try:
        started = time.perf_counter()
        try:
            response_context = requests.post(
                url,
                headers=headers,
                json=body,
                stream=True,
                timeout=(min(10, max_elapsed_seconds), min(120, max_elapsed_seconds)),
            )
        finally:
            upstream_wait += time.perf_counter() - started

        with response_context as resp:
            if time.monotonic() - stream_started > max_elapsed_seconds:
                raise _ProviderStreamBoundaryError(
                    'provider_stream_timeout',
                    'AI provider stream exceeded the elapsed-time safety limit.',
                )
            if resp.status_code != 200:
                outcome = 'error'
                # Provider response bodies can echo prompts, model inputs or
                # credential diagnostics. Keep the public event stable and
                # put only bounded, reviewed metadata into protected logs.
                LOGGER.warning(
                    'AI provider returned a non-success status',
                    extra={'provider': provider_id, 'http_status': resp.status_code},
                )
                yield {'type': 'error', 'message': 'AI 服务拒绝了请求，请检查配置后重试'}
                return
            resp.encoding = 'utf-8'
            lines = iter(_iter_bounded_sse_lines(resp, max_frame_bytes))
            while True:
                try:
                    line = next_upstream_line(lines)
                except StopIteration:
                    # A clean provider round has an explicit DONE/finish
                    # marker. EOF without one is an incomplete upstream stream.
                    outcome = 'error'
                    yield {
                        'type': 'error',
                        'message': 'AI 服务流在完成前中断，请重试',
                    }
                    return
                if time.monotonic() - stream_started > max_elapsed_seconds:
                    raise _ProviderStreamBoundaryError(
                        'provider_stream_timeout',
                        'AI provider stream exceeded the elapsed-time safety limit.',
                    )
                if line:
                    upstream_events += 1
                    upstream_bytes += len(line.encode('utf-8'))
                    if upstream_events > max_events:
                        raise _ProviderStreamBoundaryError(
                            'provider_event_limit_exceeded',
                            'AI provider stream exceeded the event safety limit.',
                        )
                    if upstream_bytes > max_total_bytes:
                        raise _ProviderStreamBoundaryError(
                            'provider_byte_limit_exceeded',
                            'AI provider stream exceeded the byte safety limit.',
                        )
                if not line or not line.startswith('data: '):
                    continue
                data_str = line[6:]
                if data_str.strip() == '[DONE]':
                    outcome = 'success'
                    yield {'type': 'done'}
                    return
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = data.get('choices', [])
                if not choices:
                    continue
                delta = choices[0].get('delta', {})
                finish = choices[0].get('finish_reason')
                if delta.get('content'):
                    if not first_content_observed:
                        AI_PROVIDER_TIME_TO_FIRST_CONTENT.labels(provider_id).observe(upstream_wait)
                        first_content_observed = True
                    yield {'type': 'content', 'content': delta['content']}
                for tool_call in delta.get('tool_calls', []):
                    index = tool_call.get('index', 0)
                    if 'id' in tool_call:
                        yield {
                            'type': 'tool_call_start',
                            'index': index,
                            'id': tool_call['id'],
                            'name': tool_call.get('function', {}).get('name', ''),
                        }
                    arguments = tool_call.get('function', {}).get('arguments')
                    if arguments is not None:
                        yield {'type': 'tool_call_args', 'index': index, 'arguments': arguments}
                if finish == 'stop':
                    outcome = 'success'
                    yield {'type': 'done'}
                    return
                if finish == 'tool_calls':
                    outcome = 'success'
                    yield {'type': 'tool_calls_complete'}

    except _ProviderStreamBoundaryError as error:
        outcome = 'error'
        yield {'type': 'error', 'code': error.code, 'message': error.public_message}
    except GeneratorExit:
        # Keep a terminal result if the consumer closes immediately after
        # receiving it; otherwise an interrupted iterator is a cancellation.
        if outcome not in {'success', 'error'}:
            outcome = 'cancelled'
        raise
    except requests.Timeout:
        outcome = 'error'
        yield {'type': 'error', 'message': 'API 请求超时（120秒）'}
    except requests.ConnectionError:
        outcome = 'error'
        yield {'type': 'error', 'message': '无法连接到 API 服务器，请检查网络'}
    except requests.RequestException:
        outcome = 'error'
        LOGGER.warning('AI streaming request failed')
        yield {'type': 'error', 'message': 'API 请求失败，请检查网络后重试'}
    except Exception:
        outcome = 'error'
        raise
    finally:
        AI_PROVIDER_UPSTREAM_WAIT.labels(provider_id, outcome).observe(upstream_wait)
