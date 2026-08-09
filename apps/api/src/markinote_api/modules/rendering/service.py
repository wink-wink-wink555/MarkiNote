"""Markdown rendering with protected extensions and an HTML allowlist."""
from __future__ import annotations

import html
import re
import uuid
from functools import lru_cache
from re import Match

import bleach
import markdown
from bs4 import BeautifulSoup

_FENCE_RE = re.compile(
    r'(?ms)^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})'
    r'(?P<lang>[^\n]*)\n(?P<code>.*?)^(?P=indent)(?P=fence)[ \t]*$',
)
_BLOCK_MATH_PATTERNS = (
    re.compile(r'\$\$([\s\S]+?)\$\$'),
    re.compile(r'\\\[([\s\S]+?)\\\]'),
)
_INLINE_MATH_PATTERNS = (
    re.compile(r'\\\(([^\n]+?)\\\)'),
    re.compile(r'(?<!\\)(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)'),
)
_INLINE_CODE_RE = re.compile(r'(?<!`)`(?!`)([^`\n]+)`(?!`)')

_ALLOWED_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'code', 'dd', 'del', 'details',
    'div', 'dl', 'dt', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img',
    'kbd', 'li', 'mark', 'ol', 'p', 'pre', 's', 'samp', 'small', 'span', 'strong',
    'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'ul',
}
_ALLOWED_ATTRIBUTES = {
    '*': ['class', 'id'],
    'a': ['href', 'title', 'target', 'rel'],
    'abbr': ['title'],
    'code': ['class'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'loading'],
    'ol': ['start'],
    'td': ['align'],
    'th': ['align'],
}
_SAFE_CLASSES = {
    'codehilite', 'codehilitetable', 'highlight', 'math-block', 'math-inline',
    'toc', 'footnote', 'footnote-ref', 'footnote-backref', 'headerlink',
}


def _allow_attribute(tag: str, name: str, value: str) -> bool:
    allowed = set(_ALLOWED_ATTRIBUTES.get('*', ())) | set(_ALLOWED_ATTRIBUTES.get(tag, ()))
    if name not in allowed:
        return False
    if name == 'id':
        return value.startswith('md-') and bool(re.fullmatch(r'md-[A-Za-z0-9_-]{1,120}', value))
    if name == 'class':
        classes = value.split()
        return bool(classes) and all(
            css_class in _SAFE_CLASSES
            or (css_class.startswith('language-') and bool(re.fullmatch(r'language-[A-Za-z0-9_+-]{1,40}', css_class)))
            or (tag == 'span' and bool(re.fullmatch(r'[a-z][a-z0-9]{0,3}', css_class)))
            for css_class in classes
        )
    if name in {'width', 'height'}:
        return value.isdigit() and 1 <= int(value) <= 10000
    if name == 'target':
        return value in {'_blank', '_self'}
    if name == 'loading':
        return value in {'lazy', 'eager'}
    return True


def _replace_wrapped_placeholder(rendered: str, placeholder: str, replacement: str) -> str:
    rendered = rendered.replace(f'<p>{placeholder}</p>', replacement)
    return rendered.replace(placeholder, replacement)


def _prefix_document_ids(rendered: str) -> str:
    """Keep generated heading IDs useful without allowing DOM clobbering."""
    soup = BeautifulSoup(rendered, 'html.parser')
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for element in soup.find_all(id=True):
        old = element.get('id', '')
        if not isinstance(old, str) or not old:
            continue
        base = 'md-' + re.sub(r'[^A-Za-z0-9_-]+', '-', old).strip('-')[:110]
        if not base or base == 'md-':
            element.attrs.pop('id', None)
            continue
        new = base
        suffix = 2
        while new in used:
            new = f'{base}-{suffix}'
            suffix += 1
        used.add(new)
        mapping.setdefault(old, new)
        element['id'] = new
    for anchor in soup.find_all('a', href=True):
        href = anchor.get('href', '')
        if isinstance(href, str) and href.startswith('#') and href[1:] in mapping:
            anchor['href'] = '#' + mapping[href[1:]]
        if anchor.get('target') == '_blank':
            anchor['rel'] = 'noopener noreferrer'
    return str(soup)


