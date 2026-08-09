"""文件处理相关工具函数"""
from __future__ import annotations

import os
import re
import unicodedata

_WINDOWS_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}

def allowed_file(filename, allowed_extensions):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def safe_filename(filename):
    """Validate one portable filename while preserving Unicode text."""
    if not isinstance(filename, str):
        raise ValueError('文件名必须为字符串')
    filename = unicodedata.normalize('NFC', filename)
    if not filename or filename in {'.', '..'}:
        raise ValueError('文件名不能为空')
    if filename != filename.strip() or filename.endswith('.'):
        raise ValueError('文件名不能以空格或点开头/结尾')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', filename):
        raise ValueError('文件名包含非法字符')
    if len(filename.encode('utf-8')) > 232:
        raise ValueError('文件名过长')

    name, ext = os.path.splitext(filename)
    if not name:
        raise ValueError('文件名不能为空')
    if name.upper() in _WINDOWS_RESERVED:
        raise ValueError('文件名是系统保留名称')
    if len(ext.encode('utf-8')) > 32:
        raise ValueError('文件扩展名过长')
    return name + ext
