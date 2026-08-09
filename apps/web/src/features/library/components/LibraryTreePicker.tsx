import { Check, ChevronRight, FileText, Folder, FolderOpen } from 'lucide-react';
import { type CSSProperties, type KeyboardEvent, useId, useMemo, useState } from 'react';
import {
  LIBRARY_TREE_ROOT,
  type LibraryTree,
  type LibraryTreeNode,
} from '../model/libraryTree';

export interface LibraryTreeNodeState {
  disabled?: boolean;
  reason?: string;
  note?: string;
}

interface Props {
  label: string;
  nodesByParent: LibraryTree;
  expandedPaths: ReadonlySet<string>;
  selectedPaths: ReadonlySet<string>;
  selectableType: LibraryTreeNode['type'];
  multiple?: boolean;
  loadingLabel: string;
  emptyLabel: string;
  retryLabel: string;
  loadingPaths?: ReadonlySet<string>;
  errorsByPath?: ReadonlyMap<string, string>;
  rootLoading?: boolean;
  rootError?: string;
  initialFocusPath?: string;
  getNodeState?: (node: LibraryTreeNode) => LibraryTreeNodeState;
  onToggleFolder: (path: string) => void;
  onSelect: (node: LibraryTreeNode) => void;
  onRetry: (path: string) => void;
}

interface VisibleNode {
  node: LibraryTreeNode;
  level: number;
  position: number;
  setSize: number;
}

const EMPTY_PATHS = new Set<string>();
const EMPTY_ERRORS = new Map<string, string>();

function flattenVisibleNodes(nodesByParent: LibraryTree, expandedPaths: ReadonlySet<string>): VisibleNode[] {
  const visible: VisibleNode[] = [];
  const visit = (parentPath: string, level: number) => {
    const children = nodesByParent.get(parentPath) ?? [];
    children.forEach((node, index) => {
      visible.push({ node, level, position: index + 1, setSize: children.length });
      if (node.type === 'folder' && expandedPaths.has(node.path)) visit(node.path, level + 1);
    });
  };
  visit(LIBRARY_TREE_ROOT, 1);
  return visible;
}

function focusTreeItem(tree: HTMLElement, path: string): void {
  const item = [...tree.querySelectorAll<HTMLElement>('[role="treeitem"]')]
    .find((candidate) => candidate.dataset.treePath === path);
  item?.focus();
}

