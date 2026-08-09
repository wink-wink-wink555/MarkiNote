import { describe, expect, it } from 'vitest';
import type { LibraryItem } from '@/shared/api';
import {
  buildFolderTree,
  initiallyExpandedMovePaths,
  LIBRARY_TREE_ROOT,
  moveTargetRestriction,
} from './libraryTree';

describe('libraryTree model', () => {
  it('builds a nested folder map around a selectable virtual root', () => {
    const tree = buildFolderTree([
      { path: '', name: 'Server root', level: 0 },
      { path: 'docs', name: 'docs', level: 1 },
      { path: 'docs/archive', name: 'archive', level: 2 },
      { path: 'assets', name: 'assets', level: 1 },
    ], 'Root');

    expect(tree.get(LIBRARY_TREE_ROOT)?.map((node) => node.path)).toEqual(['']);
    expect(tree.get('')?.map((node) => node.path)).toEqual(['assets', 'docs']);
    expect(tree.get('docs')?.map((node) => node.path)).toEqual(['docs/archive']);
    expect(tree.get('')?.find((node) => node.path === 'docs')?.expandable).toBe(true);
  });

  it('classifies every unsafe move target and expands the source ancestry', () => {
    const folder: LibraryItem = { name: 'notes', path: 'projects/notes', type: 'folder' };
    const file: LibraryItem = { name: 'Readme.md', path: 'projects/Readme.md', type: 'file' };

    expect(moveTargetRestriction(folder, 'projects')).toBe('current-parent');
    expect(moveTargetRestriction(folder, 'projects/notes')).toBe('self-or-descendant');
    expect(moveTargetRestriction(folder, 'projects/notes/archive')).toBe('self-or-descendant');
    expect(moveTargetRestriction(folder, 'projects/other')).toBeNull();
    expect(moveTargetRestriction(file, 'projects')).toBe('current-parent');
    expect(moveTargetRestriction(file, 'projects/notes')).toBeNull();
    expect([...initiallyExpandedMovePaths('projects/notes/Draft.md')]).toEqual([
      '',
      'projects',
      'projects/notes',
    ]);
  });
});
