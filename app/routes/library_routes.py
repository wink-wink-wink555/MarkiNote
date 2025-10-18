"""Library路由：文件和文件夹管理"""
from flask import Blueprint, jsonify, current_app, request
from datetime import datetime
import os
import shutil
from app.utils import allowed_file, safe_filename

library_bp = Blueprint('library', __name__)

def get_library_structure(base_path, current_path=''):
    """获取Library目录结构
    
    Args:
        base_path: Library根目录
        current_path: 当前相对路径
        
    Returns:
        包含文件和文件夹信息的字典
    """
    full_path = os.path.join(base_path, current_path) if current_path else base_path
    items = []
    
    try:
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            rel_path = os.path.join(current_path, item) if current_path else item
            
            if os.path.isdir(item_path):
                items.append({
                    'name': item,
                    'type': 'folder',
                    'path': rel_path.replace('\\', '/'),
                    'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).isoformat()
                })
            else:
                # 只显示允许的文件类型
                if allowed_file(item, current_app.config['ALLOWED_EXTENSIONS']):
                    items.append({
                        'name': item,
                        'type': 'file',
                        'path': rel_path.replace('\\', '/'),
                        'size': os.path.getsize(item_path),
                        'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).isoformat()
                    })
    except Exception as e:
        return {'error': str(e)}
    
    # 排序：文件夹在前，然后按名称排序
    items.sort(key=lambda x: (x['type'] != 'folder', x['name'].lower()))
    return items

@library_bp.route('/api/library/list', methods=['GET'])
def list_library():
    """获取Library文件列表"""
    current_path = request.args.get('path', '')
    base_path = current_app.config['LIBRARY_FOLDER']
    
    items = get_library_structure(base_path, current_path)
    
    return jsonify({
        'success': True,
        'items': items,
        'current_path': current_path
    })

