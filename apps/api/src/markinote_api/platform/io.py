"""Atomic persistence and lightweight process-local locking."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


@contextmanager
def resource_lock(key: str | os.PathLike[str]):
    normalized = os.path.normcase(os.path.abspath(os.fspath(key)))
    with _locks_guard:
        lock = _locks.setdefault(normalized, threading.RLock())
    with lock:
        yield


def atomic_write_bytes(path: str | os.PathLike[str], content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = target.stat().st_mode if target.exists() else None
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f'.{target.name}.', suffix='.tmp', delete=False) as stream:
            temp_name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if previous_mode is not None:
            os.chmod(temp_name, previous_mode)
        os.replace(temp_name, target)
        if os.name != 'nt':
            directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.remove(temp_name)


def atomic_write_text(path: str | os.PathLike[str], content: str) -> None:
    if not isinstance(content, str):
        raise TypeError('文件内容必须为字符串')
    atomic_write_bytes(path, content.encode('utf-8'))


def atomic_write_json(path: str | os.PathLike[str], value) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
    atomic_write_bytes(path, payload)


def read_utf8_text(path: str | os.PathLike[str]) -> str:
    with open(path, encoding='utf-8-sig', newline='') as stream:
        return stream.read()


def content_version(content: str | bytes) -> str:
    raw = content if isinstance(content, bytes) else content.encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def file_version(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
