// ===== MarkiNote 国际化系统 =====
(function () {
    'use strict';

    const I18N = {
        'zh-CN': {
            loading: '加载中...', cancel: '取消', confirm: '确定', delete_word: '删除', rename: '重命名',
            save: '保存', edit: '编辑', copy: '复制', close: '关闭',
            library: 'Library', search_files: '搜索文件', settings: '设置',
            root_dir: '根目录', folder_empty: '📁 文件夹为空',
            folder_empty_hint: '点击"上传"按钮添加文件',
            upload_title: '上传文件或文件夹', new_title: '新建文件或文件夹',
            search_placeholder: '搜索文件...', no_search_result: '无搜索结果',
            no_search_hint: '试试其他关键词',
            select_file_preview: '选择文件以预览', view_source: '查看源代码',
            ai_assistant: 'AI 助手',
            welcome_title: '欢迎使用 MarkiNote',
            welcome_desc: '从左侧选择一个文件开始预览',
            welcome_tip: '支持的文件格式：.md、.markdown、.txt',
            upload_select: '选择上传方式', upload_file: '上传文件', upload_folder: '上传文件夹',
            source_code: '源代码', edit_source: '编辑源代码',
            select_new_type: '选择新建类型', new_file: '新建文件', new_folder: '新建文件夹',
            file_name: '文件名', file_name_placeholder: '请输入文件名（不含扩展名）',
            file_type: '文件类型', file_name_hint: '💡 提示：文件名无需输入扩展名',
            folder_name_placeholder: '文件夹名称',
            move_to_folder: '移动到文件夹', moving: '正在移动:',
            rename_title: '重命名', original_name: '原名称:', new_name_placeholder: '输入新名称',
            move_to: '移动到...', search_bing: '用必应搜索', find_in_source: '在源代码中显示',
            language_label: '语言 / Language', language_hint: 'AI 回复将使用所选语言',
            theme_label: '主题 / Theme',
            theme_light: '浅色', theme_dark: '深色', theme_blue: '蓝色', theme_pink: '粉色',
            delete_confirm: '确定要删除 "{name}" 吗？',
            delete_success: '删除成功', move_success: '移动成功',
            move_confirm: '确定要将 "{item}" 移动到 "{target}" 吗？',
            rename_success: '重命名成功',
            upload_success: '成功上传 {count} 个文件',
            upload_fail_count: '，失败 {count} 个',
            upload_fail: '上传失败',
            no_supported_files: '没有找到支持的文件（.md, .markdown, .txt）',
            folder_create_success: '文件夹创建成功', file_create_success: '文件创建成功',
            save_success: '保存成功', copy_success: '源代码已复制到剪贴板',
            copy_fail: '复制失败', no_source: '没有可用的源代码',
            file_deleted: '文件已删除', select_other_file: '请选择其他文件预览',
            unsaved_exit: '您有未保存的改动，确定要退出编辑模式吗？\n改动将不会被保存。',
            unsaved_close: '您有未保存的改动，确定要关闭吗？\n改动将不会被保存。',
            enter_folder_name: '请输入文件夹名称', enter_file_name: '请输入文件名',
            invalid_chars: '名称包含非法字符: < > : " / \\ | ? *',
            name_empty: '名称不能为空', name_same: '新名称与原名称相同',
            source_not_found: '在源代码中未找到该文本',
            more_actions: '更多操作', copy_code: '复制代码', copy_latex: '复制LaTeX代码',
            export_jpg: '导出为JPG', copy_source: '复制源代码',
            just_now: '刚刚', minutes_ago: '{n} 分钟前', hours_ago: '{n} 小时前', days_ago: '{n} 天前',
            collapse_sidebar: '收起/展开侧边栏',
            ai_panel_title: 'AI 助手', new_chat: '新对话', chat_history: '对话历史',
            ai_settings: '设置', ai_close: '关闭',
            ai_provider: 'AI 提供商', ai_model: '模型', api_key: 'API Key',
            api_key_placeholder: '输入你的 API Key', validate: '验证', validating: '验证中...',
            enter_api_key: '请输入 API Key', set_api_key_first: '请先设置 API Key',
            validate_fail: '验证失败: ',
            no_conversations: '暂无对话记录', load_failed: '加载失败',
            ai_welcome_title: 'AI 助手',
            ai_welcome_desc: '我可以帮你管理文档、编辑文件、搜索资料。',
            ai_welcome_hint: '先在上方设置中配置 API Key 即可开始。',
            input_placeholder: '输入消息...', send: '发送', attach_file: '添加文件',
            stop_generating: '停止生成',
            no_reply: '（无回复内容）', stopped: '— 已停止 —', connection_error: '连接错误: ',
            wait_ai: '请等待 AI 回复完成后再操作',
            rollback_confirm: '确定要从此处回滚吗？\n\n此操作将删除该消息之后的所有对话内容，并回滚相关的文件修改。',
            edit_confirm: '确定要编辑此消息吗？\n\n此操作将删除该消息及之后的所有对话内容，并回滚相关的文件修改。\n编辑后发送将作为全新的回合处理。',
            rollback_fail: '回滚失败: ', rollback_request_fail: '回滚请求失败: ',
            delete_conv_confirm: '确定删除这个对话？',
            edit_msg: '编辑此消息', rollback_msg: '从此处回滚',
            executing: '执行中...', rollback_op: '↩ 回滚此操作',
            rolling_back: '回滚中...', rolled_back: '✓ 已回滚',
            rollback_failed: '回滚失败: ', rollback_error: '回滚出错',
            rollback_op_confirm: '确定回滚「{type}」操作吗？\n文件: {path}',
            back_up: '← 返回上级', no_files: '暂无文件',
            current_prefix: '当前: ', remove_label: '移除',
            messages_count: '{count} 条消息',
            tool_read: '读取 {path}', tool_read_range: ' (第{start}-{end}行)',
            tool_write: '写入 {path}', tool_edit: '编辑 {path}',
            tool_create: '创建 {path}', tool_create_folder: '创建文件夹 {path}',
            tool_delete: '删除 {path}', tool_move: '移动 {source} → {target}',
            tool_list: '列出目录 {path}', tool_search: '搜索 "{query}"',
            tool_web_search: '网络搜索 "{query}"', tool_fetch: '抓取网页 {url}',
            preview_fail: '预览失败', load_fail: '加载失败: ',
            error_prefix: '错误', create_fail: '创建失败', rename_fail: '重命名失败',
            move_fail: '移动失败', delete_fail: '删除失败', save_fail: '保存失败',
            load_list_fail: '加载文件列表失败', no_move_target: '没有可移动的目标文件夹',
            load_folder_fail: '加载文件夹列表失败',
        },
        'en': {
            loading: 'Loading...', cancel: 'Cancel', confirm: 'OK', delete_word: 'Delete', rename: 'Rename',
            save: 'Save', edit: 'Edit', copy: 'Copy', close: 'Close',
            library: 'Library', search_files: 'Search', settings: 'Settings',
            root_dir: 'Root', folder_empty: '📁 Folder is empty',
            folder_empty_hint: 'Click "Upload" to add files',
            upload_title: 'Upload file or folder', new_title: 'New file or folder',
            search_placeholder: 'Search files...', no_search_result: 'No results found',
            no_search_hint: 'Try other keywords',
            select_file_preview: 'Select a file to preview', view_source: 'View Source',
            ai_assistant: 'AI Assistant',
            welcome_title: 'Welcome to MarkiNote',
            welcome_desc: 'Select a file from the left panel to preview',
            welcome_tip: 'Supported formats: .md, .markdown, .txt',
            upload_select: 'Choose Upload Method', upload_file: 'Upload File', upload_folder: 'Upload Folder',
            source_code: 'Source Code', edit_source: 'Edit Source Code',
            select_new_type: 'Select Type', new_file: 'New File', new_folder: 'New Folder',
            file_name: 'File Name', file_name_placeholder: 'Enter file name (without extension)',
            file_type: 'File Type', file_name_hint: '💡 Tip: No need to enter file extension',
            folder_name_placeholder: 'Folder name',
            move_to_folder: 'Move to Folder', moving: 'Moving:',
            rename_title: 'Rename', original_name: 'Original name:', new_name_placeholder: 'Enter new name',
            move_to: 'Move to...', search_bing: 'Search with Bing', find_in_source: 'Show in Source',
            language_label: 'Language', language_hint: 'AI will respond in the selected language',
            theme_label: 'Theme',
            theme_light: 'Light', theme_dark: 'Dark', theme_blue: 'Blue', theme_pink: 'Pink',
            delete_confirm: 'Are you sure you want to delete "{name}"?',
            delete_success: 'Deleted successfully', move_success: 'Moved successfully',
            move_confirm: 'Move "{item}" to "{target}"?',
            rename_success: 'Renamed successfully',
            upload_success: 'Successfully uploaded {count} file(s)',
            upload_fail_count: ', {count} failed',
            upload_fail: 'Upload failed',
            no_supported_files: 'No supported files found (.md, .markdown, .txt)',
            folder_create_success: 'Folder created', file_create_success: 'File created',
            save_success: 'Saved', copy_success: 'Source code copied to clipboard',
            copy_fail: 'Copy failed', no_source: 'No source code available',
            file_deleted: 'File deleted', select_other_file: 'Please select another file',
            unsaved_exit: 'You have unsaved changes. Exit edit mode?\nChanges will not be saved.',
            unsaved_close: 'You have unsaved changes. Close?\nChanges will not be saved.',
            enter_folder_name: 'Please enter folder name', enter_file_name: 'Please enter file name',
            invalid_chars: 'Name contains invalid characters: < > : " / \\ | ? *',
            name_empty: 'Name cannot be empty', name_same: 'New name is the same as the original',
            source_not_found: 'Text not found in source code',
            more_actions: 'More', copy_code: 'Copy code', copy_latex: 'Copy LaTeX',
            export_jpg: 'Export as JPG', copy_source: 'Copy source',
            just_now: 'Just now', minutes_ago: '{n} min ago', hours_ago: '{n} hr ago', days_ago: '{n} days ago',
            collapse_sidebar: 'Toggle sidebar',
            ai_panel_title: 'AI Assistant', new_chat: 'New Chat', chat_history: 'History',
            ai_settings: 'Settings', ai_close: 'Close',
            ai_provider: 'AI Provider', ai_model: 'Model', api_key: 'API Key',
            api_key_placeholder: 'Enter your API Key', validate: 'Validate', validating: 'Validating...',
            enter_api_key: 'Please enter API Key', set_api_key_first: 'Please set up API Key first',
            validate_fail: 'Validation failed: ',
            no_conversations: 'No conversations yet', load_failed: 'Failed to load',
            ai_welcome_title: 'AI Assistant',
            ai_welcome_desc: 'I can help you manage documents, edit files, and search for information.',
            ai_welcome_hint: 'Configure your API Key in Settings above to get started.',
            input_placeholder: 'Type a message...', send: 'Send', attach_file: 'Attach file',
            stop_generating: 'Stop generating',
            no_reply: '(No response)', stopped: '— Stopped —', connection_error: 'Connection error: ',
            wait_ai: 'Please wait for the AI to finish responding',
            rollback_confirm: 'Rollback from here?\n\nThis will delete all messages after this point and revert file changes.',
            edit_confirm: 'Edit this message?\n\nThis will delete this and all subsequent messages, and revert file changes.',
            rollback_fail: 'Rollback failed: ', rollback_request_fail: 'Rollback request failed: ',
            delete_conv_confirm: 'Delete this conversation?',
            edit_msg: 'Edit message', rollback_msg: 'Rollback from here',
            executing: 'Executing...', rollback_op: '↩ Rollback',
            rolling_back: 'Rolling back...', rolled_back: '✓ Rolled back',
            rollback_failed: 'Rollback failed: ', rollback_error: 'Rollback error',
            rollback_op_confirm: 'Rollback "{type}" operation?\nFile: {path}',
            back_up: '← Back', no_files: 'No files',
            current_prefix: 'Current: ', remove_label: 'Remove',
            messages_count: '{count} messages',
            tool_read: 'Read {path}', tool_read_range: ' (lines {start}-{end})',
            tool_write: 'Write {path}', tool_edit: 'Edit {path}',
            tool_create: 'Create {path}', tool_create_folder: 'Create folder {path}',
            tool_delete: 'Delete {path}', tool_move: 'Move {source} → {target}',
            tool_list: 'List directory {path}', tool_search: 'Search "{query}"',
            tool_web_search: 'Web search "{query}"', tool_fetch: 'Fetch page {url}',
            preview_fail: 'Preview failed', load_fail: 'Failed to load: ',
            error_prefix: 'Error', create_fail: 'Creation failed', rename_fail: 'Rename failed',
            move_fail: 'Move failed', delete_fail: 'Delete failed', save_fail: 'Save failed',
            load_list_fail: 'Failed to load file list', no_move_target: 'No available target folders',
            load_folder_fail: 'Failed to load folder list',
        },
        'fr': {
            loading: 'Chargement...', cancel: 'Annuler', confirm: 'OK', delete_word: 'Supprimer', rename: 'Renommer',
            save: 'Enregistrer', edit: 'Modifier', copy: 'Copier', close: 'Fermer',
            library: 'Bibliothèque', search_files: 'Rechercher', settings: 'Paramètres',
            root_dir: 'Racine', folder_empty: '📁 Dossier vide',
            folder_empty_hint: 'Cliquez « Télécharger » pour ajouter',
            upload_title: 'Télécharger', new_title: 'Nouveau',
            search_placeholder: 'Rechercher...', no_search_result: 'Aucun résultat',
            no_search_hint: "Essayez d'autres mots-clés",
            select_file_preview: 'Sélectionnez un fichier', view_source: 'Voir la source',
            ai_assistant: 'Assistant IA',
            welcome_title: 'Bienvenue sur MarkiNote',
            welcome_desc: 'Sélectionnez un fichier à gauche pour le prévisualiser',
            welcome_tip: 'Formats supportés : .md, .markdown, .txt',
            upload_select: 'Méthode de téléchargement', upload_file: 'Fichier', upload_folder: 'Dossier',
            source_code: 'Code source', edit_source: 'Modifier le code source',
            select_new_type: 'Choisir le type', new_file: 'Nouveau fichier', new_folder: 'Nouveau dossier',
            file_name: 'Nom du fichier', file_name_placeholder: 'Entrez le nom (sans extension)',
            file_type: 'Type de fichier', file_name_hint: "💡 Pas besoin d'extension",
            folder_name_placeholder: 'Nom du dossier',
            move_to_folder: 'Déplacer vers', moving: 'Déplacement de :',
            rename_title: 'Renommer', original_name: 'Nom actuel :', new_name_placeholder: 'Nouveau nom',
            move_to: 'Déplacer vers...', search_bing: 'Rechercher avec Bing', find_in_source: 'Afficher dans la source',
            language_label: 'Langue', language_hint: "L'IA répondra dans la langue sélectionnée",
            theme_label: 'Thème',
            theme_light: 'Clair', theme_dark: 'Sombre', theme_blue: 'Bleu', theme_pink: 'Rose',
            delete_confirm: 'Supprimer « {name} » ?',
            delete_success: 'Supprimé', move_success: 'Déplacé',
            move_confirm: 'Déplacer « {item} » vers « {target} » ?',
            rename_success: 'Renommé',
            upload_success: '{count} fichier(s) téléchargé(s)',
            upload_fail_count: ', {count} échoué(s)', upload_fail: 'Échec du téléchargement',
            no_supported_files: 'Aucun fichier supporté (.md, .markdown, .txt)',
            folder_create_success: 'Dossier créé', file_create_success: 'Fichier créé',
            save_success: 'Enregistré', copy_success: 'Code source copié',
            copy_fail: 'Échec de la copie', no_source: 'Aucun code source disponible',
            file_deleted: 'Fichier supprimé', select_other_file: 'Sélectionnez un autre fichier',
            unsaved_exit: 'Modifications non enregistrées. Quitter ?', unsaved_close: 'Modifications non enregistrées. Fermer ?',
            enter_folder_name: 'Entrez le nom du dossier', enter_file_name: 'Entrez le nom du fichier',
            invalid_chars: 'Caractères invalides : < > : " / \\ | ? *',
            name_empty: 'Le nom ne peut pas être vide', name_same: 'Le nom est identique',
            source_not_found: 'Texte non trouvé dans le code source',
            more_actions: 'Plus', copy_code: 'Copier le code', copy_latex: 'Copier LaTeX',
            export_jpg: 'Exporter en JPG', copy_source: 'Copier la source',
            just_now: "À l'instant", minutes_ago: 'il y a {n} min', hours_ago: 'il y a {n} h', days_ago: 'il y a {n} j',
            collapse_sidebar: 'Basculer la barre latérale',
            ai_panel_title: 'Assistant IA', new_chat: 'Nouvelle conversation', chat_history: 'Historique',
            ai_settings: 'Paramètres', ai_close: 'Fermer',
            ai_provider: 'Fournisseur IA', ai_model: 'Modèle', api_key: 'Clé API',
            api_key_placeholder: 'Entrez votre clé API', validate: 'Valider', validating: 'Validation...',
            enter_api_key: 'Entrez la clé API', set_api_key_first: 'Configurez la clé API',
            validate_fail: 'Échec : ',
            no_conversations: 'Aucune conversation', load_failed: 'Échec du chargement',
            ai_welcome_title: 'Assistant IA',
            ai_welcome_desc: 'Je peux gérer vos documents, modifier des fichiers et rechercher des informations.',
            ai_welcome_hint: 'Configurez votre clé API dans les paramètres ci-dessus.',
            input_placeholder: 'Tapez un message...', send: 'Envoyer', attach_file: 'Joindre un fichier',
            stop_generating: 'Arrêter',
            no_reply: '(Pas de réponse)', stopped: '— Arrêté —', connection_error: 'Erreur de connexion : ',
            wait_ai: "Attendez la fin de la réponse de l'IA",
            rollback_confirm: 'Revenir en arrière ?\n\nCela supprimera les messages suivants et annulera les modifications.',
            edit_confirm: 'Modifier ce message ?\n\nCela supprimera ce message et les suivants.',
            rollback_fail: 'Échec : ', rollback_request_fail: 'Échec de la requête : ',
            delete_conv_confirm: 'Supprimer cette conversation ?',
            edit_msg: 'Modifier', rollback_msg: 'Revenir en arrière',
            executing: 'Exécution...', rollback_op: '↩ Annuler',
            rolling_back: 'Annulation...', rolled_back: '✓ Annulé',
            rollback_failed: 'Échec : ', rollback_error: "Erreur d'annulation",
            rollback_op_confirm: 'Annuler « {type} » ?\nFichier : {path}',
            back_up: '← Retour', no_files: 'Aucun fichier',
            current_prefix: 'Actuel : ', remove_label: 'Retirer',
            messages_count: '{count} messages',
            tool_read: 'Lire {path}', tool_read_range: ' (lignes {start}-{end})',
            tool_write: 'Écrire {path}', tool_edit: 'Modifier {path}',
            tool_create: 'Créer {path}', tool_create_folder: 'Créer dossier {path}',
            tool_delete: 'Supprimer {path}', tool_move: 'Déplacer {source} → {target}',
            tool_list: 'Lister {path}', tool_search: 'Rechercher « {query} »',
            tool_web_search: 'Recherche web « {query} »', tool_fetch: 'Récupérer {url}',
            preview_fail: 'Échec de la prévisualisation', load_fail: 'Échec : ',
            error_prefix: 'Erreur', create_fail: 'Échec de la création', rename_fail: 'Échec du renommage',
            move_fail: 'Échec du déplacement', delete_fail: 'Échec de la suppression', save_fail: "Échec de l'enregistrement",
            load_list_fail: 'Échec du chargement de la liste', no_move_target: 'Aucun dossier cible disponible',
            load_folder_fail: 'Échec du chargement des dossiers',
        },
        'ja': {
            loading: '読み込み中...', cancel: 'キャンセル', confirm: 'OK', delete_word: '削除', rename: '名前変更',
            save: '保存', edit: '編集', copy: 'コピー', close: '閉じる',
            library: 'ライブラリ', search_files: '検索', settings: '設定',
            root_dir: 'ルート', folder_empty: '📁 フォルダが空です',
            folder_empty_hint: '「アップロード」をクリックしてファイルを追加',
            upload_title: 'アップロード', new_title: '新規作成',
            search_placeholder: 'ファイルを検索...', no_search_result: '結果なし',
            no_search_hint: '他のキーワードをお試しください',
            select_file_preview: 'ファイルを選択してプレビュー', view_source: 'ソースを表示',
            ai_assistant: 'AIアシスタント',
            welcome_title: 'MarkiNote へようこそ',
            welcome_desc: '左側からファイルを選択してプレビュー',
            welcome_tip: '対応形式：.md、.markdown、.txt',
            upload_select: 'アップロード方法', upload_file: 'ファイル', upload_folder: 'フォルダ',
            source_code: 'ソースコード', edit_source: 'ソースを編集',
            select_new_type: '種類を選択', new_file: '新規ファイル', new_folder: '新規フォルダ',
            file_name: 'ファイル名', file_name_placeholder: 'ファイル名を入力（拡張子不要）',
            file_type: 'ファイルの種類', file_name_hint: '💡 拡張子は不要です',
            folder_name_placeholder: 'フォルダ名',
            move_to_folder: 'フォルダに移動', moving: '移動中：',
            rename_title: '名前変更', original_name: '現在の名前：', new_name_placeholder: '新しい名前を入力',
            move_to: '移動先...', search_bing: 'Bingで検索', find_in_source: 'ソースで表示',
            language_label: '言語', language_hint: 'AIが選択した言語で回答します',
            theme_label: 'テーマ',
            theme_light: 'ライト', theme_dark: 'ダーク', theme_blue: 'ブルー', theme_pink: 'ピンク',
            delete_confirm: '「{name}」を削除しますか？',
            delete_success: '削除しました', move_success: '移動しました',
            move_confirm: '「{item}」を「{target}」に移動しますか？',
            rename_success: '名前を変更しました',
            upload_success: '{count}個のファイルをアップロードしました',
            upload_fail_count: '、{count}個失敗', upload_fail: 'アップロード失敗',
            no_supported_files: '対応ファイルがありません',
            folder_create_success: 'フォルダを作成しました', file_create_success: 'ファイルを作成しました',
            save_success: '保存しました', copy_success: 'ソースをコピーしました',
            copy_fail: 'コピー失敗', no_source: 'ソースコードがありません',
            file_deleted: 'ファイル削除済み', select_other_file: '他のファイルを選択してください',
            unsaved_exit: '未保存の変更があります。終了しますか？', unsaved_close: '未保存の変更があります。閉じますか？',
            enter_folder_name: 'フォルダ名を入力', enter_file_name: 'ファイル名を入力',
            invalid_chars: '無効な文字: < > : " / \\ | ? *',
            name_empty: '名前を入力してください', name_same: '同じ名前です',
            source_not_found: 'テキストが見つかりません',
            more_actions: 'その他', copy_code: 'コードをコピー', copy_latex: 'LaTeXをコピー',
            export_jpg: 'JPGとして保存', copy_source: 'ソースをコピー',
            just_now: 'たった今', minutes_ago: '{n}分前', hours_ago: '{n}時間前', days_ago: '{n}日前',
            collapse_sidebar: 'サイドバー切替',
            ai_panel_title: 'AIアシスタント', new_chat: '新規チャット', chat_history: '履歴',
            ai_settings: '設定', ai_close: '閉じる',
            ai_provider: 'AIプロバイダー', ai_model: 'モデル', api_key: 'APIキー',
            api_key_placeholder: 'APIキーを入力', validate: '検証', validating: '検証中...',
            enter_api_key: 'APIキーを入力してください', set_api_key_first: 'まずAPIキーを設定',
            validate_fail: '検証失敗: ',
            no_conversations: '会話履歴なし', load_failed: '読み込み失敗',
            ai_welcome_title: 'AIアシスタント',
            ai_welcome_desc: 'ドキュメント管理、ファイル編集、情報検索をお手伝いします。',
            ai_welcome_hint: '上の設定でAPIキーを設定してください。',
            input_placeholder: 'メッセージを入力...', send: '送信', attach_file: 'ファイルを添付',
            stop_generating: '生成停止',
            no_reply: '（応答なし）', stopped: '— 停止 —', connection_error: '接続エラー: ',
            wait_ai: 'AIの応答完了をお待ちください',
            rollback_confirm: 'ここからロールバックしますか？\n\n以降の内容が削除されます。',
            edit_confirm: 'このメッセージを編集しますか？\n\n以降の内容が削除されます。',
            rollback_fail: 'ロールバック失敗: ', rollback_request_fail: 'リクエスト失敗: ',
            delete_conv_confirm: 'この会話を削除しますか？',
            edit_msg: 'メッセージ編集', rollback_msg: 'ロールバック',
            executing: '実行中...', rollback_op: '↩ 元に戻す',
            rolling_back: '戻し中...', rolled_back: '✓ 戻しました',
            rollback_failed: '失敗: ', rollback_error: 'エラー',
            rollback_op_confirm: '「{type}」を元に戻しますか？\nファイル: {path}',
            back_up: '← 戻る', no_files: 'ファイルなし',
            current_prefix: '現在: ', remove_label: '削除',
            messages_count: '{count}件',
            tool_read: '読取 {path}', tool_read_range: ' ({start}-{end}行)',
            tool_write: '書込 {path}', tool_edit: '編集 {path}',
            tool_create: '作成 {path}', tool_create_folder: 'フォルダ作成 {path}',
            tool_delete: '削除 {path}', tool_move: '移動 {source} → {target}',
            tool_list: 'ディレクトリ一覧 {path}', tool_search: '検索 「{query}」',
            tool_web_search: 'Web検索 「{query}」', tool_fetch: 'ページ取得 {url}',
            preview_fail: 'プレビュー失敗', load_fail: '読み込み失敗: ',
            error_prefix: 'エラー', create_fail: '作成失敗', rename_fail: '名前変更失敗',
            move_fail: '移動失敗', delete_fail: '削除失敗', save_fail: '保存失敗',
            load_list_fail: 'ファイル一覧の読み込み失敗', no_move_target: '移動先フォルダがありません',
            load_folder_fail: 'フォルダ一覧の読み込み失敗',
        }
    };

    function t(key, params) {
        const lang = localStorage.getItem('appLanguage') || 'zh-CN';
        const dict = I18N[lang] || I18N['zh-CN'];
        let text = dict[key] || I18N['zh-CN'][key] || key;
        if (params) {
            for (const [k, v] of Object.entries(params)) {
                text = text.replace(new RegExp('\\{' + k + '\\}', 'g'), v);
            }
        }
        return text;
    }

    function applyLanguage() {
        const _s = (sel, key) => { const e = document.querySelector(sel); if (e) e.textContent = t(key); };
        const _a = (sel, attr, key) => { const e = document.querySelector(sel); if (e) e.setAttribute(attr, t(key)); };

        // Library sidebar
        _a('#searchBtn', 'title', 'search_files');
        _a('#settingsBtn', 'title', 'settings');
        _a('#uploadBtn', 'title', 'upload_title');
        _a('#newBtn', 'title', 'new_title');
        _a('#searchInput', 'placeholder', 'search_placeholder');
        _a('#sidebarToggleBtn', 'title', 'collapse_sidebar');
        _a('#aiToggleBtn', 'title', 'ai_assistant');

        // View source button text
        const vsSpan = document.querySelector('#viewSourceBtn .btn-text');
        if (vsSpan) vsSpan.textContent = t('view_source');

        // Preview welcome
        const pw = document.querySelector('.preview-content .welcome-message');
        if (pw) {
            const h3 = pw.querySelector('h3');
            const ps = pw.querySelectorAll('p');
            if (h3) h3.textContent = t('welcome_title');
            if (ps[0]) ps[0].textContent = t('welcome_desc');
            if (ps[1]) ps[1].textContent = t('welcome_tip');
        }

        // Modals
        _s('#uploadModal .modal-header h3', 'upload_select');
        document.querySelectorAll('#uploadModal .upload-option-btn span').forEach((el, i) => {
            el.textContent = t(i === 0 ? 'upload_file' : 'upload_folder');
        });
        _s('#uploadModal .modal-footer .btn-secondary', 'cancel');

        _s('#sourceModalTitle', 'source_code');
        const editBtn = document.querySelector('#sourceViewActions .btn-secondary');
        if (editBtn) { const sp = editBtn.querySelector('.btn-text'); if (sp) sp.textContent = t('edit'); }
        const copyBtn = document.querySelector('#sourceViewActions .btn-primary');
        if (copyBtn) { const sp = copyBtn.querySelector('.btn-text'); if (sp) sp.textContent = t('copy'); }
        const cancelEdit = document.querySelector('#sourceEditActions .btn-secondary');
        if (cancelEdit) { const sp = cancelEdit.querySelector('.btn-text'); if (sp) sp.textContent = t('cancel'); }
        const saveEdit = document.querySelector('#sourceEditActions .btn-primary');
        if (saveEdit) { const sp = saveEdit.querySelector('.btn-text'); if (sp) sp.textContent = t('save'); }

        _s('#newSelectModal .modal-header h3', 'select_new_type');
        document.querySelectorAll('#newSelectModal .upload-option-btn span').forEach((el, i) => {
            el.textContent = t(i === 0 ? 'new_file' : 'new_folder');
        });
        _s('#newSelectModal .modal-footer .btn-secondary', 'cancel');

        _s('#newFileModal .modal-header h3', 'new_file');
        _s('#newFileModal label[data-role="fname"]', 'file_name');
        _a('#fileNameInput', 'placeholder', 'file_name_placeholder');
        _s('#newFileModal label[data-role="ftype"]', 'file_type');
        _s('#newFileModal .settings-hint', 'file_name_hint');
        _s('#newFileModal .modal-footer .btn-secondary', 'cancel');
        _s('#newFileModal .modal-footer .btn-primary', 'confirm');

        _s('#newFolderModal .modal-header h3', 'new_folder');
        _a('#folderNameInput', 'placeholder', 'folder_name_placeholder');
        _s('#newFolderModal .modal-footer .btn-secondary', 'cancel');
        _s('#newFolderModal .modal-footer .btn-primary', 'confirm');

        _s('#moveModal .modal-header h3', 'move_to_folder');
        _s('#moveModal .modal-footer .btn-secondary', 'cancel');

        _s('#renameModal .modal-header h3', 'rename_title');
        _a('#renameInput', 'placeholder', 'new_name_placeholder');
        _s('#renameModal .modal-footer .btn-secondary', 'cancel');
        _s('#renameModal .modal-footer .btn-primary', 'confirm');

        // Settings modal
        _s('#settingsModal .modal-header h3', 'settings');
        _s('#settingsModal .settings-section:first-child .settings-label', 'language_label');
        _s('#settingsModal .settings-hint', 'language_hint');
        _s('#settingsModal .settings-section:last-child .settings-label', 'theme_label');
        document.querySelectorAll('.theme-option span').forEach(el => {
            const theme = el.parentElement.dataset.theme;
            el.textContent = t('theme_' + theme);
        });

        // Context menus
        const cmItems = document.querySelectorAll('#contextMenu .context-menu-item');
        if (cmItems[0]) { const t0 = cmItems[0].lastChild; if (t0) t0.textContent = '\n            ' + t('rename') + '\n        '; }
        if (cmItems[1]) { const t1 = cmItems[1].lastChild; if (t1) t1.textContent = '\n            ' + t('move_to') + '\n        '; }
        if (cmItems[2]) { const t2 = cmItems[2].lastChild; if (t2) t2.textContent = '\n            ' + t('delete_word') + '\n        '; }

        const pcmItems = document.querySelectorAll('#previewContextMenu .context-menu-item');
        if (pcmItems[0]) { const t0 = pcmItems[0].lastChild; if (t0) t0.textContent = '\n            ' + t('copy') + '\n        '; }
        if (pcmItems[1]) { const t1 = pcmItems[1].lastChild; if (t1) t1.textContent = '\n            ' + t('search_bing') + '\n        '; }
        if (pcmItems[2]) { const t2 = pcmItems[2].lastChild; if (t2) t2.textContent = '\n            ' + t('find_in_source') + '\n        '; }

        // AI panel
        _s('.ai-panel-header h2 .ai-title-text', 'ai_panel_title');
        _a('#aiNewChatBtn', 'title', 'new_chat');
        _a('#aiHistoryBtn', 'title', 'chat_history');
        _a('#aiSettingsBtn', 'title', 'ai_settings');
        _a('#aiCloseBtn', 'title', 'ai_close');

        _s('#aiSettingsPanel .ai-setting-group:nth-child(1) label', 'ai_provider');
        _s('#aiSettingsPanel .ai-setting-group:nth-child(2) label', 'ai_model');
        _s('#aiSettingsPanel .ai-setting-group:nth-child(3) label', 'api_key');
        _a('#aiApiKeyInput', 'placeholder', 'api_key_placeholder');
        _s('#aiValidateKeyBtn', 'validate');

        _a('#aiInput', 'placeholder', 'input_placeholder');
        _a('#aiSendBtn', 'title', 'send');
        _a('#aiAttachBtn', 'title', 'attach_file');

        // AI welcome
        const aw = document.querySelector('.ai-messages .ai-welcome');
        if (aw) {
            const h3 = aw.querySelector('h3');
            const p = aw.querySelector('p');
            if (h3) h3.textContent = t('ai_welcome_title');
            if (p) p.innerHTML = t('ai_welcome_desc') + '<br>' + t('ai_welcome_hint');
        }
    }

    window.I18N = I18N;
    window.t = t;
    window.applyLanguage = applyLanguage;
})();
