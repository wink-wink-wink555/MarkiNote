// 全局状态
let currentPath = '';
let selectedFile = null;
let contextMenuTarget = null;
let selectedText = ''; // 存储选中的文本
let isEditingSource = false; // 是否正在编辑源代码
let allFiles = []; // 存储所有文件用于搜索
let hasUnsavedChanges = false; // 是否有未保存的改动

// DOM元素
const fileList = document.getElementById('fileList');
const previewContent = document.getElementById('previewContent');
const previewTitle = document.getElementById('previewTitle');
const currentFilePath = document.getElementById('currentFilePath');
const breadcrumb = document.getElementById('breadcrumb');
const uploadBtn = document.getElementById('uploadBtn');
const newBtn = document.getElementById('newBtn');
const searchBtn = document.getElementById('searchBtn');
const themeToggleBtn = document.getElementById('themeToggleBtn');
const fileInput = document.getElementById('fileInput');
const viewSourceBtn = document.getElementById('viewSourceBtn');
const contextMenu = document.getElementById('contextMenu');
const previewContextMenu = document.getElementById('previewContextMenu');
const newSelectModal = document.getElementById('newSelectModal');
const newFileModal = document.getElementById('newFileModal');
const newFolderModal = document.getElementById('newFolderModal');
const uploadModal = document.getElementById('uploadModal');
const sourceModal = document.getElementById('sourceModal');
const moveModal = document.getElementById('moveModal');
const renameModal = document.getElementById('renameModal');
const searchBar = document.getElementById('searchBar');
const searchInput = document.getElementById('searchInput');

// 存储当前文件的原始markdown内容
let currentMarkdownSource = '';

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadLibrary();
    setupEventListeners();
    initializeMermaid();
});

// 设置事件监听
function setupEventListeners() {
    uploadBtn.addEventListener('click', openUploadModal);
    newBtn.addEventListener('click', openNewSelectModal);
    searchBtn.addEventListener('click', toggleSearch);
    themeToggleBtn.addEventListener('click', toggleTheme);
    fileInput.addEventListener('change', handleFileUpload);
    viewSourceBtn.addEventListener('click', openSourceModal);
    searchInput.addEventListener('input', handleSearch);
    
    // 点击其他地方关闭右键菜单
    document.addEventListener('click', () => {
        contextMenu.classList.remove('show');
        previewContextMenu.classList.remove('show');
    });
    
    // 点击其他地方关闭模态框
    window.addEventListener('click', (e) => {
        if (e.target === newSelectModal) {
            closeNewSelectModal();
        }
        if (e.target === newFileModal) {
            closeNewFileModal();
        }
        if (e.target === newFolderModal) {
            closeNewFolderModal();
        }
        if (e.target === uploadModal) {
            closeUploadModal();
        }
        if (e.target === sourceModal) {
            closeSourceModal();
        }
        if (e.target === moveModal) {
            closeMoveModal();
        }
        if (e.target === renameModal) {
            closeRenameModal();
        }
    });
    
    // 回车键创建文件
    document.getElementById('fileNameInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            createFile();
        }
    });
    
    // 回车键创建文件夹
    document.getElementById('folderNameInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            createFolder();
        }
    });
    
    // 回车键重命名
    document.getElementById('renameInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            confirmRename();
        }
    });
    
    // 监听预览内容的右键菜单（选中文字）
    previewContent.addEventListener('contextmenu', showPreviewContextMenu);
    
    // 加载保存的主题设置
    loadTheme();
}


// 打开上传选择模态框
function openUploadModal() {
    uploadModal.classList.add('show');
}

// 关闭上传选择模态框
function closeUploadModal() {
    uploadModal.classList.remove('show');
}

// 选择上传类型
function selectUploadType(type) {
    closeUploadModal();
    
    if (type === 'file') {
        // 上传文件
        fileInput.removeAttribute('webkitdirectory');
        fileInput.removeAttribute('directory');
        fileInput.setAttribute('accept', '.md,.markdown,.txt');
    } else if (type === 'folder') {
        // 上传文件夹
        fileInput.setAttribute('webkitdirectory', '');
        fileInput.setAttribute('directory', '');
        fileInput.removeAttribute('accept');
    }
    
    fileInput.click();
}

// 加载Library
async function loadLibrary(path = '') {
    currentPath = path;
    fileList.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const response = await fetch(`/api/library/list?path=${encodeURIComponent(path)}`);
        const data = await response.json();
        
        if (data.success) {
            displayFiles(data.items);
            updateBreadcrumb(path);
        } else {
            showError('加载文件列表失败');
        }
    } catch (error) {
        showError('加载失败: ' + error.message);
    }
}

// 显示文件列表
function displayFiles(items) {
    if (items.length === 0) {
        fileList.innerHTML = '<div class="empty-state">📁 文件夹为空<br><small style="color: var(--text-secondary); margin-top: 8px;">点击"上传"按钮添加文件</small></div>';
        return;
    }
    
    fileList.innerHTML = items.map(item => {
        const icon = item.type === 'folder' 
            ? '<svg width="24" height="24" viewBox="0 0 16 16" fill="#3b82f6"><path d="M.54 3.87L.5 3a2 2 0 0 1 2-2h3.672a2 2 0 0 1 1.414.586l.828.828A2 2 0 0 0 9.828 3h3.982a2 2 0 0 1 1.992 2.181l-.637 7A2 2 0 0 1 13.174 14H2.826a2 2 0 0 1-1.991-1.819l-.637-7a1.99 1.99 0 0 1 .342-1.31z"/></svg>'
            : '<svg width="24" height="24" viewBox="0 0 16 16" fill="#64748b"><path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5L14 4.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5h-2z"/></svg>';
        
        const size = item.size ? formatFileSize(item.size) : '';
        const modified = item.modified ? formatDate(item.modified) : '';
        
        return `
            <div class="file-item ${item.type}" 
                 data-path="${item.path}" 
                 data-type="${item.type}"
                 onclick="handleFileClick('${item.path}', '${item.type}')"
                 oncontextmenu="showContextMenu(event, '${item.path}', '${item.type}')">
                <div class="file-icon">${icon}</div>
                <div class="file-info">
                    <div class="file-name">${item.name}</div>
                    <div class="file-meta">${size} ${size && modified ? '•' : ''} ${modified}</div>
                </div>
                <button class="file-menu-btn" onclick="showContextMenuFromButton(event, '${item.path}', '${item.type}')" title="更多操作">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M3 9.5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/>
                    </svg>
                </button>
            </div>
        `;
    }).join('');
}