@library_bp.route('/api/library/upload', methods=['POST'])
def upload_to_library():
    """上传文件到Library"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件被上传'}), 400
    
    file = request.files['file']
    target_path = request.form.get('path', '')
    
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
    
    if file and allowed_file(file.filename, current_app.config['ALLOWED_EXTENSIONS']):
        filename = safe_filename(file.filename)
        
        # 构建保存路径
        base_path = current_app.config['LIBRARY_FOLDER']
        save_dir = os.path.join(base_path, target_path) if target_path else base_path
        
        # 确保目录存在
        os.makedirs(save_dir, exist_ok=True)
        
        # 如果文件已存在，添加时间戳
        filepath = os.path.join(save_dir, filename)
        if os.path.exists(filepath):
            name, ext = os.path.splitext(filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{name}_{timestamp}{ext}"
            filepath = os.path.join(save_dir, filename)
        
        file.save(filepath)
        
        return jsonify({
            'success': True,
            'message': '文件上传成功',
            'filename': filename,
            'path': os.path.join(target_path, filename).replace('\\', '/') if target_path else filename
        })
    
    return jsonify({'error': '不支持的文件格式'}), 400

@library_bp.route('/api/library/create-folder', methods=['POST'])
def create_folder():
    """创建新文件夹"""
    data = request.get_json()
    folder_name = data.get('name', '').strip()
    parent_path = data.get('path', '')
    
    if not folder_name:
        return jsonify({'error': '文件夹名称不能为空'}), 400
    
    # 安全处理文件夹名称
    folder_name = safe_filename(folder_name)
    
    base_path = current_app.config['LIBRARY_FOLDER']
    folder_path = os.path.join(base_path, parent_path, folder_name) if parent_path else os.path.join(base_path, folder_name)
    
    try:
        if os.path.exists(folder_path):
            return jsonify({'error': '文件夹已存在'}), 400
        
        os.makedirs(folder_path, exist_ok=True)
        
        return jsonify({
            'success': True,
            'message': '文件夹创建成功',
            'folder_name': folder_name
        })
    except Exception as e:
        return jsonify({'error': f'创建文件夹失败: {str(e)}'}), 500

@library_bp.route('/api/library/delete', methods=['POST'])
def delete_item():
    """删除文件或文件夹"""
    data = request.get_json()
    item_path = data.get('path', '')
    
    if not item_path:
        return jsonify({'error': '路径不能为空'}), 400
    
    base_path = current_app.config['LIBRARY_FOLDER']
    full_path = os.path.join(base_path, item_path)
    
    # 安全检查：确保路径在Library目录内
    if not os.path.abspath(full_path).startswith(os.path.abspath(base_path)):
        return jsonify({'error': '非法路径'}), 403
    
    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
            return jsonify({'success': True, 'message': '文件删除成功'})
        elif os.path.isdir(full_path):
            shutil.rmtree(full_path)
            return jsonify({'success': True, 'message': '文件夹删除成功'})
        else:
            return jsonify({'error': '文件或文件夹不存在'}), 404
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@library_bp.route('/api/library/move', methods=['POST'])
def move_item():
    """移动文件到文件夹"""
    data = request.get_json()
    source_path = data.get('source', '')
    target_path = data.get('target', '')
    
    if not source_path:
        return jsonify({'error': '源路径不能为空'}), 400
    
    base_path = current_app.config['LIBRARY_FOLDER']
    source_full = os.path.join(base_path, source_path)
    target_full = os.path.join(base_path, target_path) if target_path else base_path
    
    # 安全检查
    if not os.path.abspath(source_full).startswith(os.path.abspath(base_path)):
        return jsonify({'error': '非法源路径'}), 403
    if not os.path.abspath(target_full).startswith(os.path.abspath(base_path)):
        return jsonify({'error': '非法目标路径'}), 403
    
    try:
        if not os.path.exists(source_full):
            return jsonify({'error': '源文件不存在'}), 404
        
        # 确保目标是文件夹
        if os.path.isfile(target_full):
            return jsonify({'error': '目标必须是文件夹'}), 400
        
        os.makedirs(target_full, exist_ok=True)
        
        # 移动文件
        filename = os.path.basename(source_full)
        new_path = os.path.join(target_full, filename)
        
        # 如果目标位置已存在同名文件，添加时间戳
        if os.path.exists(new_path):
            name, ext = os.path.splitext(filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{name}_{timestamp}{ext}"
            new_path = os.path.join(target_full, filename)
        
        shutil.move(source_full, new_path)
        
        return jsonify({
            'success': True,
            'message': '文件移动成功',
            'new_path': os.path.relpath(new_path, base_path).replace('\\', '/')
        })
    except Exception as e:
        return jsonify({'error': f'移动失败: {str(e)}'}), 500

@library_bp.route('/api/library/read', methods=['GET'])
def read_file():
    """读取文件内容用于预览"""
    file_path = request.args.get('path', '')
    
    if not file_path:
        return jsonify({'error': '文件路径不能为空'}), 400
    
    base_path = current_app.config['LIBRARY_FOLDER']
    full_path = os.path.join(base_path, file_path)
    
    # 安全检查
    if not os.path.abspath(full_path).startswith(os.path.abspath(base_path)):
        return jsonify({'error': '非法路径'}), 403
    
    try:
        if not os.path.exists(full_path):
            return jsonify({'error': '文件不存在'}), 404
        
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            'success': True,
            'content': content,
            'filename': os.path.basename(file_path)
        })
    except Exception as e:
        return jsonify({'error': f'读取文件失败: {str(e)}'}), 500

@library_bp.route('/api/library/folders', methods=['GET'])
def get_all_folders():
    """获取所有文件夹列表（用于移动文件时选择目标文件夹）"""
    base_path = current_app.config['LIBRARY_FOLDER']
    
    def get_folders_recursive(path, prefix=''):
        """递归获取所有文件夹"""
        folders = []
        
        # 添加根目录选项
        if prefix == '':
            folders.append({
                'path': '',
                'name': '📁 根目录',
                'level': 0
            })
        
        try:
            items = sorted(os.listdir(path))
            for item in items:
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    rel_path = os.path.join(prefix, item) if prefix else item
                    level = len(rel_path.split(os.sep))
                    
                    folders.append({
                        'path': rel_path.replace('\\', '/'),
                        'name': item,
                        'level': level
                    })
                    
                    # 递归获取子文件夹
                    sub_folders = get_folders_recursive(item_path, rel_path)
                    folders.extend(sub_folders)
        except Exception as e:
            print(f"Error reading directory {path}: {e}")
        
        return folders
    
    try:
        folders = get_folders_recursive(base_path)
        return jsonify({
            'success': True,
            'folders': folders
        })
    except Exception as e:
        return jsonify({'error': f'获取文件夹列表失败: {str(e)}'}), 500

@library_bp.route('/api/library/rename', methods=['POST'])
def rename_item():
    """重命名文件或文件夹"""
    data = request.get_json()
    old_path = data.get('old_path', '')
    new_name = data.get('new_name', '').strip()
    
    if not old_path:
        return jsonify({'error': '原路径不能为空'}), 400
    
    if not new_name:
        return jsonify({'error': '新名称不能为空'}), 400
    
    # 安全处理新名称
    new_name = safe_filename(new_name)
    
    base_path = current_app.config['LIBRARY_FOLDER']
    old_full_path = os.path.join(base_path, old_path)
    
    # 安全检查：确保原路径在Library目录内
    if not os.path.abspath(old_full_path).startswith(os.path.abspath(base_path)):
        return jsonify({'error': '非法路径'}), 403
    
    try:
        # 检查原文件/文件夹是否存在
        if not os.path.exists(old_full_path):
            return jsonify({'error': '文件或文件夹不存在'}), 404
        
        # 构造新路径
        parent_dir = os.path.dirname(old_full_path)
        new_full_path = os.path.join(parent_dir, new_name)
        
        # 检查新路径是否已存在
        if os.path.exists(new_full_path):
            return jsonify({'error': f'名称"{new_name}"已被使用'}), 400
        
        # 执行重命名
        os.rename(old_full_path, new_full_path)
        
        # 计算新的相对路径
        new_rel_path = os.path.relpath(new_full_path, base_path).replace('\\', '/')
        
        return jsonify({
            'success': True,
            'message': '重命名成功',
            'new_path': new_rel_path,
            'new_name': new_name
        })
    except PermissionError:
        return jsonify({'error': '权限不足，无法重命名'}), 403
    except OSError as e:
        return jsonify({'error': f'重命名失败: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'重命名失败: {str(e)}'}), 500

@library_bp.route('/api/library/save', methods=['POST'])
def save_file():
    """保存文件内容"""
    data = request.get_json()
    file_path = data.get('path', '')
    content = data.get('content', '')
    
    if not file_path:
        return jsonify({'error': '文件路径不能为空'}), 400
    
    base_path = current_app.config['LIBRARY_FOLDER']
    full_path = os.path.join(base_path, file_path)
    
    # 安全检查：确保路径在Library目录内
    if not os.path.abspath(full_path).startswith(os.path.abspath(base_path)):
        return jsonify({'error': '非法路径'}), 403
    
    try:
        # 检查文件是否存在
        if not os.path.exists(full_path):
            return jsonify({'error': '文件不存在'}), 404
        
        # 检查是否是文件
        if not os.path.isfile(full_path):
            return jsonify({'error': '路径不是文件'}), 400
        
        # 保存文件
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({
            'success': True,
            'message': '文件保存成功'
        })
    except PermissionError:
        return jsonify({'error': '权限不足，无法保存文件'}), 403
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

@library_bp.route('/api/library/create-file', methods=['POST'])
def create_file():
    """创建新文件"""
    data = request.get_json()
    file_name = data.get('name', '').strip()
    parent_path = data.get('path', '')
    
    if not file_name:
        return jsonify({'error': '文件名不能为空'}), 400
    
    # 检查文件扩展名
    ext = file_name.lower().split('.')[-1]
    if ext not in ['md', 'markdown', 'txt']:
        return jsonify({'error': '不支持的文件格式'}), 400
    
    # 安全处理文件名
    file_name = safe_filename(file_name)
    
    base_path = current_app.config['LIBRARY_FOLDER']
    file_path = os.path.join(base_path, parent_path, file_name) if parent_path else os.path.join(base_path, file_name)
    
    try:
        # 检查文件是否已存在
        if os.path.exists(file_path):
            return jsonify({'error': '文件已存在'}), 400
        
        # 创建文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('# ' + file_name.rsplit('.', 1)[0] + '\n\n')
        
        return jsonify({
            'success': True,
            'message': '文件创建成功',
            'file_name': file_name
        })
    except Exception as e:
        return jsonify({'error': f'创建文件失败: {str(e)}'}), 500

