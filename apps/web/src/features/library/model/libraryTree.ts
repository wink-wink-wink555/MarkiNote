import type { FolderOption, LibraryItem } from '@/shared/api';
import { dirname } from '@/shared/lib/format';

export const LIBRARY_TREE_ROOT = '\u0000';

export interface LibraryTreeNode {
  name: string;
  path: string;
  type: LibraryItem['type'];
  parentPath: string;
  expandable: boolean;
}

export type LibraryTree = ReadonlyMap<string, readonly LibraryTreeNode[]>;

export type MoveTargetRestriction = 'current-parent' | 'self-or-descendant';

function sortNodes(nodes: LibraryTreeNode[]): LibraryTreeNode[] {
  return nodes.sort((left, right) => {
    if (left.type !== right.type) return left.type === 'folder' ? -1 : 1;
    return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
  });
}

export function directoryItemsToTreeNodes(parentPath: string, items: readonly LibraryItem[]): LibraryTreeNode[] {
  return sortNodes(items.map((item) => ({
    name: item.name,
    path: item.path,
    type: item.type,
    parentPath,
    expandable: item.type === 'folder',
  })));
}

export function buildFolderTree(folders: readonly FolderOption[], rootName: string): LibraryTree {
  const normalized = folders.some((folder) => folder.path === '')
    ? folders
    : [{ path: '', name: rootName, level: 0 }, ...folders];
  const children = new Map<string, LibraryTreeNode[]>();

  normalized.forEach((folder) => {
    const parentPath = folder.path === '' ? LIBRARY_TREE_ROOT : dirname(folder.path);
    const siblings = children.get(parentPath) ?? [];
    siblings.push({
      name: folder.path === '' ? rootName : folder.name,
      path: folder.path,
      type: 'folder',
      parentPath,
      expandable: false,
    });
    children.set(parentPath, siblings);
  });

  children.forEach((nodes, parentPath) => {
    const sorted = sortNodes(nodes);
    children.set(parentPath, sorted.map((node) => ({
      ...node,
      expandable: children.has(node.path),
    })));
  });

  return children;
}

export function moveTargetRestriction(source: LibraryItem, targetPath: string): MoveTargetRestriction | null {
  if (targetPath === dirname(source.path)) return 'current-parent';
  if (
    source.type === 'folder'
    && (targetPath === source.path || targetPath.startsWith(`${source.path}/`))
  ) return 'self-or-descendant';
  return null;
}

export function initiallyExpandedMovePaths(sourcePath: string): Set<string> {
  const expanded = new Set<string>(['']);
  const parent = dirname(sourcePath);
  if (!parent) return expanded;

  const parts = parent.split('/');
  for (let index = 0; index < parts.length; index += 1) {
    expanded.add(parts.slice(0, index + 1).join('/'));
  }
  return expanded;
}
