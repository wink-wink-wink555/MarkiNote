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
    
    # 修复列表格式：自动在列表项前添加空行，标准化缩进
    # 避免列表被误识别为代码块（4+空格会被识别为代码块）
    lines = md_content.split('\n')
    
    # 第一步：分析所有列表项的缩进，找出最小缩进（顶级列表的缩进）
    list_indents = []
    for line in lines:
        stripped = line.strip()
        is_list_item = bool(re.match(r'^[\-\*\+]\s+', stripped))
        if is_list_item:
            if line.startswith(' '):
                leading_spaces = len(line) - len(line.lstrip(' '))
                list_indents.append(leading_spaces)
            else:
                list_indents.append(0)  # 无缩进的顶级列表
    
    # 找出最小缩进（顶级列表的缩进级别）
    min_indent = min(list_indents) if list_indents else 0
    
    # 判断缩进单位：如果最小的非零缩进是2，说明使用2空格缩进单位
    indent_unit = 4  # 默认4空格
    if list_indents:
        non_zero_indents = [i for i in list_indents if i > 0]
        if non_zero_indents:
            # 找出最小的非零缩进作为缩进单位
            smallest_non_zero = min(non_zero_indents)
            if smallest_non_zero == 2 or any(i % 4 == 2 for i in list_indents):
                indent_unit = 2
    
    # 第二步：处理每一行，标准化缩进并添加必要的空行
    fixed_lines = []
    prev_was_list = False
    
    # 决定顶级列表的基准缩进：
    # 如果最小缩进>=4，说明这些列表可能是某个父元素（如编号列表）的子项
    # 应该保持4个空格的缩进（Markdown标准的嵌套缩进），而不是减少为2
    # 只有当最小缩进在1-3之间时才保持原样，0就是0
    if min_indent >= 4:
        base_indent = 4  # 保持为4，作为标准嵌套缩进
    elif min_indent > 0:
        base_indent = min_indent  # 1-3之间保持原样
    else:
        base_indent = 0  # 无缩进
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 检查当前行是否是列表项
        is_list_item = bool(re.match(r'^[\-\*\+]\s+', stripped))
        
        if is_list_item:
            # 获取当前行的缩进
            if line.startswith(' '):
                leading_spaces = len(line) - len(line.lstrip(' '))
            else:
                leading_spaces = 0
            
            # 标准化缩进：
            # 1. 计算相对于最小缩进的层级
            relative_indent = leading_spaces - min_indent
            
            # 2. 如果使用2空格缩进单位，转换为4空格单位
            if indent_unit == 2 and relative_indent > 0:
                # 将2空格单位转换为4空格单位：2→4, 4→8, 6→12
                level = relative_indent // 2
                normalized_relative_indent = level * 4
            else:
                normalized_relative_indent = relative_indent
            
            # 3. 加上基准缩进（顶级列表的缩进）
            final_indent = base_indent + normalized_relative_indent
            
            # 构建标准化的行
            line = ' ' * final_indent + stripped
            
            # 如果前一行不是空行且不是列表项，添加空行
            if i > 0 and fixed_lines and fixed_lines[-1].strip() and not prev_was_list:
                fixed_lines.append('')
            fixed_lines.append(line)
            prev_was_list = True
        else:
            fixed_lines.append(line)
            prev_was_list = False
    
    md_content = '\n'.join(fixed_lines)
    
    # 调试输出：显示处理后的列表内容
    if list_indents:
        print(f"[列表处理] 检测到 {len(list_indents)} 个列表项")
        print(f"[列表处理] 最小缩进: {min_indent}, 基准缩进: {base_indent}, 缩进单位: {indent_unit}")
        # 显示处理后的前5个列表行
        list_lines = [line for line in fixed_lines if re.match(r'^\s*[\-\*\+]\s+', line)]
        for i, line in enumerate(list_lines[:5]):
            print(f"[列表 {i+1}] 缩进{len(line) - len(line.lstrip())}空格: {repr(line[:50])}")
    
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
        # 清理代码：移除首尾空白，但保留内部换行
        code_cleaned = code.strip()
        # 对特殊字符进行HTML转义
        import html
        code_escaped = html.escape(code_cleaned)
        # 生成标准的Mermaid代码块HTML，确保类名为language-mermaid
        wrapped_content = f'<pre><code class="language-mermaid">{code_escaped}</code></pre>'
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
                print(f"[Mermaid {i}] 替换了 {replacement}")
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