// 更新面包屑导航
function updateBreadcrumb(path) {
    const parts = path ? path.split('/').filter(p => p) : [];
    let html = '<span class="breadcrumb-item" onclick="loadLibrary(\'\')">根目录</span>';
    
    let accumulated = '';
    parts.forEach((part, index) => {
        accumulated += (accumulated ? '/' : '') + part;
        const isLast = index === parts.length - 1;
        html += `<span class="breadcrumb-item ${isLast ? 'active' : ''}" 
                      onclick="loadLibrary('${accumulated}')">${part}</span>`;
    });
    
    breadcrumb.innerHTML = html;
}

// 处理文件/文件夹点击
function handleFileClick(path, type) {
    if (type === 'folder') {
        loadLibrary(path);
    } else {
        selectFile(path);
        previewFile(path);
    }
}

// 选中文件
function selectFile(path) {
    selectedFile = path;
    
    // 更新UI选中状态
    document.querySelectorAll('.file-item').forEach(item => {
        item.classList.remove('selected');
        if (item.dataset.path === path) {
            item.classList.add('selected');
        }
    });
    
    // 启用查看源代码按钮
    viewSourceBtn.disabled = false;
}

// 预览文件
async function previewFile(path) {
    previewContent.innerHTML = '<div class="loading">加载中...</div>';
    previewTitle.textContent = '加载中...';
    currentFilePath.textContent = path;
    
    try {
        const response = await fetch('/api/preview', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ path })
        });
        
        const data = await response.json();
        
        if (data.success) {
            previewTitle.textContent = data.filename;
            currentMarkdownSource = data.raw_markdown || '';
            previewContent.innerHTML = `<div class="markdown-body">${data.html}</div>`;
            
            // 添加代码块复制按钮
            addCodeCopyButtons();
            
            // 添加数学公式复制按钮
            addMathCopyButtons();
            
            // 渲染Mermaid图表
            renderMermaidDiagrams();
            
            // 触发MathJax渲染
            if (window.MathJax) {
                MathJax.typesetPromise([previewContent]).catch(err => console.log('MathJax error:', err));
            }
        } else {
            showError(data.error || '预览失败');
        }
    } catch (error) {
        showError('预览失败: ' + error.message);
    }
}

// 文件上传（支持文件夹）
async function handleFileUpload(event) {
    const files = Array.from(event.target.files);
    if (files.length === 0) return;
    
    // 过滤只保留支持的文件类型
    const allowedExtensions = ['.md', '.markdown', '.txt'];
    const validFiles = files.filter(file => {
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        return allowedExtensions.includes(ext);
    });
    
    if (validFiles.length === 0) {
        showError('没有找到支持的文件（.md, .markdown, .txt）');
        fileInput.value = '';
        return;
    }

    let successCount = 0;
    let failCount = 0;
    
    for (const file of validFiles) {
        // 获取相对路径（如果是文件夹上传）
        let relativePath = file.webkitRelativePath || file.name;
        
        // 如果是文件夹上传，提取文件夹结构
        let targetPath = currentPath;
        if (file.webkitRelativePath) {
            const pathParts = file.webkitRelativePath.split('/');
            if (pathParts.length > 1) {
                // 移除文件名，保留文件夹路径
                const folderPath = pathParts.slice(0, -1).join('/');
                targetPath = currentPath ? `${currentPath}/${folderPath}` : folderPath;
            }
        }
        
    const formData = new FormData();
    formData.append('file', file);
        formData.append('path', targetPath);

    try {
            const response = await fetch('/api/library/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

            if (data.success) {
                successCount++;
        } else {
                failCount++;
                console.error('上传失败:', file.name, data.error);
        }
    } catch (error) {
            failCount++;
            console.error('上传失败:', file.name, error.message);
        }
    }
    
    // 显示上传结果
    if (successCount > 0) {
        showSuccess(`成功上传 ${successCount} 个文件${failCount > 0 ? `，失败 ${failCount} 个` : ''}`);
    } else {
        showError('上传失败');
    }
    
    // 清空文件输入
    fileInput.value = '';
    
    // 刷新文件列表
    setTimeout(() => loadLibrary(currentPath), 500);
}

// 打开新建文件夹模态框
function openNewFolderModal() {
    newFolderModal.classList.add('show');
    document.getElementById('folderNameInput').value = '';
    document.getElementById('folderNameInput').focus();
}

// 关闭新建文件夹模态框
function closeNewFolderModal() {
    newFolderModal.classList.remove('show');
}

// 创建文件夹
async function createFolder() {
    const name = document.getElementById('folderNameInput').value.trim();
    
    if (!name) {
        showError('请输入文件夹名称');
        return;
    }
    
    try {
        const response = await fetch('/api/library/create-folder', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: name,
                path: currentPath
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess('文件夹创建成功');
            closeNewFolderModal();
            loadLibrary(currentPath);
        } else {
            showError(data.error || '创建失败');
        }
    } catch (error) {
        showError('创建失败: ' + error.message);
    }
}

// 显示右键菜单
function showContextMenu(event, path, type) {
    event.preventDefault();
    event.stopPropagation();
    
    contextMenuTarget = { path, type };
    
    // 定位菜单
    contextMenu.style.left = event.pageX + 'px';
    contextMenu.style.top = event.pageY + 'px';
    contextMenu.classList.add('show');
}

// 从"..."按钮显示右键菜单
function showContextMenuFromButton(event, path, type) {
    event.preventDefault();
    event.stopPropagation();
    
    contextMenuTarget = { path, type };
    
    // 获取按钮位置
    const button = event.currentTarget;
    const rect = button.getBoundingClientRect();
    
    // 定位菜单到按钮下方
    contextMenu.style.left = (rect.left - 100) + 'px'; // 向左偏移一些
    contextMenu.style.top = (rect.bottom + 5) + 'px';
    contextMenu.classList.add('show');
}

// 右键菜单操作
async function contextMenuAction(action) {
    if (!contextMenuTarget) return;
    
    const { path, type } = contextMenuTarget;
    
    switch (action) {
        case 'rename':
            // 打开重命名模态框
            openRenameModal(path, type);
            break;
            
        case 'move':
            // 打开移动文件模态框
            openMoveModal(path);
            break;
            
        case 'delete':
            if (confirm(`确定要删除 "${path.split('/').pop()}" 吗？`)) {
                await deleteItem(path);
            }
            break;
    }
    
    contextMenu.classList.remove('show');
}

// 打开移动文件模态框
async function openMoveModal(sourcePath) {
    const itemName = sourcePath.split('/').pop();
    document.getElementById('moveItemName').textContent = itemName;
    
    // 加载文件夹列表
    const folderList = document.getElementById('folderList');
    folderList.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const response = await fetch('/api/library/folders');
        const data = await response.json();
        
        if (data.success) {
            displayFolderList(data.folders, sourcePath);
        } else {
            folderList.innerHTML = '<div class="empty-state">加载文件夹列表失败</div>';
        }
    } catch (error) {
        folderList.innerHTML = '<div class="empty-state">加载失败: ' + error.message + '</div>';
    }
    
    moveModal.classList.add('show');
}

