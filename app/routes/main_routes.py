"""主要路由：首页和文件上传"""
from flask import Blueprint, render_template, request, jsonify, current_app
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from app.utils import allowed_file, process_markdown

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """主页"""
    return render_template('index.html')

@main_bp.route('/api/preview', methods=['POST'])
def preview_file():
    """预览Markdown文件"""
    data = request.get_json()
    file_path = data.get('path', '')
    
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
        
        # 读取并渲染Markdown
        with open(full_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # 处理Markdown内容
        html_content = process_markdown(md_content)
        
        return jsonify({
            'success': True,
            'html': html_content,
            'raw_markdown': md_content,
            'filename': os.path.basename(file_path)
        })
    except Exception as e:
        return jsonify({'error': f'预览失败: {str(e)}'}), 500

