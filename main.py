"""MarkiNote - Markdown 文档管理系统启动文件"""
from app import create_app

# 创建Flask应用实例
app = create_app()

if __name__ == '__main__':
    print("MarkiNote 启动中...")
    print("访问 http://localhost:5000 使用应用")
    print("支持的功能：Markdown 预览、文件管理、数学公式、代码高亮")
    app.run(debug=True, host='0.0.0.0', port=5000)

