import { useQueryClient } from '@tanstack/react-query';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';
import { server } from '@/test/mocks/server';
import { AttachmentPicker } from './AttachmentPicker';

function Harness() {
  const [selected, setSelected] = useState<string[]>([]);
  return <AttachmentPicker open selected={selected} limit={2} onChange={setSelected} onClose={vi.fn()} />;
}

describe('AttachmentPicker', () => {
  it('distinguishes request failures from empty folders and exposes selection state', async () => {
    let attempts = 0;
    server.use(http.get('http://localhost/api/v1/documents', () => {
      attempts += 1;
      if (attempts === 1) return HttpResponse.json({
        title: 'Library unavailable',
        detail: 'Try loading the folder again.',
        code: 'library_unavailable',
        status: 503,
      }, { status: 503 });
      return HttpResponse.json({
        success: true,
        current_path: '',
        items: [{ name: 'Guide.md', path: 'Guide.md', type: 'file', size: 42 }],
      });
    }));
    const user = userEvent.setup();
    renderApp(<Harness />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Try loading the folder again');
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    const tree = screen.getByRole('tree', { name: 'Choose attachments' });
    expect(tree).toHaveAttribute('aria-multiselectable', 'true');
    const guide = await screen.findByRole('treeitem', { name: 'Guide.md' });
    expect(guide).toHaveAttribute('aria-selected', 'false');
    await user.click(guide);
    expect(guide).toHaveAttribute('aria-selected', 'true');
  });

  it('commits multiple selections together, reserves the current-file slot, and discards dismissals', async () => {
    server.use(http.get('http://localhost/api/v1/documents', () => HttpResponse.json({
      success: true,
      current_path: '',
      items: [
        { name: 'Current.md', path: 'Current.md', type: 'file', size: 10 },
        { name: 'One.md', path: 'One.md', type: 'file', size: 10 },
        { name: 'Two.md', path: 'Two.md', type: 'file', size: 10 },
        { name: 'Three.md', path: 'Three.md', type: 'file', size: 10 },
      ],
    })));

    function BatchHarness() {
      const [open, setOpen] = useState(true);
      const [selected, setSelected] = useState<string[]>([]);
      return <>
        <button type="button" onClick={() => setOpen(true)}>Open picker</button>
        <output data-testid="committed">{selected.join('|')}</output>
        {open && <AttachmentPicker
          open
          selected={selected}
          reserved={['Current.md']}
          limit={3}
          onChange={setSelected}
          onClose={() => setOpen(false)}
        />}
      </>;
    }

    const user = userEvent.setup();
    renderApp(<BatchHarness />);
    const current = await screen.findByRole('treeitem', { name: 'Current.md' });
    expect(current).toHaveAttribute('aria-disabled', 'true');
    expect(current).toHaveAttribute('aria-selected', 'true');
    await user.click(screen.getByRole('treeitem', { name: 'One.md' }));
    await user.click(screen.getByRole('treeitem', { name: 'Two.md' }));
    expect(screen.getByTestId('committed')).toHaveTextContent(/^$/);
    expect(screen.getByText('3 selected · 3 maximum')).toBeInTheDocument();
    const overLimit = screen.getByRole('treeitem', { name: 'Three.md' });
    expect(overLimit).toHaveAttribute('aria-disabled', 'true');
    expect(overLimit).toHaveAccessibleDescription('Attach up to 3 files');
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(screen.getByTestId('committed')).toHaveTextContent('One.md|Two.md');

    await user.click(screen.getByRole('button', { name: 'Open picker' }));
    await user.click(await screen.findByRole('treeitem', { name: 'One.md' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByTestId('committed')).toHaveTextContent('One.md|Two.md');
  });

  it('expands folders in place, lazily loads children, and follows tree keyboard navigation', async () => {
    const requested: string[] = [];
    server.use(http.get('http://localhost/api/v1/documents', ({ request }) => {
      const path = new URL(request.url).searchParams.get('path') ?? '';
      requested.push(path);
      if (path === 'docs') {
        return HttpResponse.json({
          success: true,
          current_path: path,
          items: [{ name: 'Nested.md', path: 'docs/Nested.md', type: 'file', size: 12 }],
        });
      }
      return HttpResponse.json({
        success: true,
        current_path: '',
        items: [
          { name: 'docs', path: 'docs', type: 'folder' },
          { name: 'Root.md', path: 'Root.md', type: 'file', size: 12 },
        ],
      });
    }));
    const user = userEvent.setup();
    renderApp(<Harness />);

    const docs = await screen.findByRole('treeitem', { name: 'docs' });
    expect(docs).toHaveAttribute('aria-expanded', 'false');
    expect(requested).toEqual(['']);

    await user.click(docs);
    const nested = await screen.findByRole('treeitem', { name: 'Nested.md' });
    expect(docs).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('treeitem', { name: 'Root.md' })).toBeInTheDocument();
    expect(requested).toEqual(['', 'docs']);

    docs.focus();
    await user.keyboard('{ArrowRight}');
    expect(nested).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(docs).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(docs).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('treeitem', { name: 'Nested.md' })).not.toBeInTheDocument();
  });

  it('keeps a failed child folder in context and distinguishes retry from an empty folder', async () => {
    let nestedAttempts = 0;
    server.use(http.get('http://localhost/api/v1/documents', ({ request }) => {
      const path = new URL(request.url).searchParams.get('path') ?? '';
      if (!path) {
        return HttpResponse.json({
          success: true,
          current_path: '',
          items: [{ name: 'docs', path: 'docs', type: 'folder' }],
        });
      }
      nestedAttempts += 1;
      if (nestedAttempts === 1) {
        return HttpResponse.json({
          title: 'Folder unavailable',
          detail: 'Try this folder again.',
          code: 'folder_unavailable',
          status: 503,
        }, { status: 503 });
      }
      return HttpResponse.json({ success: true, current_path: path, items: [] });
    }));
    const user = userEvent.setup();
    renderApp(<Harness />);

    const docs = await screen.findByRole('treeitem', { name: 'docs' });
    await user.click(docs);
    expect(await screen.findByRole('alert')).toHaveTextContent('Try this folder again.');
    expect(docs).toHaveAttribute('aria-expanded', 'true');

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No attachable files')).toBeInTheDocument();
    expect(nestedAttempts).toBe(2);
  });

  it('refreshes an expanded folder when the shared library cache is invalidated', async () => {
    let nestedName = 'Before.md';
    let invalidateTree = () => Promise.resolve();
    server.use(http.get('http://localhost/api/v1/documents', ({ request }) => {
      const path = new URL(request.url).searchParams.get('path') ?? '';
      return HttpResponse.json({
        success: true,
        current_path: path,
        items: path === 'docs'
          ? [{ name: nestedName, path: `docs/${nestedName}`, type: 'file', size: 12 }]
          : [{ name: 'docs', path: 'docs', type: 'folder' }],
      });
    }));

    function InvalidatingHarness() {
      const queryClient = useQueryClient();
      invalidateTree = () => queryClient.invalidateQueries({ queryKey: ['library'] });
      return <AttachmentPicker open selected={[]} limit={3} onChange={vi.fn()} onClose={vi.fn()} />;
    }

    const user = userEvent.setup();
    renderApp(<InvalidatingHarness />);
    await user.click(await screen.findByRole('treeitem', { name: 'docs' }));
    expect(await screen.findByRole('treeitem', { name: 'Before.md' })).toBeInTheDocument();

    nestedName = 'After.md';
    await act(async () => { await invalidateTree(); });

    expect(await screen.findByRole('treeitem', { name: 'After.md' })).toBeInTheDocument();
    expect(screen.queryByRole('treeitem', { name: 'Before.md' })).not.toBeInTheDocument();
  });

  it('resynchronizes the draft and resets expansion when a mounted picker is reopened', async () => {
    server.use(http.get('http://localhost/api/v1/documents', ({ request }) => {
      const path = new URL(request.url).searchParams.get('path') ?? '';
      return HttpResponse.json({
        success: true,
        current_path: path,
        items: path ? [] : [
          { name: 'docs', path: 'docs', type: 'folder' },
          { name: 'One.md', path: 'One.md', type: 'file', size: 10 },
          { name: 'Two.md', path: 'Two.md', type: 'file', size: 10 },
        ],
      });
    }));

    function PersistentHarness() {
      const [open, setOpen] = useState(true);
      const [selected, setSelected] = useState(['One.md']);
      return <>
        <button type="button" onClick={() => setSelected(['Two.md'])}>Use external selection</button>
        <button type="button" onClick={() => setOpen(true)}>Open picker</button>
        <output data-testid="persistent-selection">{selected.join('|')}</output>
        <AttachmentPicker
          open={open}
          selected={selected}
          limit={3}
          onChange={setSelected}
          onClose={() => setOpen(false)}
        />
      </>;
    }

    const user = userEvent.setup();
    renderApp(<PersistentHarness />);
    const docs = await screen.findByRole('treeitem', { name: 'docs' });
    await user.click(docs);
    expect(docs).toHaveAttribute('aria-expanded', 'true');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('button', { name: 'Use external selection' }));
    await user.click(screen.getByRole('button', { name: 'Open picker' }));

    const reopenedDocs = await screen.findByRole('treeitem', { name: 'docs' });
    expect(reopenedDocs).toHaveAttribute('aria-expanded', 'false');
    await waitFor(() => {
      expect(screen.getByRole('treeitem', { name: 'One.md' })).toHaveAttribute('aria-selected', 'false');
      expect(screen.getByRole('treeitem', { name: 'Two.md' })).toHaveAttribute('aria-selected', 'true');
    });
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(screen.getByTestId('persistent-selection')).toHaveTextContent('Two.md');
  });
});
