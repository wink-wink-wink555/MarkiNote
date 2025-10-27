"""Markdown处理相关工具函数"""
import markdown
import re

def process_markdown(md_content):
    """处理Markdown内容并渲染为HTML
    
    Args:
        md_content: 原始Markdown文本
        
    Returns:
        渲染后的HTML内容
    """
    # 清理行尾的双空格（Markdown中会被转换为<br>）
    # 保留真正需要换行的地方，移除意外的行尾空格
    md_content = re.sub(r'  +\n', '\n', md_content)
    
    # 预处理：保护Mermaid代码块不被codehilite处理
    mermaid_blocks = []
    
    def save_mermaid_block(match):
        idx = len(mermaid_blocks)
        code = match.group(1).strip()
        mermaid_blocks.append(code)
        return f'\n\nMERMAIDBLOCKPLACEHOLDER{idx}ENDPLACEHOLDER\n\n'
    
    # 匹配 ```mermaid ... ``` 代码块
    md_content = re.sub(r'```mermaid\s*\n([\s\S]+?)\n```', save_mermaid_block, md_content)
    
    # 预处理：保护数学公式不被markdown处理
    math_blocks = []
    
    # 保存块级数学公式
    def save_block_math(match):
        idx = len(math_blocks)
        # 清理公式内容：移除引用块标记 "> "
        formula = match.group(0)
        # 移除每行开头的 "> " 或 ">"
        formula = re.sub(r'^>\s?', '', formula, flags=re.MULTILINE)
        math_blocks.append(('block', formula))
        return f'\n\nMATHBLOCKPLACEHOLDER{idx}ENDPLACEHOLDER\n\n'
    
    # 保存行内数学公式
    def save_inline_math(match):
        idx = len(math_blocks)
        # 清理公式内容：移除引用块标记
        formula = match.group(0)
        formula = re.sub(r'^>\s?', '', formula, flags=re.MULTILINE)
        math_blocks.append(('inline', formula))
        return f'MATHINLINEPLACEHOLDER{idx}ENDPLACEHOLDER'
    
    # 替换数学公式为占位符（按顺序处理，避免冲突）
    # 使用更宽松的匹配模式
    
    # 1. 处理 $$...$$ 块级公式
    md_content = re.sub(r'\$\$([\s\S]+?)\$\$', save_block_math, md_content)
    
    # 2. 处理 \[...\] 块级公式（LaTeX标准格式）
    # 注意：在Python中，\[ 需要转义
    # 支持跨行匹配，包括引用块中的公式
    md_content = re.sub(r'\\\[([\s\S]+?)\\\]', save_block_math, md_content)
    
    # 3. 处理 \(...\) 行内公式（LaTeX标准格式）
    md_content = re.sub(r'\\\(([\s\S]+?)\\\)', save_inline_math, md_content)
    
    # 4. 处理 $...$ 行内公式（避免匹配到 $$）
    # 使用更精确的模式，避免贪婪匹配
    md_content = re.sub(r'(?<!\$)\$(?!\$)([^\n\$]+?)\$(?!\$)', save_inline_math, md_content)
    
    # 5. 智能识别：没有分隔符但包含LaTeX命令的行
    # 匹配包含常见LaTeX命令的独立行（不在列表、标题等结构中）
    def smart_math_detect(match):
        line = match.group(0)
        # 检查是否包含常见的LaTeX命令
        latex_commands = [r'\\sum', r'\\frac', r'\\int', r'\\prod', r'\\sqrt', 
                        r'\\alpha', r'\\beta', r'\\gamma', r'\\delta', r'\\theta',
                        r'\\log', r'\\ln', r'\\sin', r'\\cos', r'\\tan',
                        r'\\lim', r'\\infty', r'\\partial', r'\\nabla']
        
        has_latex = any(re.search(cmd, line) for cmd in latex_commands)
        
        if has_latex:
            # 包装为块级公式
            idx = len(math_blocks)
            math_blocks.append(('block', f'\\[{line}\\]'))
            return f'\n\nMATHBLOCKPLACEHOLDER{idx}ENDPLACEHOLDER\n\n'
        return line
    
    # 匹配独立的行（前后有换行，不以#、-、*、>开头）
    md_content = re.sub(r'^(?![#\-\*>\s])(.+(?:\\sum|\\frac|\\int|\\prod|\\sqrt).+)$', 
                       smart_math_detect, md_content, flags=re.MULTILINE)
    
    # 修复列表格式：自动在列表项前添加空行，并将2空格缩进转换为4空格
    # 这样即使原文没有空行，也能正确渲染列表
    lines = md_content.split('\n')
    
    # 第一步：分析所有列表项的缩进，找出缩进单位
    list_indents = []
    for line in lines:
        stripped = line.strip()
        is_list_item = bool(re.match(r'^[\-\*\+]\s+', stripped))
        if is_list_item and line.startswith(' '):
            leading_spaces = len(line) - len(line.lstrip(' '))
            list_indents.append(leading_spaces)
    
    # 判断是否需要翻倍缩进：如果存在非4倍数的缩进，说明使用的是2空格缩进单位
    needs_double = False
    if list_indents:
        # 检查是否有2的倍数但非4的倍数的缩进
        for indent in list_indents:
            if indent % 4 == 2:
                needs_double = True
                break
    
    # 第二步：处理每一行
    fixed_lines = []
    prev_was_list = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 检查当前行是否是列表项
        is_list_item = bool(re.match(r'^[\-\*\+]\s+', stripped))
        
        # 修复缩进：如果检测到需要翻倍，则将所有有缩进的列表项缩进翻倍
        if needs_double and is_list_item and line.startswith(' '):
            leading_spaces = len(line) - len(line.lstrip(' '))
            # 将缩进翻倍：2→4, 4→8, 6→12
            line = ' ' * leading_spaces + line
        
        if is_list_item:
            # 如果前一行不是空行且不是列表项，添加空行
            if i > 0 and fixed_lines and fixed_lines[-1].strip() and not prev_was_list:
                fixed_lines.append('')
            fixed_lines.append(line)
            prev_was_list = True
        else:
            fixed_lines.append(line)
            prev_was_list = False
    
    md_content = '\n'.join(fixed_lines)
    
    # 手动处理删除线（GFM语法）~~text~~ -> <del>text</del>
    # 需要在markdown处理前先保护删除线内容
    strikethrough_blocks = []
    
    def save_strikethrough(match):
        idx = len(strikethrough_blocks)
        strikethrough_blocks.append(match.group(1))
        return f'STRIKETHROUGHPLACEHOLDER{idx}ENDPLACEHOLDER'
    
    # 匹配 ~~内容~~ （不能跨越多行）
    md_content = re.sub(r'~~([^~\n]+?)~~', save_strikethrough, md_content)
    
    # 使用markdown库渲染HTML，支持表格、代码高亮等扩展
    html_content = markdown.markdown(
        md_content,
        extensions=[
            'extra',  # 包含多个扩展：abbr, attr_list, def_list, fenced_code, footnotes, tables
            'codehilite',  # 代码高亮
            'sane_lists',  # 更好的列表处理
            'nl2br',  # 换行符转换
            'toc'  # 目录支持
        ],
        extension_configs={
            'codehilite': {
                'css_class': 'highlight',
                'linenums': False
            }
        }
    )
    
    # 恢复删除线
    for i, text in enumerate(strikethrough_blocks):
        placeholder = f'STRIKETHROUGHPLACEHOLDER{i}ENDPLACEHOLDER'
        html_content = html_content.replace(placeholder, f'<del>{text}</del>')
    
    # 恢复Mermaid代码块
    print(f"[Mermaid] 共提取了 {len(mermaid_blocks)} 个Mermaid代码块")
    for i, code in enumerate(mermaid_blocks):
        placeholder = f'MERMAIDBLOCKPLACEHOLDER{i}ENDPLACEHOLDER'
        # 生成标准的Mermaid代码块HTML，确保类名为language-mermaid
        wrapped_content = f'<pre><code class="language-mermaid">{code}</code></pre>'
        # 尝试多种替换方式，包括更复杂的包装情况
        replacements = [
            f'<p>{placeholder}</p>',
            f'<pre><code>{placeholder}</code></pre>',
            f'<pre><code class="highlight">{placeholder}</code></pre>',
            f'<pre><code class="language-text">{placeholder}</code></pre>',
            placeholder
        ]

        replaced = False
        for replacement in replacements:
            if replacement in html_content:
                html_content = html_content.replace(replacement, wrapped_content)
                print(f"[Mermaid {i}] 替换了 {replacement} 为 {wrapped_content}")
                replaced = True
                break

        if not replaced:
            print(f"[警告] Mermaid {i} 的占位符未找到: {placeholder}")
            # 如果都没找到，尝试更宽泛的搜索
            pattern = rf'<[^>]*>{re.escape(placeholder)}[^<]*</[^>]*>|{re.escape(placeholder)}'
            matches = re.findall(pattern, html_content)
            if matches:
                print(f"[调试] 找到匹配的模式: {matches[:3]}")  # 只显示前3个匹配

    # 恢复数学公式，并包装在适当的HTML标签中
    print(f"[数学公式] 共提取了 {len(math_blocks)} 个数学公式")
    for i, (math_type, math_content) in enumerate(math_blocks):
        if math_type == 'block':
            placeholder = f'MATHBLOCKPLACEHOLDER{i}ENDPLACEHOLDER'
            # 将块级公式包装在div中，方便样式控制
            wrapped_content = f'<div class="math-block">{math_content}</div>'
            # 尝试多种替换方式
            if f'<p>{placeholder}</p>' in html_content:
                html_content = html_content.replace(f'<p>{placeholder}</p>', wrapped_content)
                print(f"[块级公式 {i}] 替换了 <p> 包装的占位符")
            elif placeholder in html_content:
                html_content = html_content.replace(placeholder, wrapped_content)
                print(f"[块级公式 {i}] 替换了普通占位符")
            else:
                print(f"[警告] 块级公式 {i} 的占位符未找到: {placeholder}")
        else:
            placeholder = f'MATHINLINEPLACEHOLDER{i}ENDPLACEHOLDER'
            # 行内公式包装在span中
            wrapped_content = f'<span class="math-inline">{math_content}</span>'
            if placeholder in html_content:
                html_content = html_content.replace(placeholder, wrapped_content)
                print(f"[行内公式 {i}] 成功替换")
            else:
                print(f"[警告] 行内公式 {i} 的占位符未找到: {placeholder}")

    return html_content
