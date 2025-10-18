"""Flask应用初始化"""
from flask import Flask
from app.config import Config

def create_app():
    """创建并配置Flask应用
    
    Returns:
        Flask: 配置好的Flask应用实例
    """
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    
    # 加载配置
    app.config.from_object(Config)
    
    # 初始化配置
    Config.init_app(app)
    
    # 注册蓝图
    from app.routes import main_bp, library_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(library_bp)
    
    return app

