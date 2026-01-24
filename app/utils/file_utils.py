"""文件处理相关工具函数"""
import re
import os

def allowed_file(filename, allowed_extensions):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def safe_filename(filename):
    """
    安全的文件名处理，支持中文字符
    只移除路径分隔符和其他危险字符，保留中文
    """
    # 移除路径分隔符和其他危险字符
    # 保留中文、英文、数字、点、下划线、连字符、空格、括号
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    
    # 移除开头和结尾的空格和点
    filename = filename.strip('. ')
    
    # 如果文件名为空或只有扩展名，使用默认名称
    if not filename or filename.startswith('.'):
        filename = 'unnamed' + filename
    
    # 限制文件名长度（保留扩展名）
    name, ext = os.path.splitext(filename)
    if len(name.encode('utf-8')) > 200:
        # 截断时保证不会截断中文字符的一半
        name = name[:100]
    
    return name + ext