// 显示文件夹列表
function displayFolderList(folders, sourcePath) {
    const folderList = document.getElementById('folderList');
    
    if (folders.length === 0) {
        folderList.innerHTML = '<div class="empty-state">没有可用的文件夹</div>';
        return;
    }
    
    // 获取源文件的父文件夹路径
    const sourceParentPath = sourcePath.includes('/') 
        ? sourcePath.substring(0, sourcePath.lastIndexOf('/')) 
        : '';
    
    // 过滤掉无效的文件夹：
    // 1. 源路径本身（不能移动到自己）
    // 2. 源路径的子文件夹（避免循环移动）
    // 3. 源文件的父文件夹（已经在那里了，移动无意义）
    const validFolders = folders.filter(folder => {
        // 过滤源路径本身
        if (folder.path === sourcePath) return false;
        // 过滤源路径的子文件夹
        if (folder.path.startsWith(sourcePath + '/')) return false;
        // 过滤源文件的父文件夹（它已经在那里了）
        if (folder.path === sourceParentPath) return false;
        return true;
    });
    
    if (validFolders.length === 0) {
        folderList.innerHTML = '<div class="empty-state">没有可移动的目标文件夹</div>';
        return;
    }
    
    folderList.innerHTML = validFolders.map(folder => {
        // 根目录特殊处理
        const isRoot = folder.path === '';
        
        // 计算缩进和层级指示器
        const level = folder.level;
        const indentPixels = (level - (isRoot ? 0 : 1)) * 24; // 每层缩进24px
        
        // 层级指示器（使用竖线和横线）
        let levelIndicator = '';
        if (!isRoot && level > 0) {
            // 为子文件夹添加树形连接线
            levelIndicator = '<span class="folder-tree-line"></span>';
        }
        
        // 图标
        const icon = isRoot
            ? '<svg width="18" height="18" viewBox="0 0 16 16" fill="#f59e0b"><path d="M1 3.5A1.5 1.5 0 0 1 2.5 2h2.764c.958 0 1.76.56 2.311 1.184C7.985 3.648 8.48 4 9 4h4.5A1.5 1.5 0 0 1 15 5.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9z"/></svg>'
            : '<svg width="18" height="18" viewBox="0 0 16 16" fill="#3b82f6"><path d="M1 3.5A1.5 1.5 0 0 1 2.5 2h2.764c.958 0 1.76.56 2.311 1.184C7.985 3.648 8.48 4 9 4h4.5A1.5 1.5 0 0 1 15 5.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9z"/></svg>';
        
        return `
            <div class="folder-item folder-level-${level}" onclick="selectTargetFolder('${folder.path}', '${folder.name}')" style="padding-left: ${indentPixels + 16}px;">
                ${levelIndicator}
                ${icon}
                <span class="folder-name">${folder.name}</span>
            </div>
        `;
    }).join('');
}

// 选择目标文件夹并移动
async function selectTargetFolder(targetPath, targetName) {
    if (!contextMenuTarget) return;
    
    const sourcePath = contextMenuTarget.path;
    
    // 确认移动
    const itemName = sourcePath.split('/').pop();
    if (confirm(`确定要将 "${itemName}" 移动到 "${targetName}" 吗？`)) {
        closeMoveModal();
        await moveItem(sourcePath, targetPath);
    }
}