@lru_cache(maxsize=16)
def _render_cached(md_content: str) -> str:
    namespace = 'MN' + uuid.uuid4().hex.upper()
    fences: list[tuple[str, str, str]] = []
    inline_codes: list[str] = []
    mermaid_blocks: list[str] = []
    math_blocks: list[tuple[str, str]] = []
    strike_blocks: list[str] = []

    def save_fence(match: Match[str]) -> str:
        lang = match.group('lang').strip()
        code = match.group('code')
        index = len(fences)
        fences.append((lang, code, match.group(0)))
        return f'\n\n{namespace}FENCE{index}END\n\n'

    protected = _FENCE_RE.sub(save_fence, md_content)

    def save_inline_code(match: Match[str]) -> str:
        index = len(inline_codes)
        inline_codes.append(match.group(0))
        return f'{namespace}INLINECODE{index}END'

    protected = _INLINE_CODE_RE.sub(save_inline_code, protected)

    def save_math(kind: str):
        def replace(match: Match[str]) -> str:
            index = len(math_blocks)
            math_blocks.append((kind, match.group(0)))
            return f'{namespace}MATH{index}END'
        return replace

    for pattern in _BLOCK_MATH_PATTERNS:
        protected = pattern.sub(save_math('block'), protected)
    for pattern in _INLINE_MATH_PATTERNS:
        protected = pattern.sub(save_math('inline'), protected)

    def save_strike(match: Match[str]) -> str:
        index = len(strike_blocks)
        strike_blocks.append(match.group(1))
        return f'{namespace}STRIKE{index}END'

    protected = re.sub(r'~~([^~\n]+?)~~', save_strike, protected)

    for index, inline_code in enumerate(inline_codes):
        protected = protected.replace(f'{namespace}INLINECODE{index}END', inline_code)

    for index, (lang, code, original) in enumerate(fences):
        placeholder = f'{namespace}FENCE{index}END'
        if lang.casefold().split()[0:1] == ['mermaid']:
            mermaid_index = len(mermaid_blocks)
            mermaid_blocks.append(code)
            protected = protected.replace(placeholder, f'{namespace}MERMAID{mermaid_index}END')
        else:
            protected = protected.replace(placeholder, original)

    rendered = markdown.markdown(
        protected,
        extensions=['extra', 'codehilite', 'sane_lists', 'nl2br', 'toc'],
        extension_configs={'codehilite': {'css_class': 'highlight', 'linenums': False}},
    )

    for index, text in enumerate(strike_blocks):
        rendered = _replace_wrapped_placeholder(
            rendered,
            f'{namespace}STRIKE{index}END',
            f'<del>{html.escape(text)}</del>',
        )

    for index, code in enumerate(mermaid_blocks):
        rendered = _replace_wrapped_placeholder(
            rendered,
            f'{namespace}MERMAID{index}END',
            f'<pre><code class="language-mermaid">{html.escape(code.strip())}</code></pre>',
        )

    for index, (kind, formula) in enumerate(math_blocks):
        tag = 'div' if kind == 'block' else 'span'
        css_class = 'math-block' if kind == 'block' else 'math-inline'
        rendered = _replace_wrapped_placeholder(
            rendered,
            f'{namespace}MATH{index}END',
            f'<{tag} class="{css_class}">{html.escape(formula)}</{tag}>',
        )

    rendered = _prefix_document_ids(rendered)
    return bleach.clean(
        rendered,
        tags=_ALLOWED_TAGS,
        attributes=_allow_attribute,
        protocols={'http', 'https', 'mailto'},
        strip=True,
        strip_comments=True,
    )


def process_markdown(md_content):
    if not isinstance(md_content, str):
        raise TypeError('Markdown 内容必须为字符串')
    # Storage preserves authored line endings. Parsing a normalized copy makes
    # CRLF, CR, and LF documents equivalent while keeping the saved source byte
    # for byte and sharing one cache entry across line-ending variants.
    normalized = md_content.replace('\r\n', '\n').replace('\r', '\n')
    return _render_cached(normalized)
