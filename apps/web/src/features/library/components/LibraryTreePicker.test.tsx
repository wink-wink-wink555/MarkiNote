import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';
import {
  LIBRARY_TREE_ROOT,
  type LibraryTreeNode,
} from '../model/libraryTree';
import { LibraryTreePicker } from './LibraryTreePicker';

const folder: LibraryTreeNode = {
  name: 'docs',
  path: 'docs',
  type: 'folder',
  parentPath: LIBRARY_TREE_ROOT,
  expandable: true,
};
const nestedFile: LibraryTreeNode = {
  name: 'Nested.md',
  path: 'docs/Nested.md',
  type: 'file',
  parentPath: 'docs',
  expandable: false,
};
const rootFile: LibraryTreeNode = {
  name: 'Root.md',
  path: 'Root.md',
  type: 'file',
  parentPath: LIBRARY_TREE_ROOT,
  expandable: false,
};
const tree = new Map([
  [LIBRARY_TREE_ROOT, [folder, rootFile]],
  ['docs', [nestedFile]],
]);

function Harness() {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['docs']));
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  return <LibraryTreePicker
    label="Documents"
    nodesByParent={tree}
    expandedPaths={expanded}
    selectedPaths={selected}
    selectableType="file"
    multiple
    loadingLabel="Loading"
    emptyLabel="Empty"
    retryLabel="Retry"
    onToggleFolder={(path) => setExpanded((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    })}
    onSelect={(node) => setSelected((current) => new Set(current).add(node.path))}
    onRetry={vi.fn()}
  />;
}

describe('LibraryTreePicker', () => {
  it('exposes hierarchy and uses roving focus for the complete tree keyboard pattern', async () => {
    const user = userEvent.setup();
    renderApp(<Harness />);
    const docs = screen.getByRole('treeitem', { name: 'docs' });
    const nested = screen.getByRole('treeitem', { name: 'Nested.md' });
    const root = screen.getByRole('treeitem', { name: 'Root.md' });

    expect(screen.getByRole('tree', { name: 'Documents' })).toHaveAttribute('aria-multiselectable', 'true');
    expect(docs).toHaveAttribute('aria-level', '1');
    expect(nested).toHaveAttribute('aria-level', '2');
    expect(root).toHaveAttribute('aria-level', '1');
    expect(docs).toHaveAttribute('tabindex', '0');
    expect(nested).toHaveAttribute('tabindex', '-1');

    docs.focus();
    await user.keyboard('{ArrowDown}');
    expect(nested).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(root).toHaveFocus();
    await user.keyboard('{Home}');
    expect(docs).toHaveFocus();
    await user.keyboard('{End}');
    expect(root).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(nested).toHaveFocus();

    await user.click(nested);
    expect(nested).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{ArrowLeft}');
    expect(docs).toHaveFocus();
  });
});