// 关闭移动文件模态框
function closeMoveModal() {
    moveModal.classList.remove('show');
}

// 移动文件
async function moveItem(source, target) {
    try {
        const response = await fetch('/api/library/move', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                source: source,
                target: target
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess('移动成功');
            loadLibrary(currentPath);
    } else {
            showError(data.error || '移动失败');
        }
    } catch (error) {
        showError('移动失败: ' + error.message);
    }
}

// 删除文件/文件夹
async function deleteItem(path) {
    try {
        const response = await fetch('/api/library/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ path })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess('删除成功');
            
            // 如果删除的是当前选中的文件，清空预览
            if (selectedFile === path) {
                selectedFile = null;
                currentMarkdownSource = '';
                previewContent.innerHTML = `
                    <div class="welcome-message">
                        <h3>文件已删除</h3>
                        <p>请选择其他文件预览</p>
                    </div>
                `;
                previewTitle.textContent = '选择文件以预览';
                currentFilePath.textContent = '';
                viewSourceBtn.disabled = true;
            }
            
            loadLibrary(currentPath);
        } else {
            showError(data.error || '删除失败');
        }
    } catch (error) {
        showError('删除失败: ' + error.message);
    }
}

// ===== 重命名功能 =====

// 打开重命名模态框
function openRenameModal(path, type) {
    const fileName = path.split('/').pop();
    document.getElementById('renameItemOldName').textContent = fileName;
    
    // 如果是文件，只显示文件名（不含扩展名）
    if (type === 'file') {
        const lastDotIndex = fileName.lastIndexOf('.');
        if (lastDotIndex > 0) {
            const nameWithoutExt = fileName.substring(0, lastDotIndex);
            document.getElementById('renameInput').value = nameWithoutExt;
        } else {
            document.getElementById('renameInput').value = fileName;
        }
    } else {
        document.getElementById('renameInput').value = fileName;
    }
    
    document.getElementById('renameError').style.display = 'none';
    
    // 存储当前路径和类型以便后续使用
    contextMenuTarget = { path, type };
    
    renameModal.classList.add('show');
    // 聚焦输入框并选中全部文本
    const input = document.getElementById('renameInput');
    input.focus();
    input.select();
}

// 关闭重命名模态框
function closeRenameModal() {
    renameModal.classList.remove('show');
}