export function LibraryTreePicker({
  label,
  nodesByParent,
  expandedPaths,
  selectedPaths,
  selectableType,
  multiple = false,
  loadingLabel,
  emptyLabel,
  retryLabel,
  loadingPaths = EMPTY_PATHS,
  errorsByPath = EMPTY_ERRORS,
  rootLoading = false,
  rootError,
  initialFocusPath,
  getNodeState,
  onToggleFolder,
  onSelect,
  onRetry,
}: Props) {
  const descriptionPrefix = useId();
  const [activePath, setActivePath] = useState<string | null>(null);
  const visibleNodes = useMemo(
    () => flattenVisibleNodes(nodesByParent, expandedPaths),
    [expandedPaths, nodesByParent],
  );
  const visiblePaths = useMemo(
    () => new Set(visibleNodes.map(({ node }) => node.path)),
    [visibleNodes],
  );
  const selectedFallback = visibleNodes.find(({ node }) => selectedPaths.has(node.path))?.node.path;
  const firstPath = visibleNodes[0]?.node.path;
  const tabStopPath = activePath !== null && visiblePaths.has(activePath)
    ? activePath
    : initialFocusPath !== undefined && visiblePaths.has(initialFocusPath)
      ? initialFocusPath
      : selectedFallback ?? firstPath;

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, current: VisibleNode) => {
    const index = visibleNodes.findIndex(({ node }) => node.path === current.node.path);
    if (index < 0) return;
    const tree = event.currentTarget.closest<HTMLElement>('[role="tree"]');
    if (!tree) return;

    let nextPath: string | undefined;
    if (event.key === 'ArrowDown') nextPath = visibleNodes[index + 1]?.node.path;
    if (event.key === 'ArrowUp') nextPath = visibleNodes[index - 1]?.node.path;
    if (event.key === 'Home') nextPath = visibleNodes[0]?.node.path;
    if (event.key === 'End') nextPath = visibleNodes.at(-1)?.node.path;
    if (event.key === 'ArrowRight' && current.node.type === 'folder' && current.node.expandable) {
      if (!expandedPaths.has(current.node.path)) {
        event.preventDefault();
        onToggleFolder(current.node.path);
        return;
      }
      const child = visibleNodes[index + 1];
      if (child && child.level > current.level) nextPath = child.node.path;
    }
    if (event.key === 'ArrowLeft') {
      if (current.node.type === 'folder' && current.node.expandable && expandedPaths.has(current.node.path)) {
        event.preventDefault();
        onToggleFolder(current.node.path);
        return;
      }
      if (current.node.parentPath !== LIBRARY_TREE_ROOT) nextPath = current.node.parentPath;
    }
    if (nextPath === undefined) return;
    event.preventDefault();
    setActivePath(nextPath);
    focusTreeItem(tree, nextPath);
  };

  if (rootLoading) {
    return <div className="picker-tree-loading" role="status" aria-label={loadingLabel}>
      <span>{loadingLabel}</span>
      <span className="picker-tree-skeleton" aria-hidden="true" />
      <span className="picker-tree-skeleton short" aria-hidden="true" />
      <span className="picker-tree-skeleton" aria-hidden="true" />
    </div>;
  }
  if (rootError) {
    return <div className="picker-tree-state error" role="alert">
      <p>{rootError}</p>
      <button type="button" className="button button-small" onClick={() => onRetry(LIBRARY_TREE_ROOT)}>{retryLabel}</button>
    </div>;
  }
  if (!visibleNodes.length) {
    return <div className="picker-tree-state" role="status">{emptyLabel}</div>;
  }

  return <div
    className="picker-tree"
    role="tree"
    aria-label={label}
    aria-multiselectable={multiple || undefined}
  >
    {visibleNodes.map((entry, visibleIndex) => {
      const { node } = entry;
      const expanded = node.type === 'folder' && expandedPaths.has(node.path);
      const selectable = node.type === selectableType;
      const selected = selectable && selectedPaths.has(node.path);
      const state = getNodeState?.(node) ?? {};
      const noteId = state.note ? `${descriptionPrefix}-note-${visibleIndex}` : undefined;
      const selectionOnlyDisabled = Boolean(
        state.disabled && node.type === 'folder' && node.expandable,
      );
      const children = nodesByParent.get(node.path);
      const loading = expanded && loadingPaths.has(node.path);
      const error = expanded ? errorsByPath.get(node.path) : undefined;
      const empty = expanded && !loading && !error && children !== undefined && children.length === 0;
      return <div
        className="picker-tree-entry"
        role="none"
        key={`${node.type}:${node.path || 'root'}`}
        style={{ '--tree-depth': entry.level - 1 } as CSSProperties}
      >
        <button
          type="button"
          role="treeitem"
          className={`picker-tree-row ${selected ? 'selected' : ''} ${state.disabled ? 'disabled' : ''}`}
          data-tree-path={node.path}
          data-modal-initial-focus={node.path === tabStopPath ? '' : undefined}
          tabIndex={node.path === tabStopPath ? 0 : -1}
          aria-level={entry.level}
          aria-posinset={entry.position}
          aria-setsize={entry.setSize}
          aria-expanded={node.type === 'folder' && node.expandable ? expanded : undefined}
          aria-selected={selectable ? selected : undefined}
          aria-disabled={state.disabled && !selectionOnlyDisabled ? true : undefined}
          aria-label={node.name}
          aria-describedby={noteId}
          title={state.reason}
          onFocus={() => setActivePath(node.path)}
          onKeyDown={(event) => handleKeyDown(event, entry)}
          onClick={() => {
            setActivePath(node.path);
            if (selectable && !state.disabled) onSelect(node);
            if (node.type === 'folder' && node.expandable) onToggleFolder(node.path);
          }}
        >
          <span className={`picker-tree-disclosure ${expanded ? 'expanded' : ''}`} aria-hidden="true">
            {node.type === 'folder' && node.expandable ? <ChevronRight size={15} /> : null}
          </span>
          <span className={`picker-tree-icon ${node.type}`} aria-hidden="true">
            {node.type === 'folder'
              ? expanded ? <FolderOpen size={17} /> : <Folder size={17} />
              : <FileText size={17} />}
          </span>
          <span className="picker-tree-copy">
            <span>{node.name}</span>
            {state.note ? <small id={noteId}>{state.note}</small> : null}
          </span>
          {selected ? <span className="picker-tree-check" aria-hidden="true"><Check size={15} /></span> : null}
        </button>
        {loading ? <div className="picker-tree-child-state" role="status">{loadingLabel}</div> : null}
        {error ? <div className="picker-tree-child-state error" role="alert">
          <span>{error}</span>
          <button type="button" className="button button-small" onClick={() => onRetry(node.path)}>{retryLabel}</button>
        </div> : null}
        {empty ? <div className="picker-tree-child-state" role="status">{emptyLabel}</div> : null}
      </div>;
    })}
  </div>;
}
