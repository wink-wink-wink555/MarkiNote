"""AI API 提供商适配层 — DeepSeek / Kimi (Moonshot)"""
import json
import requests

PROVIDERS = {
    'deepseek': {
        'name': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'models': [
            {'id': 'deepseek-chat', 'name': 'DeepSeek-V3'},
        ]
    },
    'kimi': {
        'name': 'Kimi (Moonshot)',
        'base_url': 'https://api.moonshot.cn/v1',
        'models': [
            {'id': 'moonshot-v1-8k', 'name': 'Moonshot 8K'},
            {'id': 'moonshot-v1-32k', 'name': 'Moonshot 32K'},
            {'id': 'moonshot-v1-128k', 'name': 'Moonshot 128K'},
        ]
    }
}


def get_providers_info():
    return {k: {'name': v['name'], 'models': v['models']} for k, v in PROVIDERS.items()}


def validate_api_key(provider_id, api_key):
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return False, '未知提供商'
    try:
        url = f"{provider['base_url']}/models"
        resp = requests.get(url, headers={'Authorization': f'Bearer {api_key}'}, timeout=10)
        if resp.status_code == 200:
            return True, '连接成功'
        elif resp.status_code == 401:
            return False, 'API Key 无效'
        else:
            return False, f'请求失败: HTTP {resp.status_code}'
    except requests.Timeout:
        return False, '连接超时'
    except Exception as e:
        return False, f'连接失败: {str(e)}'


def stream_chat_completion(messages, tools, api_key, provider_id, model_id):
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

    url = f"{provider['base_url']}/chat/completions"
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    body = {
        'model': model_id,
        'messages': messages,
        'stream': True,
        'temperature': 0.7,
    }

    if tools:
        body['tools'] = tools
        body['tool_choice'] = 'auto'

    try:
        resp = requests.post(url, headers=headers, json=body, stream=True, timeout=120)
        if resp.status_code != 200:
            try:
                err = resp.json()
                msg = err.get('error', {}).get('message', resp.text[:200])
            except Exception:
                msg = resp.text[:200]
            yield {'type': 'error', 'message': f'API 错误 ({resp.status_code}): {msg}'}
            return

        resp.encoding = 'utf-8'
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith('data: '):
                continue
            data_str = line[6:]
            if data_str.strip() == '[DONE]':
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

            if 'content' in delta and delta['content']:
                yield {'type': 'content', 'content': delta['content']}

            if 'tool_calls' in delta:
                for tc in delta['tool_calls']:
                    idx = tc.get('index', 0)
                    if 'id' in tc:
                        yield {
                            'type': 'tool_call_start',
                            'index': idx,
                            'id': tc['id'],
                            'name': tc.get('function', {}).get('name', '')
                        }
                    if 'function' in tc and 'arguments' in tc['function']:
                        yield {
                            'type': 'tool_call_args',
                            'index': idx,
                            'arguments': tc['function']['arguments']
                        }

            if finish == 'stop':
                yield {'type': 'done'}
                return
            elif finish == 'tool_calls':
                yield {'type': 'tool_calls_complete'}

        usage = data.get('usage') if 'data' in dir() else None
        if usage:
            yield {'type': 'usage', 'usage': usage}

    except requests.Timeout:
        yield {'type': 'error', 'message': 'API 请求超时（120秒）'}
    except requests.ConnectionError:
        yield {'type': 'error', 'message': '无法连接到 API 服务器，请检查网络'}
    except Exception as e:
        yield {'type': 'error', 'message': f'请求异常: {str(e)}'}
