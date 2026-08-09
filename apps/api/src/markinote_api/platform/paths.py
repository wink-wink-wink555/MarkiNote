"""Canonical path handling for MarkiNote-owned files."""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath


class PathValidationError(ValueError):
    """Raised when a user-controlled path leaves its configured root."""


def normalize_relative_path(value: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise PathValidationError('路径必须为字符串')
    if '\x00' in value:
        raise PathValidationError('路径包含非法字符')

    raw = value.replace('\\', '/')
    if len(raw) > 1024:
        raise PathValidationError('路径过长')
    if not raw:
        if allow_empty:
            return ''
        raise PathValidationError('路径不能为空')
    if raw.startswith('/') or PureWindowsPath(raw).drive:
        raise PathValidationError('只允许文档库内的相对路径')

    parts = []
    for part in PurePosixPath(raw).parts:
        if part in ('', '.'):
            continue
        if part == '..':
            raise PathValidationError('路径越界，禁止访问文档库外文件')
        parts.append(part)

    normalized = '/'.join(parts)
    if not normalized and not allow_empty:
        raise PathValidationError('路径不能为空')
    return normalized


def resolve_under_root(
    root: str | os.PathLike[str],
    relative_path: str,
    *,
    allow_root: bool = True,
    must_exist: bool = False,
) -> tuple[Path, str]:
    """Resolve a relative path and reject traversal and symlink escapes."""
    normalized = normalize_relative_path(relative_path, allow_empty=allow_root)
    root_path = Path(root).resolve()
    lexical_candidate = root_path.joinpath(*normalized.split('/')) if normalized else root_path
    cursor = root_path
    for part in normalized.split('/') if normalized else ():
        cursor = cursor / part
        if cursor.is_symlink():
            raise PathValidationError('禁止访问符号链接路径')
    candidate = lexical_candidate.resolve(strict=False)

    try:
        contained = os.path.commonpath((str(root_path), str(candidate))) == str(root_path)
    except ValueError:
        contained = False
    if not contained or (candidate == root_path and not allow_root):
        raise PathValidationError('路径越界，禁止访问文档库外文件')
    if must_exist and not candidate.exists():
        raise FileNotFoundError(normalized)
    return candidate, normalized


def relative_to_root(root: str | os.PathLike[str], path: str | os.PathLike[str]) -> str:
    root_path = Path(root).resolve()
    resolved = Path(path).resolve(strict=False)
    try:
        return resolved.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise PathValidationError('路径越界，禁止访问文档库外文件') from exc


_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


def validate_storage_id(value: str, label: str = 'ID') -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise PathValidationError(f'{label} 格式非法')
    return value
