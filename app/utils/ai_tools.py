"""AI 工具定义与执行逻辑"""
import os
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文档库中指定文件的内容。支持指定行范围来读取文件的部分内容，适合阅读大文件。如果内容被截断，请使用 start_line 和 end_line 参数分段读取剩余部分。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件相对路径，例如 'notes/hello.md'"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（从1开始），不指定则从第1行开始"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号（包含该行），不指定则读到文件末尾"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入完整内容到指定文件（会覆盖原内容）。修改前会自动备份。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件相对路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的完整文件内容"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "使用查找替换方式局部编辑文件。适合小范围修改，比 write_file 更安全。修改前会自动备份。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件相对路径"
                    },
                    "old_text": {
                        "type": "string",
                        "description": "要查找并替换的原文本（必须精确匹配）"
                    },
                    "new_text": {
                        "type": "string",
                        "description": "替换后的新文本"
                    }
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "创建新文件并写入初始内容。如果文件已存在则会报错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "新文件的相对路径，例如 'notes/new_note.md'"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件的初始内容"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "创建新文件夹，支持多级目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件夹相对路径，例如 'notes/subfolder'"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_item",
            "description": "删除文件或文件夹。删除前会自动备份。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的文件或文件夹的相对路径"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_item",
            "description": "移动或重命名文件/文件夹。操作前会自动备份。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "源文件/文件夹的相对路径"
                    },
                    "target": {
                        "type": "string",
                        "description": "目标路径（如果是文件夹则移动到其中，如果包含文件名则同时重命名）"
                    }
                },
                "required": ["source", "target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出指定目录的内容，包括文件和子文件夹。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录相对路径，空字符串表示根目录"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "在文档库的文件内容中搜索关键词，返回匹配的文件列表和匹配行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    },
                    "path": {
                        "type": "string",
                        "description": "限定搜索的目录路径（可选，空字符串表示搜索全部）"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "在互联网上搜索信息并返回摘要结果。适用于查找资料、获取最新信息等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "抓取指定 URL 网页的完整内容并返回。适合阅读文章、文档、博客等。对于内容过长的页面会自动生成详细摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的网页 URL，如 'https://example.com/article'"
                    }
                },
                "required": ["url"]
            }
        }
    }
]

SYSTEM_PROMPT_BASE = """你是 MarkiNote AI 助手，一个智能文档管理助手。你可以帮助用户管理 Markdown 文档、回答问题、并执行文件操作。

你拥有以下工具：
- read_file: 读取文件内容（支持 start_line/end_line 参数分段读取大文件）
- write_file: 写入文件内容（自动备份）
- edit_file: 查找替换方式编辑文件（自动备份）
- create_file: 创建新文件
- create_folder: 创建新文件夹
- delete_item: 删除文件或文件夹（自动备份）
- move_item: 移动或重命名（自动备份）
- list_directory: 列出目录内容
- search_files: 在文件内容中搜索关键词
- web_search: 在互联网上搜索信息
- fetch_url: 抓取指定 URL 网页的完整内容（大页面自动摘要）

所有文件操作限制在文档库目录内。每次修改都会自动创建备份，用户可以随时回滚。

使用工具时的注意事项：
1. 修改文件前先用 read_file 了解内容
2. 小范围修改用 edit_file（查找替换），大范围重写用 write_file
3. 操作完成后简要说明做了什么
4. 需要阅读网页内容时，使用 fetch_url 工具传入 URL"""

_LANGUAGE_INSTRUCTIONS = {
    'zh-CN': '\n\n【语言规则 - 最高优先级】你必须始终使用简体中文回复用户。所有回复、解释、工具操作说明都必须使用简体中文。即使用户使用其他语言，你也必须用简体中文回复。这条规则不可违反。',
    'en': '\n\n【Language Rule - HIGHEST PRIORITY】You MUST always respond in English. ALL responses, explanations, and tool operation descriptions MUST be in English. Even if the user writes in another language, you MUST reply in English. This rule is non-negotiable.',
    'fr': "\n\n【Règle linguistique - PRIORITÉ MAXIMALE】Vous DEVEZ toujours répondre en français. TOUTES les réponses, explications et descriptions d'opérations d'outils DOIVENT être en français. Même si l'utilisateur écrit dans une autre langue, vous DEVEZ répondre en français. Cette règle est non négociable.",
    'ja': '\n\n【言語ルール - 最優先】あなたは常に日本語で返答しなければなりません。すべての返答、説明、ツール操作の説明は日本語でなければなりません。ユーザーが他の言語で書いても、日本語で返答してください。このルールは絶対です。',
}

