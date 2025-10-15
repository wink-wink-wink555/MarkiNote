# 贡献指南 🎉

首先，感谢你愿意为 MarkiNote 贡献力量！(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧

这份指南会帮助你了解如何为这个项目做出贡献。

---

## 💡 贡献方式

你可以通过以下方式为 MarkiNote 做出贡献：

### 🐛 报告 Bug
发现了问题？请告诉我们！

1. 在 [Issues](https://github.com/wink-wink-wink555/MarkiNote/issues) 页面搜索，确认问题还没有被报告
2. 创建新的 Issue，使用 Bug 模板
3. 详细描述问题：
   - 你的操作步骤
   - 预期的结果
   - 实际的结果
   - 截图（如果有的话）
   - 系统环境（操作系统、Python 版本等）

### ✨ 提出新功能
有好点子？我们很乐意听！(｡♥‿♥｡)

1. 在 Issues 中创建 Feature Request
2. 描述你的想法：
   - 这个功能解决什么问题？
   - 你期望的使用方式是什么？
   - 有没有参考的例子？

### 📝 改进文档
文档永远可以更好！

- 修正拼写错误
- 补充使用说明
- 添加更多示例
- 翻译成其他语言

### 💻 提交代码
准备好贡献代码了？太棒了！ヾ(≧▽≦*)o

---

## 🚀 开发流程

### 1. Fork 和克隆项目

```bash
# Fork 项目到你的 GitHub 账号
# 然后克隆你的 fork

git clone https://github.com/你的用户名/MarkiNote.git
cd MarkiNote
```

### 2. 创建分支

为你的改动创建一个新分支：

```bash
git checkout -b feature/你的功能名称
# 或
git checkout -b fix/bug修复描述
```

**分支命名规范：**
- `feature/功能名称` - 新功能
- `fix/bug描述` - Bug 修复
- `docs/文档说明` - 文档更新
- `refactor/重构说明` - 代码重构
- `style/样式说明` - 样式调整

### 3. 开发环境设置

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python main.py
```

### 4. 进行修改

- 确保代码符合项目的编码风格
- 添加必要的注释
- 如果是新功能，更新相关文档
- 测试你的改动

### 5. 提交更改

```bash
# 添加改动的文件
git add .

# 提交（使用清晰的提交信息）
git commit -m "feat: 添加导出 HTML 功能"
# 或
git commit -m "fix: 修复数学公式渲染问题"
```

**提交信息规范：**
- `feat:` - 新功能
- `fix:` - Bug 修复
- `docs:` - 文档更新
- `style:` - 代码格式调整
- `refactor:` - 代码重构
- `test:` - 测试相关
- `chore:` - 其他杂项

### 6. 推送到你的 Fork

```bash
git push origin feature/你的功能名称
```

### 7. 创建 Pull Request

1. 访问你的 Fork 页面
2. 点击 "New Pull Request"
3. 填写 PR 描述：
   - 改动的内容
   - 解决的问题
   - 相关的 Issue 编号（如果有）
4. 提交 PR

---

## 📋 代码规范

### Python 代码风格

- 遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008/) 规范
- 使用 4 个空格缩进（不使用 Tab）
- 函数和变量使用小写加下划线：`my_function`
- 类名使用大驼峰：`MyClass`
- 常量使用全大写：`MAX_SIZE`

**示例：**
```python
def process_markdown(content):
    """处理 Markdown 内容
    
    Args:
        content: 原始 Markdown 文本
        
    Returns:
        处理后的 HTML 内容
    """
    # 你的代码
    return html_content
```

### JavaScript 代码风格

- 使用 2 个空格缩进
- 使用驼峰命名：`myFunction`
- 使用 `const` 和 `let`，避免 `var`
- 添加适当的注释

**示例：**
```javascript
/**
 * 预览 Markdown 文件
 * @param {string} filePath - 文件路径
 */
function previewFile(filePath) {
  // 你的代码
}
```

### CSS 代码风格

- 使用 2 个空格缩进
- 类名使用小写加连字符：`.my-class`
- 合理组织 CSS 规则

---

## ✅ 检查清单

在提交 PR 之前，请确保：

- [ ] 代码可以正常运行
- [ ] 没有引入新的错误或警告
- [ ] 代码符合项目风格规范
- [ ] 添加了必要的注释
- [ ] 更新了相关文档
- [ ] 提交信息清晰明确
- [ ] PR 描述完整

---

## 🎨 设计原则

在开发新功能时，请遵循以下原则：

1. **简单易用** ✨
   - 功能要直观，用户无需查看文档就能理解
   - 避免过度复杂的设计

2. **性能优先** ⚡
   - 保持应用轻量快速
   - 优化大文件的处理

3. **美观友好** 🎨
   - 保持界面风格一致
   - 注重用户体验

4. **安全可靠** 🔒
   - 验证用户输入
   - 处理错误情况

---

## 🤝 社区准则

为了维护一个友好、包容的社区环境，请：

- ✅ 尊重他人的观点和经验
- ✅ 优雅地接受建设性批评
- ✅ 关注对社区最有利的事情
- ✅ 对其他社区成员表现出同理心

- ❌ 使用性化的语言或图像
- ❌ 进行人身攻击或侮辱
- ❌ 发表不恰当的评论
- ❌ 骚扰他人

---

## 📞 联系方式

有任何问题？随时联系我们！(｡･ω･｡)ﾉ♡

- 📧 GitHub Issues: [提交 Issue](https://github.com/wink-wink-wink555/MarkiNote/issues)
- 💬 Pull Requests: [查看 PRs](https://github.com/wink-wink-wink555/MarkiNote/pulls)

---

## 💖 致谢

感谢所有为 MarkiNote 做出贡献的开发者！

每一个 Issue、每一个 PR、每一条建议，都让这个项目变得更好！(づ｡◕‿‿◕｡)づ

---

<div align="center">

**让我们一起让 MarkiNote 变得更棒！** ✧*｡٩(ˊᗜˋ*)و✧*｡

Happy Coding! ❤️

</div>

