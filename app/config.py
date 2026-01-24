"""应用配置文件"""
import os

class Config:
    """Flask应用配置"""
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    LIBRARY_FOLDER = 'lib'  # 改为lib文件夹
    ALLOWED_EXTENSIONS = {'md', 'markdown', 'txt'}
    
    @staticmethod
    def init_app(app):
        """初始化应用配置"""
        # 确保Library文件夹存在
        os.makedirs(app.config['LIBRARY_FOLDER'], exist_ok=True)

