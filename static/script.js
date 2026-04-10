// 全局状态
let currentPath = '';
let selectedFile = null;
let contextMenuTarget = null;
let selectedText = ''; // 存储选中的文本
let isEditingSource = false; // 是否正在编辑源代码
let allFiles = []; // 存储所有文件用于搜索
let hasUnsavedChanges = false; // 是否有未保存的改动
let _lastDirItemsHash = ''; // 目录内容指纹，用于静默刷新去重

// DOM元素
const fileList = document.getElementById('fileList');
const previewContent = document.getElementById('previewContent');
const previewTitle = document.getElementById('previewTitle');
const currentFilePath = document.getElementById('currentFilePath');
const breadcrumb = document.getElementById('breadcrumb');
const uploadBtn = document.getElementById('uploadBtn');
const newBtn = document.getElementById('newBtn');
const searchBtn = document.getElementById('searchBtn');
const settingsBtn = document.getElementById('settingsBtn');
const settingsModal = document.getElementById('settingsModal');
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

// ===== 通用复制函数（带兼容性处理） =====
async function copyToClipboard(text) {
    // 方法1: 尝试使用现代 Clipboard API
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            console.warn('Clipboard API 失败，尝试备用方法:', err);
        }
    }
    
    // 方法2: 使用传统的 execCommand 方法（兼容更多浏览器）
    try {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        textArea.style.top = '-9999px';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        
        if (successful) {
            return true;
        } else {
            throw new Error('execCommand 复制失败');
        }
    } catch (err) {
        console.error('所有复制方法都失败了:', err);
        return false;
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadLibrary();
    setupEventListeners();
    initializeMermaid();
    loadSidebarState();
    startFileWatcher();
});