SYSTEM_PROMPT = SYSTEM_PROMPT_BASE + _LANGUAGE_INSTRUCTIONS['zh-CN']


def get_system_prompt(language='zh-CN'):
    instruction = _LANGUAGE_INSTRUCTIONS.get(language, _LANGUAGE_INSTRUCTIONS['zh-CN'])
    return SYSTEM_PROMPT_BASE + instruction


def _safe_path(rel_path, library_dir):
    rel_path = rel_path.replace('\\', '/').strip('/')
    full = os.path.abspath(os.path.join(library_dir, rel_path))
    if not full.startswith(os.path.abspath(library_dir)):
        raise ValueError('路径越界，禁止访问库外文件')
    return full, rel_path


def execute_tool(tool_name, arguments, library_dir, backup_manager, backup_group_id=None, **extra):
    """执行指定工具，返回 (result_text, backup_info)。extra 可携带 api_key/provider_id/model_id 供 subagent 使用。"""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        return '参数解析失败: JSON 格式错误', None

    handlers = {
        'read_file': _read_file,
        'write_file': _write_file,
        'edit_file': _edit_file,
        'create_file': _create_file,
        'create_folder': _create_folder,
        'delete_item': _delete_item,
        'move_item': _move_item,
        'list_directory': _list_directory,
        'search_files': _search_files,
        'web_search': _web_search,
        'fetch_url': _fetch_url,
    }

    handler = handlers.get(tool_name)
    if not handler:
        return f'未知工具: {tool_name}', None

    try:
        return handler(args, library_dir, backup_manager, backup_group_id, **extra)
    except ValueError as e:
        return f'安全错误: {str(e)}', None
    except Exception as e:
        return f'执行失败: {str(e)}', None


def _read_file(args, lib_dir, bm, gid, **extra):
    full, rel = _safe_path(args['path'], lib_dir)
    if not os.path.isfile(full):
        return f'文件不存在: {rel}', None
    with open(full, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    total_lines = len(lines)
    start = args.get('start_line')
    end = args.get('end_line')

    if start is not None or end is not None:
        start_idx = max(0, (start or 1) - 1)
        end_idx = min(total_lines, end or total_lines)
        selected = lines[start_idx:end_idx]
        content = ''.join(selected)
        header = f'文件: {rel} (第 {start_idx + 1}-{end_idx} 行，共 {total_lines} 行)'
    else:
        content = ''.join(lines)
        size = os.path.getsize(full)
        header = f'文件: {rel} ({total_lines} 行, {size} 字节)'

    return f'{header}\n---\n{content}', None


def _write_file(args, lib_dir, bm, gid, **extra):
    full, rel = _safe_path(args['path'], lib_dir)
    if not os.path.isfile(full):
        return f'文件不存在: {rel}（如需创建新文件请用 create_file）', None

    if gid and bm:
        bm.backup_before_modify(gid, 'write_file', rel, f'覆盖写入 {rel}')

    with open(full, 'w', encoding='utf-8') as f:
        f.write(args['content'])

    if gid and bm:
        bm.backup_after_modify(gid, rel)

    return f'已写入文件: {rel} ({len(args["content"])} 字节)', {'type': 'write_file', 'path': rel}


def _edit_file(args, lib_dir, bm, gid, **extra):
    full, rel = _safe_path(args['path'], lib_dir)
    if not os.path.isfile(full):
        return f'文件不存在: {rel}', None

    with open(full, 'r', encoding='utf-8') as f:
        content = f.read()

    old_text = args['old_text']
    new_text = args['new_text']

    if old_text not in content:
        return f'在 {rel} 中未找到要替换的文本片段。请确认原文本是否完全匹配。', None

    count = content.count(old_text)
    if gid and bm:
        bm.backup_before_modify(gid, 'edit_file', rel, f'编辑 {rel}')

    content = content.replace(old_text, new_text, 1)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)

    if gid and bm:
        bm.backup_after_modify(gid, rel)

    info = f'已编辑文件: {rel}（替换了 1 处匹配'
    if count > 1:
        info += f'，还有 {count - 1} 处未替换'
    info += '）'
    return info, {'type': 'edit_file', 'path': rel}


