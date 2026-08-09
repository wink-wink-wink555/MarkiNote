import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';
import { server } from '@/test/mocks/server';
import { uploadBatch } from '../model/uploadBatch';
import { LibrarySidebar } from './LibrarySidebar';

vi.mock('../model/uploadBatch', () => ({ uploadBatch: vi.fn() }));

const props = {
  currentPath: '',
  selectedFile: '',
  onPathChange: vi.fn(),
  onSelectFile: vi.fn(),
  onBeforeItemChange: vi.fn(() => true),
  onItemChanged: vi.fn(),
};

describe('LibrarySidebar upload lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(uploadBatch).mockReset();
  });

  it('prevents overlapping batches and restores controls after one final refresh', async () => {
    let finishUpload: ((result: { success: number; failed: number }) => void) | undefined;
    vi.mocked(uploadBatch).mockReturnValue(new Promise((resolve) => { finishUpload = resolve; }));
    const { container } = renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const firstFile = new File(['one'], 'one.md', { type: 'text/markdown' });

    fireEvent.change(input!, { target: { files: [firstFile] } });
    await waitFor(() => expect(uploadBatch).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
    expect(input).toBeDisabled();

    fireEvent.change(input!, { target: { files: [firstFile] } });
    expect(uploadBatch).toHaveBeenCalledTimes(1);
    finishUpload?.({ success: 1, failed: 0 });

    expect(await screen.findByText('1 files uploaded')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Add' })).toBeEnabled();
      expect(input).toBeEnabled();
    });
  });

  it('keeps the error feedback when a folder has no supported documents', async () => {
    const { container } = renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    const unsupported = new File(['metadata'], '.DS_Store');

    fireEvent.change(input!, { target: { files: [unsupported] } });

    expect(await screen.findByText('No supported files found (.md, .markdown, .txt)')).toBeInTheDocument();
    expect(uploadBatch).not.toHaveBeenCalled();
  });

  it('reports partial uploads as persistent error feedback with the failed count', async () => {
    vi.mocked(uploadBatch).mockResolvedValue({ success: 1, failed: 1 });
    const { container } = renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    const first = new File(['one'], 'one.md', { type: 'text/markdown' });
    const second = new File(['two'], 'two.md', { type: 'text/markdown' });

    fireEvent.change(input!, { target: { files: [first, second] } });

    expect(await screen.findByRole('alert')).toHaveTextContent('1 uploaded, 1 failed');
  });

  it('exposes the current document and a clear search recovery action', async () => {
    const user = userEvent.setup();
    renderApp(<LibrarySidebar {...props} selectedFile="Guide.md" />);

    const fileName = await screen.findByText('Guide.md');
    expect(fileName.closest('button')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('heading', { name: 'Library', level: 2 })).toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: 'Search all files and folders' }), 'missing');
    expect(await screen.findByText('No matching files or folders')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Clear search' })[0]!);

    expect(screen.getByRole('searchbox', { name: 'Search all files and folders' })).toHaveValue('');
    expect(screen.getByRole('searchbox', { name: 'Search all files and folders' })).toHaveFocus();
    expect(screen.getByText('Guide.md')).toBeInTheDocument();
  });

  it('searches the complete library and opens a nested result in its parent folder', async () => {
    const user = userEvent.setup();
    renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: 'Search all files and folders' }), 'nested');

    const nested = await screen.findByText('Nested Guide.md');
    expect(nested.closest('.file-copy')).toHaveTextContent('archive/Nested Guide.md');
    await user.click(nested);

    expect(props.onPathChange).toHaveBeenCalledWith('archive');
    expect(props.onSelectFile).toHaveBeenCalledWith('archive/Nested Guide.md');
    expect(screen.getByRole('searchbox', { name: 'Search all files and folders' })).toHaveValue('');
  });

  it('keeps search context intact when selecting a result is rejected', async () => {
    const user = userEvent.setup();
    const onPathChange = vi.fn();
    const onSelectFile = vi.fn(() => Promise.resolve(false));
    renderApp(<LibrarySidebar {...props} onPathChange={onPathChange} onSelectFile={onSelectFile} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();

    const search = screen.getByRole('searchbox', { name: 'Search all files and folders' });
    await user.type(search, 'nested');
    await user.click(await screen.findByText('Nested Guide.md'));

    await waitFor(() => expect(onSelectFile).toHaveBeenCalledWith('archive/Nested Guide.md'));
    expect(search).toHaveValue('nested');
    expect(onPathChange).not.toHaveBeenCalled();
    expect(screen.getByText('Nested Guide.md')).toBeInTheDocument();
  });

  it('announces listing failures as alerts with a retry action', async () => {
    server.use(http.get('http://localhost/api/v1/documents', () => HttpResponse.json({
      type: 'about:blank',
      title: 'Unavailable',
      status: 503,
      detail: 'Library is temporarily unavailable.',
      code: 'library_unavailable',
    }, { status: 503 })));

    renderApp(<LibrarySidebar {...props} />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Library is temporarily unavailable');
    expect(alert).toContainElement(screen.getByRole('button', { name: 'Retry' }));
  });

  it('opens row actions in a keyboard menu and restores focus on Escape', async () => {
    const user = userEvent.setup();
    renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    const trigger = screen.getByRole('button', { name: 'Guide.md — More actions' });

    trigger.focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menu')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Rename' })).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Move' })).toHaveFocus();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('excludes the current parent from move targets and requires an explicit destination', async () => {
    const user = userEvent.setup();
    renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Guide.md — More actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Move' }));

    const dialog = screen.getByRole('dialog', { name: 'Move' });
    const tree = await within(dialog).findByRole('tree', { name: 'Destination' });
    const root = within(tree).getByRole('treeitem', { name: 'Root' });
    const docs = within(tree).getByRole('treeitem', { name: 'docs' });
    expect(root).not.toHaveAttribute('aria-disabled');
    expect(root).toHaveAccessibleDescription('This item is already in this folder');
    expect(docs).toHaveAttribute('aria-selected', 'false');
    expect(within(dialog).getByRole('button', { name: 'Move' })).toBeDisabled();

    await user.click(docs);
    expect(docs).toHaveAttribute('aria-selected', 'true');
    expect(within(dialog).getByText('/docs')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Move' })).toBeEnabled();
  });

  it('keeps a source folder and its descendants visible for explanation but never selectable', async () => {
    server.use(http.get('http://localhost/api/v1/documents/folders', () => HttpResponse.json({
      success: true,
      folders: [
        { path: '', name: 'Root', level: 0 },
        { path: 'docs', name: 'docs', level: 1 },
        { path: 'docs/archive', name: 'archive', level: 2 },
        { path: 'other', name: 'other', level: 1 },
      ],
    })));
    const user = userEvent.setup();
    renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('docs')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'docs — More actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Move' }));
    const dialog = screen.getByRole('dialog', { name: 'Move' });
    const tree = await within(dialog).findByRole('tree', { name: 'Destination' });
    const source = within(tree).getByRole('treeitem', { name: 'docs' });

    expect(source).not.toHaveAttribute('aria-disabled');
    expect(source).toHaveAccessibleDescription('A folder cannot be moved into itself or one of its subfolders');
    await user.click(source);
    const descendant = within(tree).getByRole('treeitem', { name: 'archive' });
    expect(source).toHaveAttribute('aria-expanded', 'true');
    expect(descendant).toHaveAttribute('aria-disabled', 'true');
    expect(descendant).toHaveAccessibleDescription('A folder cannot be moved into itself or one of its subfolders');
    expect(within(dialog).getByRole('button', { name: 'Move' })).toBeDisabled();

    await user.click(within(tree).getByRole('treeitem', { name: 'other' }));
    expect(within(dialog).getByRole('button', { name: 'Move' })).toBeEnabled();
  });

  it('keeps move confirmation unavailable when destinations cannot be loaded', async () => {
    const user = userEvent.setup();
    server.use(http.get('http://localhost/api/v1/documents/folders', () => HttpResponse.json({
      type: 'about:blank',
      title: 'Unavailable',
      status: 503,
      detail: 'Destinations are temporarily unavailable.',
      code: 'library_unavailable',
    }, { status: 503 })));
    renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Guide.md — More actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Move' }));

    const dialog = screen.getByRole('dialog', { name: 'Move' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Destinations are temporarily unavailable.');
    expect(within(dialog).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Move' })).toBeDisabled();
  });

  it('waits for the latest draft to flush before moving the selected item', async () => {
    let releaseFlush: (saved: boolean) => void = () => undefined;
    const flushGate = new Promise<boolean>((resolve) => { releaseFlush = resolve; });
    const onBeforeItemChange = vi.fn(() => flushGate);
    let moveRequests = 0;
    server.use(http.post('http://localhost/api/v1/documents/move', async ({ request }) => {
      moveRequests += 1;
      const body = await request.json() as { source: string; target: string };
      return HttpResponse.json({
        success: true,
        old_path: body.source,
        new_path: `${body.target}/Guide.md`,
      });
    }));
    const user = userEvent.setup();
    renderApp(<LibrarySidebar {...props} selectedFile="Guide.md" onBeforeItemChange={onBeforeItemChange} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Guide.md — More actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Move' }));
    const dialog = screen.getByRole('dialog', { name: 'Move' });
    await user.click(await within(dialog).findByRole('treeitem', { name: 'docs' }));
    await user.click(within(dialog).getByRole('button', { name: 'Move' }));

    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Saving…' })).toBeDisabled());
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Close' })).toBeDisabled();
    expect(moveRequests).toBe(0);

    releaseFlush(true);
    await waitFor(() => expect(moveRequests).toBe(1));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Move' })).not.toBeInTheDocument());
    expect(onBeforeItemChange).toHaveBeenCalledWith('Guide.md');
  });

  it('cannot dismiss an in-flight library mutation with Escape, backdrop, or close controls', async () => {
    const user = userEvent.setup();
    let finishRequest: (() => void) | undefined;
    const pendingRequest = new Promise<void>((resolve) => { finishRequest = resolve; });
    server.use(http.post('http://localhost/api/v1/documents/files', async () => {
      await pendingRequest;
      return HttpResponse.json({
        success: true,
        file_name: 'Draft.md',
        path: 'Draft.md',
        size: 0,
        version: 'v1',
      });
    }));
    renderApp(<LibrarySidebar {...props} />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.click(screen.getByRole('menuitem', { name: 'New file' }));
    const dialog = screen.getByRole('dialog', { name: 'New file' });
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Draft');
    await user.click(screen.getByRole('button', { name: 'New file' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Loading…' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    await user.keyboard('{Escape}');
    fireEvent.mouseDown(document.querySelector('.modal-backdrop')!);
    expect(dialog).toBeInTheDocument();

    finishRequest?.();
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'New file' })).not.toBeInTheDocument());
  });
});