// 确认重命名
async function confirmRename() {
    if (!contextMenuTarget) return;
    
    const newNameInput = document.getElementById('renameInput').value.trim();
    const errorElement = document.getElementById('renameError');
    const { path: oldPath, type } = contextMenuTarget;
    const oldName = oldPath.split('/').pop();
    
    // 验证新名称
    if (!newNameInput) {
        errorElement.textContent = '名称不能为空';
        errorElement.style.display = 'block';
        return;
    }
    
    // 检查是否包含非法字符
    const invalidChars = /[<>:"/\\|?*]/;
    if (invalidChars.test(newNameInput)) {
        errorElement.textContent = '名称包含非法字符: < > : " / \\ | ? *';
        errorElement.style.display = 'block';
        return;
    }
    
    // 构造完整的新名称
    let newName;
    if (type === 'file') {
        // 文件：保持原有扩展名
        const lastDotIndex = oldName.lastIndexOf('.');
        if (lastDotIndex > 0) {
            const extension = oldName.substring(lastDotIndex);
            newName = newNameInput + extension;
        } else {
            newName = newNameInput;
        }
    } else {
        // 文件夹：直接使用新名称
        newName = newNameInput;
    }
    
    // 检查名称是否改变
    if (newName === oldName) {
        errorElement.textContent = '新名称与原名称相同';
        errorElement.style.display = 'block';
        return;
    }
    
    try {
        const response = await fetch('/api/library/rename', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                old_path: oldPath,
                new_name: newName
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess('重命名成功');
            closeRenameModal();
            
            // 如果重命名的是当前选中的文件，更新选中状态
            if (selectedFile === oldPath) {
                selectedFile = data.new_path;
                currentFilePath.textContent = data.new_path;
            }
            
            // 刷新文件列表
            loadLibrary(currentPath);
        } else {
            errorElement.textContent = data.error || '重命名失败';
            errorElement.style.display = 'block';
        }
    } catch (error) {
        errorElement.textContent = '重命名失败: ' + error.message;
        errorElement.style.display = 'block';
    }
}

// ===== 预览内容右键菜单功能 =====

// 显示预览内容右键菜单
function showPreviewContextMenu(event) {
    // 获取选中的文本
    const selection = window.getSelection();
    const text = selection.toString().trim();
    
    // 只有选中了文本才显示菜单
    if (!text) {
        return;
    }
    
    event.preventDefault();
    event.stopPropagation();
    
    selectedText = text;
    
    // 检测选中的文本是否包含换行符
    const hasNewline = text.includes('\n') || text.includes('\r');
    
    // 获取"在源代码中显示"菜单项
    const findInSourceMenuItem = document.getElementById('findInSourceMenuItem');
    
    // 如果包含换行，隐藏该选项；否则显示
    if (findInSourceMenuItem) {
        findInSourceMenuItem.style.display = hasNewline ? 'none' : 'flex';
    }
    
    // 定位菜单
    previewContextMenu.style.left = event.pageX + 'px';
    previewContextMenu.style.top = event.pageY + 'px';
    previewContextMenu.classList.add('show');
    
    // 隐藏Library右键菜单
    contextMenu.classList.remove('show');
}

// 预览右键菜单操作
async function previewContextMenuAction(action) {
    if (!selectedText) return;
    
    switch (action) {
        case 'copy':
            // 复制选中的文本（无提示）
            try {
                await navigator.clipboard.writeText(selectedText);
                // 复制成功后不显示提示
            } catch (err) {
                console.error('复制失败:', err);
                showError('复制失败');
            }
            break;
            
        case 'bing':
            // 用必应搜索
            const searchUrl = `https://cn.bing.com/search?q=${encodeURIComponent(selectedText)}`;
            window.open(searchUrl, '_blank');
            break;
            
        case 'findInSource':
            // 在源代码中找到
            if (!currentMarkdownSource) {
                showError('没有可用的源代码');
                return;
            }
            
            // 打开源代码模态框
            const codeElement = document.querySelector('#sourceContent code');
            codeElement.textContent = currentMarkdownSource;
            sourceModal.classList.add('show');
            
            // 在源代码中高亮并滚动到选中的文本
            setTimeout(() => {
                highlightTextInSource(selectedText);
            }, 100);
            break;
    }
    
    previewContextMenu.classList.remove('show');
}

// 在源代码中高亮文本
function highlightTextInSource(searchText) {
    const codeElement = document.querySelector('#sourceContent code');
    if (!codeElement) return;
    
    const sourceText = codeElement.textContent;
    const index = sourceText.indexOf(searchText);
    
    if (index === -1) {
        showError('在源代码中未找到该文本');
        return;
    }
    
    // 使用HTML来高亮文本
    const beforeText = sourceText.substring(0, index);
    const matchText = sourceText.substring(index, index + searchText.length);
    const afterText = sourceText.substring(index + searchText.length);
    
    codeElement.innerHTML = 
        escapeHtml(beforeText) + 
        '<mark style="background-color: #ffeb3b; padding: 2px 4px; border-radius: 3px;">' + 
        escapeHtml(matchText) + 
        '</mark>' + 
        escapeHtml(afterText);
    
    // 滚动到高亮位置
    const markElement = codeElement.querySelector('mark');
    if (markElement) {
        markElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// HTML转义函数
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== 源代码编辑功能 =====

// 编辑源代码
function editSourceCode() {
    isEditingSource = true;
    hasUnsavedChanges = false; // 重置未保存标志
    const codeElement = document.querySelector('#sourceContent code');
    const editorElement = document.getElementById('sourceEditor');
    
    // 切换显示
    document.getElementById('sourceContent').style.display = 'none';
    editorElement.style.display = 'block';
    editorElement.value = currentMarkdownSource;
    
    // 监听编辑器内容变化
    editorElement.oninput = function() {
        hasUnsavedChanges = (editorElement.value !== currentMarkdownSource);
    };
    
    // 切换按钮
    document.getElementById('sourceViewActions').style.display = 'none';
    document.getElementById('sourceEditActions').style.display = 'flex';
    document.getElementById('sourceModalTitle').textContent = '编辑源代码';
    
    // 隐藏关闭按钮
    document.body.classList.add('editing-source');
    
    // 聚焦编辑器
    editorElement.focus();
}

// 取消编辑源代码
function cancelEditSourceCode() {
    // 如果有未保存的改动，弹窗提醒
    if (hasUnsavedChanges) {
        if (!confirm('您有未保存的改动，确定要退出编辑模式吗？\n改动将不会被保存。')) {
            return; // 用户取消退出
        }
    }
    
    isEditingSource = false;
    hasUnsavedChanges = false;
    
    // 恢复显示
    document.getElementById('sourceContent').style.display = 'block';
    document.getElementById('sourceEditor').style.display = 'none';
    
    // 移除编辑器的事件监听
    document.getElementById('sourceEditor').oninput = null;
    
    // 切换按钮
    document.getElementById('sourceViewActions').style.display = 'flex';
    document.getElementById('sourceEditActions').style.display = 'none';
    document.getElementById('sourceModalTitle').textContent = '源代码';
    
    // 显示关闭按钮
    document.body.classList.remove('editing-source');
}

// 保存源代码
async function saveSourceCode() {
    if (!selectedFile) {
        showError('没有选中的文件');
        return;
    }
    
    const editorElement = document.getElementById('sourceEditor');
    const newContent = editorElement.value;
    
    try {
        const response = await fetch('/api/library/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                path: selectedFile,
                content: newContent
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess('保存成功');
            currentMarkdownSource = newContent;
            hasUnsavedChanges = false; // 重置未保存标志
            
            // 更新代码显示
            const codeElement = document.querySelector('#sourceContent code');
            codeElement.textContent = newContent;
            
            // 退出编辑模式
            isEditingSource = false;
            document.getElementById('sourceContent').style.display = 'block';
            document.getElementById('sourceEditor').style.display = 'none';
            document.getElementById('sourceEditor').oninput = null;
            document.getElementById('sourceViewActions').style.display = 'flex';
            document.getElementById('sourceEditActions').style.display = 'none';
            document.getElementById('sourceModalTitle').textContent = '源代码';
            document.body.classList.remove('editing-source');
            
            // 刷新预览
            previewFile(selectedFile);
        } else {
            showError(data.error || '保存失败');
        }
    } catch (error) {
        showError('保存失败: ' + error.message);
    }
}

// 关闭源代码模态框（确保清理编辑状态）
function closeSourceModal() {
    if (isEditingSource) {
        // 如果正在编辑且有未保存的改动，提醒用户
        if (hasUnsavedChanges) {
            if (!confirm('您有未保存的改动，确定要关闭吗？\n改动将不会被保存。')) {
                return; // 用户取消关闭
            }
        }
        // 强制退出编辑模式（不再检查hasUnsavedChanges，因为已经确认过了）
        isEditingSource = false;
        hasUnsavedChanges = false;
        document.getElementById('sourceContent').style.display = 'block';
        document.getElementById('sourceEditor').style.display = 'none';
        document.getElementById('sourceEditor').oninput = null;
        document.getElementById('sourceViewActions').style.display = 'flex';
        document.getElementById('sourceEditActions').style.display = 'none';
        document.getElementById('sourceModalTitle').textContent = '源代码';
        document.body.classList.remove('editing-source');
    }
    sourceModal.classList.remove('show');
}

// ===== 搜索功能 =====

// 切换搜索栏
function toggleSearch() {
    const isVisible = searchBar.style.display !== 'none';
    if (isVisible) {
        closeSearch();
    } else {
        searchBar.style.display = 'flex';
        searchInput.value = '';
        searchInput.focus();
    }
}

// 关闭搜索
function closeSearch() {
    searchBar.style.display = 'none';
    searchInput.value = '';
    // 清除搜索高亮
    document.querySelectorAll('.file-item').forEach(item => {
        item.classList.remove('search-match');
        item.style.display = '';
    });
    // 移除"无搜索结果"提示
    const existingNoResult = fileList.querySelector('.no-search-result');
    if (existingNoResult) {
        existingNoResult.remove();
    }
}

// 处理搜索
function handleSearch(event) {
    const query = event.target.value.trim().toLowerCase();
    const fileItems = document.querySelectorAll('.file-item');
    
    // 移除之前的"无搜索结果"提示
    const existingNoResult = fileList.querySelector('.no-search-result');
    if (existingNoResult) {
        existingNoResult.remove();
    }
    
    if (!query) {
        // 清空搜索，显示所有文件
        fileItems.forEach(item => {
            item.classList.remove('search-match');
            item.style.display = '';
        });
        return;
    }
    
    // 搜索并高亮匹配项
    let hasMatch = false;
    fileItems.forEach(item => {
        const fileName = item.querySelector('.file-name').textContent.toLowerCase();
        if (fileName.includes(query)) {
            item.classList.add('search-match');
            item.style.display = '';
            hasMatch = true;
        } else {
            item.classList.remove('search-match');
            item.style.display = 'none';
        }
    });
    
    // 如果没有匹配结果，显示"无搜索结果"
    if (!hasMatch) {
        const noResultDiv = document.createElement('div');
        noResultDiv.className = 'no-search-result';
        noResultDiv.innerHTML = `
            <svg width="48" height="48" viewBox="0 0 16 16" fill="currentColor" style="opacity: 0.3; margin-bottom: 16px;">
                <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001c.03.04.062.078.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1.007 1.007 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0z"/>
            </svg>
            <p style="color: var(--text-secondary); font-size: 15px;">无搜索结果</p>
            <p style="color: var(--text-secondary); font-size: 13px; margin-top: 8px;">试试其他关键词</p>
        `;
        fileList.appendChild(noResultDiv);
    }
}

// ===== 主题切换功能 =====

// 切换主题
function toggleTheme() {
    const body = document.body;
    const isDark = body.classList.toggle('dark-mode');
    
    // 切换图标：白天模式显示月亮，夜间模式显示太阳
    document.getElementById('sunIcon').style.display = isDark ? 'block' : 'none';
    document.getElementById('moonIcon').style.display = isDark ? 'none' : 'block';
    
    // 保存主题设置
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
}

// 加载主题
function loadTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-mode');
        document.getElementById('sunIcon').style.display = 'block';
        document.getElementById('moonIcon').style.display = 'none';
    } else {
        // 白天模式：显示月亮图标
        document.getElementById('sunIcon').style.display = 'none';
        document.getElementById('moonIcon').style.display = 'block';
    }
}

// ===== 新建选择功能 =====

// 打开新建选择模态框
function openNewSelectModal() {
    newSelectModal.classList.add('show');
}

// 关闭新建选择模态框
function closeNewSelectModal() {
    newSelectModal.classList.remove('show');
}

// 选择新建类型
function selectNewType(type) {
    closeNewSelectModal();
    
    if (type === 'file') {
        openNewFileModal();
    } else if (type === 'folder') {
        openNewFolderModal();
    }
}

// ===== 新建文件功能 =====

// 打开新建文件模态框
function openNewFileModal() {
    newFileModal.classList.add('show');
    document.getElementById('fileNameInput').value = '';
    document.getElementById('fileExtensionSelect').value = 'md'; // 默认选择.md
    document.getElementById('fileNameInput').focus();
}

// 关闭新建文件模态框
function closeNewFileModal() {
    newFileModal.classList.remove('show');
}

// 创建文件
async function createFile() {
    const nameInput = document.getElementById('fileNameInput').value.trim();
    const extension = document.getElementById('fileExtensionSelect').value;
    
    if (!nameInput) {
        showError('请输入文件名');
        return;
    }
    
    // 检查文件名中是否包含非法字符
    const invalidChars = /[<>:"/\\|?*]/;
    if (invalidChars.test(nameInput)) {
        showError('文件名包含非法字符: < > : " / \\ | ? *');
        return;
    }
    
    // 组合完整文件名（去掉用户可能输入的扩展名，使用选择的扩展名）
    let baseName = nameInput;
    // 如果用户输入了扩展名，去掉它
    const dotIndex = nameInput.lastIndexOf('.');
    if (dotIndex > 0) {
        const inputExt = nameInput.substring(dotIndex + 1).toLowerCase();
        if (['md', 'markdown', 'txt'].includes(inputExt)) {
            baseName = nameInput.substring(0, dotIndex);
        }
    }
    
    const fullName = baseName + '.' + extension;
    
    try {
        const response = await fetch('/api/library/create-file', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: fullName,
                path: currentPath
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess('文件创建成功');
            closeNewFileModal();
            loadLibrary(currentPath);
        } else {
            showError(data.error || '创建失败');
        }
    } catch (error) {
        showError('创建失败: ' + error.message);
    }
}

// 打开新建文件夹模态框（保持原来的函数名）
function openNewFolderModal() {
    newFolderModal.classList.add('show');
    document.getElementById('folderNameInput').value = '';
    document.getElementById('folderNameInput').focus();
}


// 工具函数
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatDate(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前';
    if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前';
    if (diff < 604800000) return Math.floor(diff / 86400000) + ' 天前';
    
    return date.toLocaleDateString('zh-CN');
}

function showSuccess(message) {
    alert('✅ ' + message);
}

function showError(message) {
    alert('❌ ' + message);
    previewContent.innerHTML = `
        <div class="welcome-message">
            <h3>❌ 错误</h3>
            <p>${message}</p>
        </div>
    `;
}

// ===== 查看源代码功能 =====

// 打开源代码模态框
function openSourceModal() {
    if (!currentMarkdownSource) {
        showError('没有可用的源代码');
            return;
        }

    const codeElement = document.querySelector('#sourceContent code');
    codeElement.textContent = currentMarkdownSource;
    sourceModal.classList.add('show');
}

// 复制源代码
async function copySourceCode() {
    try {
        await navigator.clipboard.writeText(currentMarkdownSource);
        showSuccess('源代码已复制到剪贴板');
    } catch (err) {
        console.error('复制失败:', err);
        showError('复制失败');
    }
}

// ===== 新增功能：代码复制、Mermaid、数学公式复制 =====

// 初始化Mermaid
function initializeMermaid() {
    if (window.mermaid) {
        mermaid.initialize({
            startOnLoad: false,
            theme: 'default',
            securityLevel: 'loose',
            fontFamily: 'Arial, sans-serif'
        });
        console.log('✅ Mermaid已初始化');
    } else {
        console.warn('⚠️ Mermaid库尚未加载，等待加载...');
        // 如果Mermaid还没加载，等待一段时间后重试
        setTimeout(initializeMermaid, 500);
    }
}

// 添加代码块复制按钮
function addCodeCopyButtons() {
    const codeBlocks = previewContent.querySelectorAll('pre:not(.mermaid-source)');
    
    codeBlocks.forEach((block, index) => {
        // 检查是否已经有复制按钮
        if (block.querySelector('.code-copy-btn')) return;
        
        const button = document.createElement('button');
        button.className = 'code-copy-btn';
        button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
        button.setAttribute('data-index', index);
        button.title = '复制代码';
        
        button.addEventListener('click', async () => {
            const code = block.querySelector('code');
            const text = code ? code.textContent : block.textContent;
            
            try {
                await navigator.clipboard.writeText(text);
                button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';
                button.classList.add('copied');
                
                setTimeout(() => {
                    button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                    button.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('复制失败:', err);
                button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M11.46.146A.5.5 0 0 0 11.107 0H4.893a.5.5 0 0 0-.353.146L.146 4.54A.5.5 0 0 0 0 4.893v6.214a.5.5 0 0 0 .146.353l4.394 4.394a.5.5 0 0 0 .353.146h6.214a.5.5 0 0 0 .353-.146l4.394-4.394a.5.5 0 0 0 .146-.353V4.893a.5.5 0 0 0-.146-.353L11.46.146zM8 4c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 4.995A.905.905 0 0 1 8 4zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/></svg>';
                setTimeout(() => {
                    button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                }, 2000);
            }
        });
        
        block.style.position = 'relative';
        block.appendChild(button);
    });
}

// 添加数学公式复制按钮
function addMathCopyButtons() {
    const mathBlocks = previewContent.querySelectorAll('.math-block');
    
    mathBlocks.forEach((block, index) => {
        // 检查是否已经有复制按钮
        if (block.querySelector('.math-copy-btn')) return;
        
        const button = document.createElement('button');
        button.className = 'math-copy-btn';
        button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
        button.setAttribute('data-index', index);
        button.title = '复制LaTeX代码';
        
        button.addEventListener('click', async (e) => {
            e.stopPropagation();
            
            // 获取原始LaTeX代码（排除按钮的文本）
            const clone = block.cloneNode(true);
            const btnInClone = clone.querySelector('.math-copy-btn');
            if (btnInClone) {
                btnInClone.remove();
            }
            const latexCode = clone.textContent.trim();
            
            try {
                await navigator.clipboard.writeText(latexCode);
                button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';
                button.classList.add('copied');
                
                setTimeout(() => {
                    button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                    button.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('复制失败:', err);
                button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M11.46.146A.5.5 0 0 0 11.107 0H4.893a.5.5 0 0 0-.353.146L.146 4.54A.5.5 0 0 0 0 4.893v6.214a.5.5 0 0 0 .146.353l4.394 4.394a.5.5 0 0 0 .353.146h6.214a.5.5 0 0 0 .353-.146l4.394-4.394a.5.5 0 0 0 .146-.353V4.893a.5.5 0 0 0-.146-.353L11.46.146zM8 4c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 4.995A.905.905 0 0 1 8 4zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/></svg>';
                setTimeout(() => {
                    button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                }, 2000);
            }
        });
        
        block.appendChild(button);
    });
}

// 渲染Mermaid图表
async function renderMermaidDiagrams() {
    if (!window.mermaid) {
        console.warn('⚠️ Mermaid库未加载，等待加载...');
        // 等待Mermaid加载
        await new Promise(resolve => {
            const checkMermaid = setInterval(() => {
                if (window.mermaid) {
                    clearInterval(checkMermaid);
                    console.log('✅ Mermaid库已加载');
                    resolve();
                }
            }, 100);
            // 超时保护
            setTimeout(() => {
                clearInterval(checkMermaid);
                resolve();
            }, 5000);
        });
        
        if (!window.mermaid) {
            console.error('❌ Mermaid库加载超时');
            return;
        }
    }
    
    // 查找所有Mermaid代码块
    const mermaidBlocks = previewContent.querySelectorAll('pre code.language-mermaid');
    
    if (mermaidBlocks.length === 0) {
        console.log('📝 没有找到Mermaid代码块');
        // 调试：显示所有代码块的class
        const allCodeBlocks = previewContent.querySelectorAll('pre code');
        console.log('📋 所有代码块的class:', 
            Array.from(allCodeBlocks).map(cb => cb.className || '(无class)'));
        return;
    }
    
    console.log(`🎨 找到 ${mermaidBlocks.length} 个Mermaid代码块`);
    
    // 确保Mermaid已初始化
    try {
        mermaid.initialize({
            startOnLoad: false,
            theme: 'default',
            securityLevel: 'loose',
            fontFamily: 'Arial, sans-serif'
        });
    } catch (err) {
        console.error('Mermaid初始化失败:', err);
    }
    
    for (let i = 0; i < mermaidBlocks.length; i++) {
        const codeBlock = mermaidBlocks[i];
        const pre = codeBlock.parentElement;
        const mermaidCode = codeBlock.textContent.trim();
        
        console.log(`🔧 处理Mermaid图表 ${i + 1}:`, mermaidCode.substring(0, 50) + '...');
        
        // 创建容器
        const container = document.createElement('div');
        container.className = 'mermaid-container';
        container.setAttribute('data-index', i);
        
        // 创建Mermaid渲染区域
        const mermaidDiv = document.createElement('div');
        mermaidDiv.className = 'mermaid';
        mermaidDiv.setAttribute('data-processed', 'false');
        mermaidDiv.textContent = mermaidCode;
        
        // 创建操作按钮容器
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'mermaid-actions';
        
        // 复制源代码按钮
        const copyBtn = document.createElement('button');
        copyBtn.className = 'mermaid-btn';
        copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
        copyBtn.title = '复制源代码';
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(mermaidCode);
                copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';
                copyBtn.classList.add('success');
                setTimeout(() => {
                    copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                    copyBtn.classList.remove('success');
                }, 2000);
            } catch (err) {
                console.error('复制失败:', err);
            }
        });
        
        // 导出为JPG按钮
        const exportBtn = document.createElement('button');
        exportBtn.className = 'mermaid-btn';
        exportBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5z"/><path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708l3 3z"/></svg>';
        exportBtn.title = '导出为JPG';
        exportBtn.addEventListener('click', () => exportMermaidAsImage(container, i));
        
        actionsDiv.appendChild(copyBtn);
        actionsDiv.appendChild(exportBtn);
        
        container.appendChild(mermaidDiv);
        container.appendChild(actionsDiv);
        
        // 替换原来的代码块
        pre.parentNode.replaceChild(container, pre);
    }
    
    // 渲染所有Mermaid图表
    try {
        const elements = previewContent.querySelectorAll('.mermaid[data-processed="false"]');
        console.log(`📌 准备渲染 ${elements.length} 个Mermaid图表`);
        
        if (elements.length > 0) {
            // Mermaid 10.x 使用 run() 方法，但需要传递选择器或节点数组
            // 移除 data-processed 属性，让 Mermaid 自己处理
            elements.forEach(el => el.removeAttribute('data-processed'));
            
            // 方法1: 使用 run() 方法（Mermaid 10+）
            try {
                await mermaid.run({
                    nodes: Array.from(elements)
                });
                console.log('✅ Mermaid图表渲染完成（方法1）');
            } catch (runErr) {
                console.warn('⚠️ mermaid.run() 失败，尝试方法2:', runErr);
                
                // 方法2: 手动渲染每个图表（兼容旧版本）
                for (let i = 0; i < elements.length; i++) {
                    const element = elements[i];
                    const graphDefinition = element.textContent;
                    const id = `mermaid-${Date.now()}-${i}`;
                    
                    try {
                        const { svg } = await mermaid.render(id, graphDefinition);
                        element.innerHTML = svg;
                        console.log(`✅ 图表 ${i + 1} 渲染成功`);
                    } catch (renderErr) {
                        console.error(`❌ 图表 ${i + 1} 渲染失败:`, renderErr);
                        element.innerHTML = `<pre style="color: red;">渲染失败: ${renderErr.message}</pre>`;
                    }
                }
                console.log('✅ Mermaid图表渲染完成（方法2）');
            }
        }
    } catch (err) {
        console.error('❌ Mermaid渲染失败:', err);
    }
}

// 导出Mermaid图表为图片
async function exportMermaidAsImage(container, index) {
    if (!window.html2canvas) {
        alert('图片导出功能需要html2canvas库');
        return;
    }

    try {
        // 找到SVG元素
        const svg = container.querySelector('svg');
        if (!svg) {
            alert('未找到图表SVG元素');
            return;
        }
        
        // 临时隐藏操作按钮
        const actions = container.querySelector('.mermaid-actions');
        if (actions) {
            actions.style.display = 'none';
        }
        
        // 使用html2canvas转换为canvas
        const canvas = await html2canvas(container, {
            backgroundColor: '#ffffff',
            scale: 2 // 提高分辨率
        });
        
        // 恢复操作按钮
        if (actions) {
            actions.style.display = '';
        }
        
        // 转换为blob并下载
        canvas.toBlob((blob) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `mermaid-diagram-${index + 1}.jpg`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 'image/jpeg', 0.95);
        
    } catch (err) {
        console.error('导出图片失败:', err);
        alert('导出失败: ' + err.message);
    }
}