def _create_file(args, lib_dir, bm, gid, **extra):
    full, rel = _safe_path(args['path'], lib_dir)
    if os.path.exists(full):
        return f'文件已存在: {rel}', None

    os.makedirs(os.path.dirname(full), exist_ok=True)
    content = args.get('content', '')

    if gid and bm:
        bm.backup_before_modify(gid, 'create_file', rel, f'创建文件 {rel}')

    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)

    if gid and bm:
        bm.backup_after_modify(gid, rel)

    return f'已创建文件: {rel}', {'type': 'create_file', 'path': rel}


def _create_folder(args, lib_dir, bm, gid, **extra):
    full, rel = _safe_path(args['path'], lib_dir)
    if os.path.exists(full):
        return f'文件夹已存在: {rel}', None

    if gid and bm:
        bm.backup_before_modify(gid, 'create_folder', rel, f'创建文件夹 {rel}')

    os.makedirs(full, exist_ok=True)
    return f'已创建文件夹: {rel}', {'type': 'create_folder', 'path': rel}


def _delete_item(args, lib_dir, bm, gid, **extra):
    full, rel = _safe_path(args['path'], lib_dir)
    if not os.path.exists(full):
        return f'路径不存在: {rel}', None

    if gid and bm:
        bm.backup_before_modify(gid, 'delete_item', rel, f'删除 {rel}')

    import shutil
    if os.path.isfile(full):
        os.remove(full)
        return f'已删除文件: {rel}', {'type': 'delete_item', 'path': rel}
    elif os.path.isdir(full):
        shutil.rmtree(full)
        return f'已删除文件夹: {rel}', {'type': 'delete_item', 'path': rel}
    return f'无法删除: {rel}', None


def _move_item(args, lib_dir, bm, gid, **extra):
    import shutil
    src_full, src_rel = _safe_path(args['source'], lib_dir)
    tgt_full, tgt_rel = _safe_path(args['target'], lib_dir)

    if not os.path.exists(src_full):
        return f'源路径不存在: {src_rel}', None

    if gid and bm:
        bm.backup_before_modify(gid, 'move_item', src_rel, f'移动 {src_rel} -> {tgt_rel}')

    if os.path.isdir(tgt_full) and os.path.exists(tgt_full):
        dst = os.path.join(tgt_full, os.path.basename(src_full))
    else:
        os.makedirs(os.path.dirname(tgt_full), exist_ok=True)
        dst = tgt_full

    shutil.move(src_full, dst)

    if gid and bm:
        bm.backup_after_modify(gid, tgt_rel)

    return f'已移动: {src_rel} -> {tgt_rel}', {'type': 'move_item', 'path': src_rel, 'target': tgt_rel}


def _list_directory(args, lib_dir, bm, gid, **extra):
    path = args.get('path', '')
    if path:
        full, rel = _safe_path(path, lib_dir)
    else:
        full = lib_dir
        rel = ''

    if not os.path.isdir(full):
        return f'目录不存在: {rel or "根目录"}', None

    items = []
    try:
        with os.scandir(full) as entries:
            for entry in entries:
                if entry.name.startswith('.'):
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                    if entry.is_dir(follow_symlinks=False):
                        items.append(f'  📁 {entry.name}/')
                    elif entry.is_file(follow_symlinks=False):
                        size = stat.st_size
                        items.append(f'  📄 {entry.name} ({size} B)')
                except (OSError, PermissionError):
                    continue
    except Exception as e:
        return f'读取目录失败: {str(e)}', None

    items.sort()
    header = f'目录: {rel or "根目录"} ({len(items)} 项)\n'
    return header + '\n'.join(items) if items else header + '  (空目录)', None