// 设置事件监听
function setupEventListeners() {
    uploadBtn.addEventListener('click', openUploadModal);
    newBtn.addEventListener('click', openNewSelectModal);
    searchBtn.addEventListener('click', toggleSearch);
    settingsBtn.addEventListener('click', openSettingsModal);
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
        if (e.target === settingsModal) {
            closeSettingsModal();
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

// 加载Library（优化版，添加性能监控）
// silent=true 时不显示"加载中"提示，用于后台定时刷新
async function loadLibrary(path = '', silent = false) {
    currentPath = path;
    if (!silent) {
        fileList.innerHTML = '<div class="loading">' + t('loading') + '</div>';
    }
    
    const startTime = performance.now();
    
    try {
        const fetchStart = performance.now();
        const response = await fetch(`/api/library/list?path=${encodeURIComponent(path)}`);
        const fetchTime = performance.now() - fetchStart;
        
        const parseStart = performance.now();
        const data = await response.json();
        const parseTime = performance.now() - parseStart;
        
        if (data.success) {
            // 静默模式下，如果目录内容没变则跳过 DOM 重建
            const itemsHash = JSON.stringify(data.items.map(i => i.path + '|' + i.name + '|' + (i.size || '')));
            if (silent && itemsHash === _lastDirItemsHash) {
                return;
            }
            _lastDirItemsHash = itemsHash;

            const renderStart = performance.now();
            displayFiles(data.items);
            const renderTime = performance.now() - renderStart;
            
            updateBreadcrumb(path);
            
            const totalTime = performance.now() - startTime;
            if (!silent) {
                console.log(`📊 加载性能: 总计${totalTime.toFixed(0)}ms | 网络${fetchTime.toFixed(0)}ms | 解析${parseTime.toFixed(0)}ms | 渲染${renderTime.toFixed(0)}ms | 文件数${data.items.length}`);
            }
        } else if (!silent) {
            showError(t('load_list_fail'));
        }
    } catch (error) {
        if (!silent) {
            showError(t('load_fail') + error.message);
            console.error('❌ 加载错误:', error);
        }
    }
}

// 显示文件列表（优化版，使用DocumentFragment减少重绘）
function displayFiles(items) {
    if (items.length === 0) {
        fileList.innerHTML = '<div class="empty-state">' + t('folder_empty') + '<br><small style="color: var(--text-secondary); margin-top: 8px;">' + t('folder_empty_hint') + '</small></div>';
        return;
    }
    
    // 使用 DocumentFragment 批量添加DOM，减少重绘次数
    const fragment = document.createDocumentFragment();
    
    items.forEach(item => {
        const icon = item.type === 'folder' 
            ? '<svg width="24" height="24" viewBox="0 0 16 16" fill="#3b82f6"><path d="M.54 3.87L.5 3a2 2 0 0 1 2-2h3.672a2 2 0 0 1 1.414.586l.828.828A2 2 0 0 0 9.828 3h3.982a2 2 0 0 1 1.992 2.181l-.637 7A2 2 0 0 1 13.174 14H2.826a2 2 0 0 1-1.991-1.819l-.637-7a1.99 1.99 0 0 1 .342-1.31z"/></svg>'
            : '<svg width="24" height="24" viewBox="0 0 16 16" fill="#64748b"><path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5L14 4.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5h-2z"/></svg>';
        
        const size = item.size ? formatFileSize(item.size) : '';
        const modified = item.modified ? formatDate(item.modified) : '';
        
        const div = document.createElement('div');
        div.className = `file-item ${item.type}`;
        div.dataset.path = item.path;
        div.dataset.type = item.type;
        div.onclick = () => handleFileClick(item.path, item.type);
        div.oncontextmenu = (e) => showContextMenu(e, item.path, item.type);
        
        div.innerHTML = `
            <div class="file-icon">${icon}</div>
            <div class="file-info">
                <div class="file-name">${item.name}</div>
                <div class="file-meta">${size} ${size && modified ? '•' : ''} ${modified}</div>
            </div>
            <button class="file-menu-btn" onclick="showContextMenuFromButton(event, '${item.path}', '${item.type}')" title="${t('more_actions')}">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M3 9.5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/>
                </svg>
            </button>
        `;
        
        // 保持当前选中文件的高亮状态
        if (selectedFile && item.path === selectedFile) {
            div.classList.add('selected');
        }

        fragment.appendChild(div);
    });
    
    // 一次性添加所有元素，只触发一次重绘
    fileList.innerHTML = '';
    fileList.appendChild(fragment);
}

// 更新面包屑导航
function updateBreadcrumb(path) {
    const parts = path ? path.split('/').filter(p => p) : [];
    let html = '<span class="breadcrumb-item" onclick="loadLibrary(\'\')">' + t('root_dir') + '</span>';
    
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

    // 同步 AI 上下文
    if (typeof window.setAIContextFile === 'function') {
        window.setAIContextFile(path);
    }
}

// 预览文件
// silent=true 时不显示"加载中"提示，用于后台定时刷新
async function previewFile(path, silent = false) {
    if (!silent) {
        previewContent.innerHTML = '<div class="loading">' + t('loading') + '</div>';
        previewTitle.textContent = t('loading');
    }
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
            // 静默模式下，如果内容没变则不刷新 DOM，避免打断用户阅读
            if (silent && currentMarkdownSource === (data.raw_markdown || '')) {
                return;
            }

            const scrollTop = previewContent.scrollTop;

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
            renderMathJax();

            // 静默刷新时恢复滚动位置，避免阅读位置跳动
            if (silent) {
                previewContent.scrollTop = scrollTop;
            }
        } else if (!silent) {
            showError(data.error || t('preview_fail'));
        }
    } catch (error) {
        if (!silent) {
            showError(t('preview_fail') + ': ' + error.message);
        }
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
        showError(t('no_supported_files'));
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
        showSuccess(t('upload_success', {count: successCount}) + (failCount > 0 ? t('upload_fail_count', {count: failCount}) : ''));
    } else {
        showError(t('upload_fail'));
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
        showError(t('enter_folder_name'));
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
            showSuccess(t('folder_create_success'));
            closeNewFolderModal();
            loadLibrary(currentPath);
        } else {
            showError(data.error || t('create_fail'));
        }
    } catch (error) {
        showError(t('create_fail') + ': ' + error.message);
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
            if (confirm(t('delete_confirm', {name: path.split('/').pop()}))) {
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
    folderList.innerHTML = '<div class="loading">' + t('loading') + '</div>';
    
    try {
        const response = await fetch('/api/library/folders');
        const data = await response.json();
        
        if (data.success) {
            displayFolderList(data.folders, sourcePath);
        } else {
            folderList.innerHTML = '<div class="empty-state">' + t('load_folder_fail') + '</div>';
        }
    } catch (error) {
        folderList.innerHTML = '<div class="empty-state">' + t('load_fail') + error.message + '</div>';
    }
    
    moveModal.classList.add('show');
}

// 显示文件夹列表
function displayFolderList(folders, sourcePath) {
    const folderList = document.getElementById('folderList');
    
    if (folders.length === 0) {
        folderList.innerHTML = '<div class="empty-state">' + t('no_move_target') + '</div>';
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
        folderList.innerHTML = '<div class="empty-state">' + t('no_move_target') + '</div>';
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
    if (confirm(t('move_confirm', {item: itemName, target: targetName}))) {
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
            showSuccess(t('move_success'));
            loadLibrary(currentPath);
    } else {
            showError(data.error || t('move_fail'));
        }
    } catch (error) {
        showError(t('move_fail') + ': ' + error.message);
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
            showSuccess(t('delete_success'));
            
            // 如果删除的是当前选中的文件，清空预览
            if (selectedFile === path) {
                selectedFile = null;
                currentMarkdownSource = '';
                previewContent.innerHTML = `
                    <div class="welcome-message">
                        <h3>${t('file_deleted')}</h3>
                        <p>${t('select_other_file')}</p>
                    </div>
                `;
                previewTitle.textContent = t('select_file_preview');
                currentFilePath.textContent = '';
                viewSourceBtn.disabled = true;
            }
            
            loadLibrary(currentPath);
        } else {
            showError(data.error || t('delete_fail'));
        }
    } catch (error) {
        showError(t('delete_fail') + ': ' + error.message);
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
        errorElement.textContent = t('name_empty');
        errorElement.style.display = 'block';
        return;
    }
    
    // 检查是否包含非法字符
    const invalidChars = /[<>:"/\\|?*]/;
    if (invalidChars.test(newNameInput)) {
        errorElement.textContent = t('invalid_chars');
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
        errorElement.textContent = t('name_same');
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
            showSuccess(t('rename_success'));
            closeRenameModal();
            
            // 如果重命名的是当前选中的文件，更新选中状态
            if (selectedFile === oldPath) {
                selectedFile = data.new_path;
                currentFilePath.textContent = data.new_path;
            }
            
            // 刷新文件列表
            loadLibrary(currentPath);
        } else {
            errorElement.textContent = data.error || t('rename_fail');
            errorElement.style.display = 'block';
        }
    } catch (error) {
        errorElement.textContent = t('rename_fail') + ': ' + error.message;
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
            const success = await copyToClipboard(selectedText);
            if (!success) {
                showError(t('copy_fail'));
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
                showError(t('no_source'));
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
        showError(t('source_not_found'));
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
    document.getElementById('sourceModalTitle').textContent = t('edit_source');
    
    // 隐藏关闭按钮
    document.body.classList.add('editing-source');
    
    // 聚焦编辑器
    editorElement.focus();
}

// 取消编辑源代码
function cancelEditSourceCode() {
    // 如果有未保存的改动，弹窗提醒
    if (hasUnsavedChanges) {
        if (!confirm(t('unsaved_exit'))) {
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
    document.getElementById('sourceModalTitle').textContent = t('source_code');
    
    // 显示关闭按钮
    document.body.classList.remove('editing-source');
}

// 保存源代码
async function saveSourceCode() {
    if (!selectedFile) {
        showError(t('no_source'));
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
            showSuccess(t('save_success'));
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
            document.getElementById('sourceModalTitle').textContent = t('source_code');
            document.body.classList.remove('editing-source');
            
            // 刷新预览
            previewFile(selectedFile);
        } else {
            showError(data.error || t('save_fail'));
        }
    } catch (error) {
        showError(t('save_fail') + ': ' + error.message);
    }
}

// 关闭源代码模态框（确保清理编辑状态）
function closeSourceModal() {
    if (isEditingSource) {
        // 如果正在编辑且有未保存的改动，提醒用户
        if (hasUnsavedChanges) {
            if (!confirm(t('unsaved_close'))) {
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
        document.getElementById('sourceModalTitle').textContent = t('source_code');
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
            <p style="color: var(--text-secondary); font-size: 15px;">${t('no_search_result')}</p>
            <p style="color: var(--text-secondary); font-size: 13px; margin-top: 8px;">${t('no_search_hint')}</p>
        `;
        fileList.appendChild(noResultDiv);
    }
}

// ===== 侧边栏折叠功能 =====

// 切换侧边栏显示/隐藏
function toggleSidebar() {
    const appContainer = document.querySelector('.app-container');
    const collapseIcon = document.getElementById('collapseIcon');
    const expandIcon = document.getElementById('expandIcon');
    
    const isCollapsed = appContainer.classList.toggle('sidebar-collapsed');
    
    // 切换图标
    if (collapseIcon && expandIcon) {
        collapseIcon.style.display = isCollapsed ? 'none' : 'block';
        expandIcon.style.display = isCollapsed ? 'block' : 'none';
    }
    
    // 保存状态到本地存储
    localStorage.setItem('sidebarCollapsed', isCollapsed ? 'true' : 'false');
}

// 加载侧边栏状态
function loadSidebarState() {
    const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    const appContainer = document.querySelector('.app-container');
    const collapseIcon = document.getElementById('collapseIcon');
    const expandIcon = document.getElementById('expandIcon');
    
    if (isCollapsed && appContainer) {
        appContainer.classList.add('sidebar-collapsed');
        if (collapseIcon && expandIcon) {
            collapseIcon.style.display = 'none';
            expandIcon.style.display = 'block';
        }
    }
    
    // 绑定按钮点击事件
    const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
    if (sidebarToggleBtn) {
        sidebarToggleBtn.addEventListener('click', toggleSidebar);
    }
}

// ===== 设置弹窗功能 =====

function openSettingsModal() {
    const langSelect = document.getElementById('settingsLanguageSelect');
    langSelect.value = localStorage.getItem('appLanguage') || 'zh-CN';
    updateThemeUI();
    settingsModal.classList.add('show');
}

function closeSettingsModal() {
    settingsModal.classList.remove('show');
}

function setTheme(theme) {
    document.body.classList.remove('dark-mode', 'blue-mode', 'pink-mode');
    if (theme === 'dark') document.body.classList.add('dark-mode');
    else if (theme === 'blue') document.body.classList.add('blue-mode');
    else if (theme === 'pink') document.body.classList.add('pink-mode');
    localStorage.setItem('theme', theme);
    updateThemeUI();
}

function updateThemeUI() {
    const current = localStorage.getItem('theme') || 'light';
    document.querySelectorAll('.theme-option').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.theme === current);
    });
}

function setLanguage(lang) {
    localStorage.setItem('appLanguage', lang);
    applyLanguage();
}

function loadTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    setTheme(saved);
    applyLanguage();
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
        showError(t('enter_file_name'));
        return;
    }
    
    // 检查文件名中是否包含非法字符
    const invalidChars = /[<>:"/\\|?*]/;
    if (invalidChars.test(nameInput)) {
        showError(t('invalid_chars'));
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
            showSuccess(t('file_create_success'));
            closeNewFileModal();
            loadLibrary(currentPath);
        } else {
            showError(data.error || t('create_fail'));
        }
    } catch (error) {
        showError(t('create_fail') + ': ' + error.message);
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
    
    if (diff < 60000) return t('just_now');
    if (diff < 3600000) return t('minutes_ago', {n: Math.floor(diff / 60000)});
    if (diff < 86400000) return t('hours_ago', {n: Math.floor(diff / 3600000)});
    if (diff < 604800000) return t('days_ago', {n: Math.floor(diff / 86400000)});
    
    const lang = localStorage.getItem('appLanguage') || 'zh-CN';
    return date.toLocaleDateString(lang);
}

function showSuccess(message) {
    alert('✅ ' + message);
}

function showError(message) {
    alert('❌ ' + message);
}

// ===== 查看源代码功能 =====

// 打开源代码模态框
function openSourceModal() {
    if (!currentMarkdownSource) {
        showError(t('no_source'));
            return;
        }

    const codeElement = document.querySelector('#sourceContent code');
    codeElement.textContent = currentMarkdownSource;
    sourceModal.classList.add('show');
}

// 复制源代码
async function copySourceCode() {
    const success = await copyToClipboard(currentMarkdownSource);
    if (success) {
        showSuccess(t('copy_success'));
    } else {
        showError(t('copy_fail'));
    }
}

// ===== 新增功能：代码复制、Mermaid、数学公式复制 =====

// 渲染MathJax数学公式（带加载检测）
async function renderMathJax() {
    // 检查MathJax是否已加载
    if (!window.MathJax) {
        console.warn('⚠️ MathJax库未加载，等待加载...');
        // 等待MathJax加载
        await new Promise(resolve => {
            const checkMathJax = setInterval(() => {
                if (window.MathJax && window.MathJax.typesetPromise) {
                    clearInterval(checkMathJax);
                    console.log('✅ MathJax库已加载');
                    resolve();
                }
            }, 100);
            // 超时保护（10秒）
            setTimeout(() => {
                clearInterval(checkMathJax);
                console.warn('⚠️ MathJax加载超时');
                resolve();
            }, 10000);
        });
    }
    
    // 再次检查MathJax及其typesetPromise是否可用
    if (window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
        try {
            await MathJax.typesetPromise([previewContent]);
            console.log('✅ MathJax渲染完成');
        } catch (err) {
            console.error('❌ MathJax渲染失败:', err);
        }
    } else if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
        // 如果typesetPromise还不可用，等待startup完成
        try {
            await MathJax.startup.promise;
            if (typeof MathJax.typesetPromise === 'function') {
                await MathJax.typesetPromise([previewContent]);
                console.log('✅ MathJax渲染完成（通过startup）');
            }
        } catch (err) {
            console.error('❌ MathJax渲染失败:', err);
        }
    } else {
        console.warn('⚠️ MathJax不可用或未正确加载');
    }
}

// 初始化Mermaid
function initializeMermaid() {
    if (window.mermaid) {
        mermaid.initialize({
            startOnLoad: false,
            theme: 'default',
            securityLevel: 'loose',
            themeVariables: {
                fontFamily: 'Arial, sans-serif'
            },
            flowchart: {
                useMaxWidth: true,
                htmlLabels: true
            }
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
            
            const success = await copyToClipboard(text);
            
            if (success) {
                button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';
                button.classList.add('copied');
                
                setTimeout(() => {
                    button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                    button.classList.remove('copied');
                }, 2000);
            } else {
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
            
            const success = await copyToClipboard(latexCode);
            
            if (success) {
                button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';
                button.classList.add('copied');
                
                setTimeout(() => {
                    button.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                    button.classList.remove('copied');
                }, 2000);
            } else {
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
            themeVariables: {
                fontFamily: 'Arial, sans-serif'
            },
            flowchart: {
                useMaxWidth: true,
                htmlLabels: true
            }
        });
    } catch (err) {
        console.error('Mermaid初始化失败:', err);
    }
    
    for (let i = 0; i < mermaidBlocks.length; i++) {
        const codeBlock = mermaidBlocks[i];
        const pre = codeBlock.parentElement;
        // 使用 textContent 会自动解码 HTML 实体
        const mermaidCode = codeBlock.textContent.trim();
        
        console.log(`🔧 处理Mermaid图表 ${i + 1}:`, mermaidCode.substring(0, 50) + '...');
        console.log(`📝 完整代码:`, mermaidCode);
        
        // 创建容器
        const container = document.createElement('div');
        container.className = 'mermaid-container';
        container.setAttribute('data-index', i);
        // 保存原始代码到容器的 data 属性中
        container.setAttribute('data-mermaid-source', mermaidCode);
        
        // 创建Mermaid渲染区域
        const mermaidDiv = document.createElement('div');
        mermaidDiv.className = 'mermaid';
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
            // 从容器的 data 属性中获取原始代码
            const sourceCode = container.getAttribute('data-mermaid-source') || mermaidCode;
            const success = await copyToClipboard(sourceCode);
            if (success) {
                copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';
                copyBtn.classList.add('success');
                setTimeout(() => {
                    copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
                    copyBtn.classList.remove('success');
                }, 2000);
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
    
    // 渲染所有Mermaid图表 - 使用手动渲染方式，更可控
    try {
        const containers = previewContent.querySelectorAll('.mermaid-container');
        console.log(`📌 准备渲染 ${containers.length} 个Mermaid图表`);
        
        for (let i = 0; i < containers.length; i++) {
            const container = containers[i];
            const mermaidDiv = container.querySelector('.mermaid');
            
            // 从容器的 data 属性中获取原始代码
            const graphDefinition = container.getAttribute('data-mermaid-source');
            
            if (!graphDefinition) {
                console.error(`❌ 图表 ${i + 1} 没有找到源代码`);
                continue;
            }
            
            const id = `mermaid-diagram-${Date.now()}-${i}`;
            
            console.log(`🎯 渲染图表 ${i + 1}, ID: ${id}`);
            console.log(`📄 图表定义 (前100字符):`, graphDefinition.substring(0, 100));
            
            try {
                // 使用 mermaid.render() 方法渲染
                const { svg } = await mermaid.render(id, graphDefinition);
                mermaidDiv.innerHTML = svg;
                console.log(`✅ 图表 ${i + 1} 渲染成功`);
            } catch (renderErr) {
                console.error(`❌ 图表 ${i + 1} 渲染失败:`, renderErr);
                console.error(`❌ 完整错误信息:`, {
                    message: renderErr.message,
                    name: renderErr.name,
                    stack: renderErr.stack
                });
                
                // 显示友好的错误信息
                mermaidDiv.innerHTML = `<div style="padding: 20px; background: #fee; border: 2px solid #f88; border-radius: 6px; color: #c33; font-family: monospace; max-width: 100%; overflow: auto;">
                    <strong style="font-size: 16px;">❌ Mermaid 图表渲染失败</strong><br><br>
                    <strong>错误信息：</strong><br>
                    <div style="background: #fff; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 4px; color: #d00;">
                        ${escapeHtml(renderErr.message || '未知错误')}
                    </div>
                    <details style="margin-top: 10px;">
                        <summary style="cursor: pointer; font-weight: bold;">📝 查看图表源代码</summary>
                        <pre style="background: #fff; padding: 10px; margin-top: 10px; border: 1px solid #ddd; border-radius: 4px; overflow-x: auto; color: #333; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(graphDefinition)}</pre>
                    </details>
                    <small style="display: block; margin-top: 10px; color: #666;">💡 提示：检查图表语法是否正确，或参考 <a href="https://mermaid.js.org/" target="_blank" style="color: #0066cc;">Mermaid 官方文档</a></small>
                </div>`;
            }
        }
        
        console.log('✅ Mermaid图表渲染完成');
    } catch (err) {
        console.error('❌ Mermaid渲染过程出错:', err);
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

// ===== 文件实时监控 =====
let _lastDirMtime = 0;
let _lastFileMtime = 0;
let _watcherTimer = null;

function startFileWatcher() {
    if (_watcherTimer) return;
    _watcherTimer = setInterval(checkForUpdates, 3000);
    checkForUpdates();
}

async function checkForUpdates() {
    try {
        const params = new URLSearchParams();
        params.set('path', currentPath);
        if (selectedFile) params.set('file', selectedFile);

        const resp = await fetch('/api/library/check-updates?' + params);
        if (!resp.ok) return;
        const data = await resp.json();

        if (_lastDirMtime && data.dir_mtime > _lastDirMtime) {
            loadLibrary(currentPath, true);
        }
        _lastDirMtime = data.dir_mtime;

        if (selectedFile && _lastFileMtime && data.file_mtime > _lastFileMtime) {
            previewFile(selectedFile, true);
        }
        _lastFileMtime = data.file_mtime;
    } catch (e) {
        // ignore
    }
}
