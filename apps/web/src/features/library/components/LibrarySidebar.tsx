import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronRight, FileText, Folder, FolderInput, FolderPlus, MoreHorizontal, Pencil, Plus, RefreshCw, Search, Trash2, Upload, X } from 'lucide-react';
import { type ChangeEvent, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { LibraryItem } from '@/shared/api';
import { errorMessage } from '@/shared/api';
import { formatBytes, formatTime } from '@/shared/lib/format';
import { useDebouncedValue } from '@/shared/lib/useDebouncedValue';
import { DropdownMenu } from '@/shared/ui/DropdownMenu';
import { Modal } from '@/shared/ui/Modal';
import { useToast } from '@/shared/ui/Toast';
import { libraryApi } from '../api/libraryApi';
import {
  buildFolderTree,
  initiallyExpandedMovePaths,
  moveTargetRestriction,
} from '../model/libraryTree';
import { uploadBatch } from '../model/uploadBatch';
import { LibraryTreePicker, type LibraryTreeNodeState } from './LibraryTreePicker';

interface Props {
  currentPath: string;
  selectedFile: string;
  onPathChange: (path: string) => void;
  onSelectFile: (path: string) => void | boolean | Promise<boolean>;
  onBeforeItemChange: (path: string) => boolean | Promise<boolean>;
  onItemChanged: (before: string, after?: string) => void;
  onClose?: () => void;
  active?: boolean;
}

type DialogState =
  | { kind: 'none' }
  | { kind: 'create-file' | 'create-folder' }
  | { kind: 'rename' | 'move'; item: LibraryItem };

function uploadTarget(root: string, file: File): string {
  const relative = file.webkitRelativePath;
  if (!relative.includes('/')) return root;
  const folders = relative.split('/').slice(0, -1).join('/');
  return [root, folders].filter(Boolean).join('/');
}

export function LibrarySidebar({ currentPath, selectedFile, onPathChange, onSelectFile, onBeforeItemChange, onItemChanged, onClose, active = true }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const searchId = useId();
  const [query, setQuery] = useState('');
  const [dialog, setDialog] = useState<DialogState>({ kind: 'none' });
  const [name, setName] = useState('');
  const [destination, setDestination] = useState<string | null>(null);
  const [moveExpandedPaths, setMoveExpandedPaths] = useState<Set<string>>(() => new Set(['']));
  const [uploading, setUploading] = useState(false);
  const [preparingOperation, setPreparingOperation] = useState(false);
  const normalizedQuery = query.trim();
  const debouncedQuery = useDebouncedValue(normalizedQuery, 250);
  const searching = normalizedQuery.length > 0;

  const listing = useQuery({
    queryKey: ['library', currentPath],
    queryFn: ({ signal }) => libraryApi.list(currentPath, signal),
    enabled: active,
    refetchInterval: active ? 8_000 : false,
  });
  const searchResults = useQuery({
    queryKey: ['library-search', debouncedQuery],
    queryFn: ({ signal }) => libraryApi.search(debouncedQuery, signal),
    enabled: active && Boolean(debouncedQuery),
    staleTime: 30_000,
  });
  const folders = useQuery({ queryKey: ['library-folders'], queryFn: libraryApi.folders, enabled: dialog.kind === 'move' });
  const waitingForSearch = searching && debouncedQuery !== normalizedQuery;
  const visibleItems = searching
    ? (waitingForSearch ? [] : searchResults.data?.items ?? [])
    : listing.data?.items ?? [];
  const activeLoading = searching ? waitingForSearch || searchResults.isPending : listing.isLoading;
  const activeFetching = searching ? waitingForSearch || searchResults.isFetching : listing.isFetching;
  const activeError = searching && !waitingForSearch ? searchResults.error : listing.error;

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['library'] }),
      queryClient.invalidateQueries({ queryKey: ['library-search'] }),
      queryClient.invalidateQueries({ queryKey: ['library-folders'] }),
    ]);
  };
  const operation = useMutation({
    mutationFn: async () => {
      if (dialog.kind === 'create-file') {
        const fileName = /\.(md|markdown|txt)$/i.test(name) ? name : `${name}.md`;
        return libraryApi.createFile(currentPath, fileName);
      }
      if (dialog.kind === 'create-folder') return libraryApi.createFolder(currentPath, name);
      if (dialog.kind === 'rename') return libraryApi.rename(dialog.item.path, name);
      if (dialog.kind === 'move') {
        if (destination === null) throw new Error(t('chooseDestination'));
        return libraryApi.move(dialog.item.path, destination);
      }
      throw new Error('No operation selected');
    },
    onSuccess: async (result) => {
      const before = 'item' in dialog ? dialog.item.path : '';
      const newPath = 'new_path' in result && typeof result.new_path === 'string' ? result.new_path : undefined;
      if (before) onItemChanged(before, newPath);
      setDialog({ kind: 'none' }); setName(''); setDestination(null);
      await invalidate(); toast(t('operationDone'), 'success');
    },
    onError: (error) => toast(errorMessage(error), 'error'),
  });
  const deleteMutation = useMutation({
    mutationFn: libraryApi.delete,
    onSuccess: async (_, path) => { onItemChanged(path); await invalidate(); toast(t('operationDone'), 'success'); },
    onError: (error) => toast(errorMessage(error), 'error'),
  });

  const openCreate = (kind: 'create-file' | 'create-folder') => { setName(''); setDialog({ kind }); };
  const openRename = (item: LibraryItem) => { setName(item.name); setDialog({ kind: 'rename', item }); };
  const openMove = (item: LibraryItem) => {
    setDestination(null);
    setMoveExpandedPaths(initiallyExpandedMovePaths(item.path));
    setDialog({ kind: 'move', item });
  };
  const pickUpload = (directory: boolean) => {
    if (uploading) return;
    const input = fileInput.current;
    if (!input) return;
    if (directory) { input.setAttribute('webkitdirectory', ''); input.removeAttribute('accept'); }
    else { input.removeAttribute('webkitdirectory'); input.accept = '.md,.markdown,.txt'; }
    input.click();
  };
  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])].filter((file) => /\.(md|markdown|txt)$/i.test(file.name));
    event.target.value = '';
    if (uploading) return;
    if (!files.length) {
      toast(t('noSupportedFiles'), 'error');
      return;
    }
    setUploading(true);
    try {
      const { success, failed } = await uploadBatch(
        files,
        (file) => libraryApi.upload(uploadTarget(currentPath, file), file),
      );
      await invalidate();
      toast(
        failed === 0 ? t('uploadDone', { count: success }) : t('uploadPartial', { success, failed }),
        failed === 0 ? 'success' : 'error',
      );
    } catch (caught) {
      toast(errorMessage(caught), 'error');
    } finally {
      setUploading(false);
    }
  };
  const clearSearch = () => {
    setQuery('');
    searchInput.current?.focus();
  };
  const openItem = async (item: LibraryItem) => {
    if (item.type === 'folder') {
      if (searching) setQuery('');
      onPathChange(item.path);
      return;
    }
    const opened = await onSelectFile(item.path);
    if (opened === false) return;
    if (searching) {
      setQuery('');
      onPathChange(item.path.split('/').slice(0, -1).join('/'));
    }
  };
  const crumbs = currentPath ? currentPath.split('/') : [];
  const moveSource = dialog.kind === 'move' ? dialog.item : null;
  const moveTree = useMemo(
    () => buildFolderTree(folders.data?.folders ?? [], t('root')),
    [folders.data?.folders, t],
  );
  const selectedMovePaths = useMemo(
    () => destination === null ? new Set<string>() : new Set([destination]),
    [destination],
  );
  const validMoveDestinationCount = moveSource
    ? (folders.data?.folders ?? []).filter((folder) => moveTargetRestriction(moveSource, folder.path) === null).length
    : 0;
  const moveNodeState = (node: { path: string }): LibraryTreeNodeState => {
    if (!moveSource) return {};
    const restriction = moveTargetRestriction(moveSource, node.path);
    if (restriction === 'current-parent') {
      return { disabled: true, reason: t('moveCurrentFolder'), note: t('moveCurrentFolder') };
    }
    if (restriction === 'self-or-descendant') {
      return { disabled: true, reason: t('moveInsideSource'), note: t('moveInsideSource') };
    }
    return {};
  };
  const toggleMoveFolder = (path: string) => {
    setMoveExpandedPaths((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };
  const submitOperation = async () => {
    if (preparingOperation || operation.isPending) return;
    setPreparingOperation(true);
    try {
      if ('item' in dialog && !await onBeforeItemChange(dialog.item.path)) return;
      await operation.mutateAsync();
    } catch {
      // The mutation's onError callback owns the user-facing error.
    } finally {
      setPreparingOperation(false);
    }
  };
  const operationLabel = dialog.kind === 'create-file' ? t('newFile')
    : dialog.kind === 'create-folder' ? t('newFolder')
      : dialog.kind === 'rename' ? t('rename')
        : dialog.kind === 'move' ? t('move')
          : t('confirm');
  const operationIcon = dialog.kind === 'create-file' ? <FileText size={15} aria-hidden="true" />
    : dialog.kind === 'create-folder' ? <FolderPlus size={15} aria-hidden="true" />
      : dialog.kind === 'rename' ? <Pencil size={15} aria-hidden="true" />
        : dialog.kind === 'move' ? <FolderInput size={15} aria-hidden="true" />
          : null;

  return <aside id="library-panel" className="library-sidebar" aria-label={t('library')}>
    <div className="sidebar-heading">
      <div><h2>{t('library')}</h2></div>
      <div className="toolbar-actions">
        <button
          type="button"
          className={`icon-button touch-target has-tooltip ${activeFetching ? 'is-loading' : ''}`}
          disabled={activeFetching}
          onClick={() => void (searching ? searchResults.refetch() : listing.refetch())}
          aria-label={t('refresh')}
          title={t('refresh')}
        >
          <RefreshCw size={16} aria-hidden="true" />
        </button>
        {onClose ? <button type="button" className="icon-button touch-target has-tooltip" data-drawer-initial-focus onClick={onClose} aria-label={t('close')} title={t('close')}><X size={16} aria-hidden="true" /></button> : null}
      </div>
    </div>
    <div className="sidebar-actions">
      <DropdownMenu
        label={t('addToLibrary')}
        trigger={<><Plus size={16} aria-hidden="true" />{t('addToLibrary')}</>}
        triggerClassName="button touch-target"
        disabled={uploading}
        items={[
          { id: 'new-file', label: t('newFile'), icon: <FileText size={15} />, onSelect: () => openCreate('create-file') },
          { id: 'new-folder', label: t('newFolder'), icon: <FolderPlus size={15} />, onSelect: () => openCreate('create-folder') },
          { id: 'upload-files', label: t('uploadFiles'), icon: <Upload size={15} />, disabled: uploading, onSelect: () => pickUpload(false) },
          { id: 'upload-folder', label: t('uploadFolder'), icon: <Folder size={15} />, disabled: uploading, onSelect: () => pickUpload(true) },
        ]}
      />
      <input ref={fileInput} disabled={uploading} hidden multiple type="file" onChange={(event) => void handleUpload(event)} />
    </div>
    <div className={`search-box ${query ? 'has-query' : ''}`}>
      <Search size={15} aria-hidden="true" />
      <label className="visually-hidden" htmlFor={searchId}>{t('search')}</label>
      <input
        ref={searchInput}
        id={searchId}
        type="search"
        name="library-search"
        autoComplete="off"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t('search')}
      />
      {query ? <button
        type="button"
        className="icon-button search-clear touch-target has-tooltip"
        onClick={clearSearch}
        aria-label={t('clearSearch')}
        title={t('clearSearch')}
      ><X size={14} aria-hidden="true" /></button> : null}
    </div>
    <nav className="breadcrumbs" aria-label={t('breadcrumbs')}>
      <button
        type="button"
        aria-current={!currentPath ? 'location' : undefined}
        onClick={() => onPathChange('')}
      >{t('root')}</button>
      {crumbs.map((part, index) => {
        const path = crumbs.slice(0, index + 1).join('/');
        const current = index === crumbs.length - 1;
        return <span key={path}>
          <ChevronRight size={13} aria-hidden="true" />
          <button type="button" aria-current={current ? 'location' : undefined} onClick={() => onPathChange(path)}>{part}</button>
        </span>;
      })}
    </nav>
    <div className="library-meta" role="status" aria-live="polite" aria-atomic="true">
      <span>{uploading
        ? t('uploadingDocuments')
        : searching
          ? t('matchingItems', { count: searchResults.data?.total ?? visibleItems.length })
          : t('currentFolderItems', { count: listing.data?.items.length ?? 0 })}</span>
      {searchResults.data?.truncated && searching ? <span>{t('searchResultsLimited', { count: visibleItems.length })}</span> : null}
    </div>
    <div className="file-list" role={visibleItems.length ? 'list' : undefined} aria-busy={activeLoading || activeFetching}>
      {activeLoading && <div className="sidebar-state">{t('loading')}</div>}
      {!activeLoading && activeError && <div className="sidebar-state error" role="alert"><p>{errorMessage(activeError)}</p><button type="button" className="button" onClick={() => void (searching ? searchResults.refetch() : listing.refetch())}>{t('retry')}</button></div>}
      {!activeLoading && !activeError && visibleItems.length === 0 && <div className="sidebar-state">
        <p>{searching ? t('noResults') : t('emptyFolder')}</p>
        {!searching ? <p className="sidebar-state-hint">{t('emptyFolderHint')}</p> : null}
        <div className="sidebar-state-actions">
          {searching
            ? <button type="button" className="button" onClick={clearSearch}>{t('clearSearch')}</button>
            : <button type="button" className="button button-primary" onClick={() => openCreate('create-file')}><Plus size={15} aria-hidden="true" />{t('createFirstDocument')}</button>}
        </div>
      </div>}
      {visibleItems.map((item) => {
        const selected = item.type === 'file' && item.path === selectedFile;
        return <div className={`file-row content-visibility-auto ${selected ? 'selected' : ''}`} role="listitem" key={item.path}>
        <button
          type="button"
          className="file-row-main touch-target"
          aria-current={selected ? 'page' : undefined}
          onClick={() => void openItem(item)}
        >
          <span className={`file-icon ${item.type}`}>{item.type === 'folder' ? <Folder size={19} aria-hidden="true" /> : <FileText size={19} aria-hidden="true" />}</span>
          <span className="file-copy"><strong title={item.name}>{item.name}</strong><small>{[
            searching ? item.path : '',
            formatBytes(item.size),
            formatTime(item.modified),
          ].filter(Boolean).join(' · ')}</small></span>
        </button>
        <DropdownMenu
          className="row-menu"
          align="end"
          label={`${item.name} — ${t('actions')}`}
          trigger={<MoreHorizontal size={17} aria-hidden="true" />}
          triggerClassName="icon-button touch-target has-tooltip"
          items={[
            { id: 'rename', label: t('rename'), icon: <Pencil size={14} aria-hidden="true" />, onSelect: () => openRename(item) },
            { id: 'move', label: t('move'), icon: <FolderInput size={14} aria-hidden="true" />, onSelect: () => openMove(item) },
            {
              id: 'delete',
              label: t('delete'),
              icon: <Trash2 size={14} aria-hidden="true" />,
              className: 'danger',
              onSelect: () => {
                if (!window.confirm(t('deleteConfirm', { name: item.name }))) return;
                void (async () => {
                  if (await onBeforeItemChange(item.path)) deleteMutation.mutate(item.path);
                })();
              },
            },
          ]}
        />
      </div>;
      })}
    </div>

    <Modal
      open={dialog.kind !== 'none'}
      title={dialog.kind === 'create-file' ? t('newFile') : dialog.kind === 'create-folder' ? t('newFolder') : dialog.kind === 'rename' ? t('rename') : t('move')}
      onClose={() => { if (!operation.isPending && !preparingOperation) setDialog({ kind: 'none' }); }}
      dismissible={!operation.isPending && !preparingOperation}
      size={dialog.kind === 'move' ? 'medium' : 'small'}
    >
      <form className="modal-body form-stack" aria-busy={operation.isPending || preparingOperation} onSubmit={(event) => { event.preventDefault(); void submitOperation(); }}>
        {dialog.kind !== 'move' && <label>{t('name')}<input data-modal-initial-focus name="item-name" autoComplete="off" value={name} maxLength={120} pattern=".*\S.*" title={t('name')} onChange={(event) => setName(event.target.value)} required /></label>}
        {dialog.kind === 'move' && folders.isPending ? <div className="sidebar-state" role="status">{t('loading')}</div> : null}
        {dialog.kind === 'move' && folders.isError ? <div className="sidebar-state error" role="alert">
          <p>{errorMessage(folders.error)}</p>
          <button type="button" className="button" onClick={() => void folders.refetch()}>{t('retry')}</button>
        </div> : null}
        {dialog.kind === 'move' && !folders.isPending && !folders.isError ? <div className="move-picker">
          <div className="picker-summary">
            <p>{t('chooseDestination')}</p>
            {destination !== null ? <output aria-live="polite">
              <span>{t('destination')}</span>
              <strong>/{destination || t('root')}</strong>
            </output> : null}
          </div>
          <LibraryTreePicker
            label={t('destination')}
            nodesByParent={moveTree}
            expandedPaths={moveExpandedPaths}
            selectedPaths={selectedMovePaths}
            selectableType="folder"
            loadingLabel={t('loading')}
            emptyLabel={t('noMoveDestinations')}
            retryLabel={t('retry')}
            initialFocusPath={destination ?? ''}
            getNodeState={moveNodeState}
            onToggleFolder={toggleMoveFolder}
            onSelect={(node) => setDestination(node.path)}
            onRetry={() => void folders.refetch()}
          />
          {validMoveDestinationCount === 0
            ? <p className="picker-inline-state" role="status">{t('noMoveDestinations')}</p>
            : null}
        </div> : null}
        <div className="modal-actions"><button type="button" className="button" disabled={operation.isPending || preparingOperation} onClick={() => setDialog({ kind: 'none' })}>{t('cancel')}</button><button
          type="submit"
          className="button button-primary"
          disabled={operation.isPending || preparingOperation || (dialog.kind === 'move' && (destination === null || folders.isPending || folders.isError))}
        >{operationIcon}{operation.isPending ? t('loading') : preparingOperation ? t('saving') : operationLabel}</button></div>
      </form>
    </Modal>
  </aside>;
}