def _search_files(args, lib_dir, bm, gid, **extra):
    query = args.get('query', '')
    search_path = args.get('path', '')

    if not query:
        return '搜索关键词不能为空', None

    if search_path:
        base, _ = _safe_path(search_path, lib_dir)
    else:
        base = lib_dir

    if not os.path.isdir(base):
        return f'搜索目录不存在', None

    results = []
    query_lower = query.lower()
    max_results = 20

    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if fname.startswith('.'):
                continue
            ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
            if ext not in ('md', 'markdown', 'txt'):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                matches = []
                for i, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        matches.append(f'  L{i}: {line.rstrip()[:120]}')
                if matches:
                    rel = os.path.relpath(fpath, lib_dir).replace('\\', '/')
                    results.append(f'📄 {rel} ({len(matches)} 处匹配)\n' + '\n'.join(matches[:5]))
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
        if len(results) >= max_results:
            break

    if not results:
        return f'未找到包含 "{query}" 的文件', None
    return f'搜索 "{query}" 的结果 ({len(results)} 个文件):\n\n' + '\n\n'.join(results), None


def _fetch_url(args, lib_dir, bm, gid, **extra):
    """抓取 URL 网页内容，大型页面使用 subagent 摘要"""
    import re
    import html as html_mod
    url = args.get('url', '').strip()
    if not url:
        return '请提供要抓取的 URL', None
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or os.environ.get('ALL_PROXY')

    try:
        import requests as req
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        proxies = {'https': proxy, 'http': proxy} if proxy else None
        resp = req.get(url, headers=headers, proxies=proxies, timeout=20, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or 'utf-8'

        if resp.status_code != 200:
            return f'抓取失败: HTTP {resp.status_code}', None

        content_type = resp.headers.get('Content-Type', '')
        if 'text/html' in content_type or 'application/xhtml' in content_type or not content_type:
            text_content = _extract_text_from_html(resp.text)
        elif 'text/' in content_type or 'json' in content_type or 'xml' in content_type:
            text_content = resp.text
        else:
            return f'不支持的内容类型: {content_type}', None

        if not text_content.strip():
            return f'页面内容为空或无法提取文本: {url}', None

        MAX_DIRECT = 8000
        if len(text_content) <= MAX_DIRECT:
            return f'URL: {url}\n内容长度: {len(text_content)} 字符\n\n---\n{text_content}', None

        api_key = extra.get('api_key')
        provider_id = extra.get('provider_id')
        model_id = extra.get('model_id')
        if api_key and provider_id:
            summary = _summarize_with_subagent(text_content, url, api_key, provider_id, model_id)
            return summary, None

        truncated = text_content[:MAX_DIRECT]
        return f'URL: {url}\n内容长度: {len(text_content)} 字符 (已截断至 {MAX_DIRECT})\n\n---\n{truncated}\n\n[... 内容已截断 ...]', None

    except req.Timeout:
        return f'抓取超时: {url}', None
    except req.ConnectionError:
        return f'无法连接到: {url}', None
    except Exception as e:
        return f'抓取失败: {str(e)}', None


def _extract_text_from_html(html_content):
    """从 HTML 提取可读文本"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'noscript', 'iframe', 'svg']):
            tag.decompose()

        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else ''

        main = soup.find('main') or soup.find('article') or soup.find('body')
        if not main:
            main = soup

        text = main.get_text(separator='\n')
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(line for line in lines if line)

        if title:
            text = f'标题: {title}\n\n{text}'
        return text
    except ImportError:
        import re
        import html as html_mod
        text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html_content, flags=re.I)
        text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.I)
        text = re.sub(r'<!--[\s\S]*?-->', '', text)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
        text = re.sub(r'</p>', '\n\n', text, flags=re.I)
        text = re.sub(r'</div>', '\n', text, flags=re.I)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_mod.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


def _summarize_with_subagent(content, url, api_key, provider_id, model_id):
    """使用 subagent（二次 AI 调用）对大型网页内容生成详细摘要"""
    try:
        import requests as req
        from app.utils.ai_provider import PROVIDERS

        provider = PROVIDERS.get(provider_id)
        if not provider:
            return f'URL: {url}\n内容长度: {len(content)} 字符 (已截断)\n\n---\n{content[:8000]}\n\n[... 摘要生成失败: 未知提供商 ...]'

        summary_model = model_id
        if provider_id == 'kimi':
            summary_model = 'moonshot-v1-8k'
        elif provider_id == 'deepseek':
            summary_model = 'deepseek-chat'

        input_content = content[:20000]

        api_resp = req.post(
            f"{provider['base_url']}/chat/completions",
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': summary_model,
                'messages': [
                    {
                        'role': 'system',
                        'content': '你是一个网页内容分析助手。请对以下网页内容进行全面、详细的总结。'
                                   '保留所有关键信息、数据、要点和重要细节。'
                                   '使用结构化的格式（标题、要点列表等）组织内容。'
                                   '用中文回复。'
                    },
                    {
                        'role': 'user',
                        'content': f'请详细总结以下网页内容:\n\nURL: {url}\n原始长度: {len(content)} 字符\n\n---\n{input_content}'
                    }
                ],
                'temperature': 0.3,
                'max_tokens': 3000,
            },
            timeout=60
        )

        if api_resp.status_code == 200:
            data = api_resp.json()
            summary = data['choices'][0]['message']['content']
            return f'URL: {url}\n原始内容长度: {len(content)} 字符\n\n[Subagent 网页摘要]\n\n{summary}'
        else:
            return f'URL: {url}\n内容长度: {len(content)} 字符 (已截断)\n\n---\n{content[:8000]}\n\n[... 摘要生成失败: HTTP {api_resp.status_code} ...]'

    except Exception as e:
        return f'URL: {url}\n内容长度: {len(content)} 字符 (已截断)\n\n---\n{content[:8000]}\n\n[... 摘要生成异常: {str(e)} ...]'


def _web_search(args, lib_dir, bm, gid, **extra):
    query = args.get('query', '')
    if not query:
        return '搜索查询不能为空', None

    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or os.environ.get('ALL_PROXY')

    result = _web_search_bing(query, proxy)
    if result:
        return result, None

    result = _web_search_ddg(query, proxy)
    if result:
        return result, None

    return f'搜索失败: 无法连接到搜索引擎。如需使用代理，请设置环境变量 HTTPS_PROXY', None


def _web_search_bing(query, proxy=None):
    """通过 Bing 搜索（国内可直接访问）"""
    import re
    try:
        import requests as req
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        proxies = {'https': proxy, 'http': proxy} if proxy else None
        url = f'https://cn.bing.com/search?q={req.utils.quote(query)}&count=5'
        resp = req.get(url, headers=headers, proxies=proxies, timeout=15)
        if resp.status_code != 200:
            return None

        html = resp.text
        results = []
        blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)
        for block in blocks[:5]:
            title_m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not title_m:
                continue
            href = title_m.group(1)
            title = re.sub(r'<[^>]+>', '', title_m.group(2)).strip()
            snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
            snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ''
            if title:
                results.append({'title': title, 'body': snippet, 'href': href})

        if not results:
            return None

        output = f'搜索 "{query}" 的结果:\n\n'
        for i, r in enumerate(results, 1):
            output += f'{i}. **{r["title"]}**\n'
            output += f'   {r["body"]}\n'
            output += f'   链接: {r["href"]}\n\n'
        return output
    except Exception:
        return None


def _web_search_ddg(query, proxy=None):
    """通过 DuckDuckGo 搜索（需要代理）"""
    try:
        from duckduckgo_search import DDGS
        kwargs = {}
        if proxy:
            kwargs['proxy'] = proxy
        with DDGS(**kwargs) as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return None

        output = f'搜索 "{query}" 的结果:\n\n'
        for i, r in enumerate(results, 1):
            output += f'{i}. **{r.get("title", "")}**\n'
            output += f'   {r.get("body", "")}\n'
            output += f'   链接: {r.get("href", "")}\n\n'
        return output
    except Exception:
        return None
