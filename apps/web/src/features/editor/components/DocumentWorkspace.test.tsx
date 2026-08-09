import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DocumentWorkspace } from './DocumentWorkspace';
import type { ReturnTypeOfWorkspace } from './types';

function workspace(overrides: Partial<ReturnTypeOfWorkspace> = {}): ReturnTypeOfWorkspace {
  return {
    source: 'Draft',
    setSource: vi.fn(),
    html: '',
    title: 'Guide.md',
    mode: 'preview',
    setMode: vi.fn(),
    dirty: true,
    loading: false,
    loadFailed: false,
    saving: false,
    error: '',
    saveError: '',
    conflict: null,
    continuingLocal: false,
    recoverableDraft: null,
    largeFile: false,
    save: vi.fn(),
    flushPendingSave: vi.fn(),
    refreshPreview: vi.fn(),
    reloadFromDisk: vi.fn(),
    refreshExternal: vi.fn(),
    keepLocal: vi.fn(),
    loadDiskVersion: vi.fn(),
    recoverLocalDraft: vi.fn(),
    ...overrides,
  };
}

describe('DocumentWorkspace semantics', () => {
  it('announces save state and associates the primary action with it', () => {
    render(<DocumentWorkspace
      workspace={workspace()}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    expect(screen.getByRole('heading', { name: 'Guide.md', level: 1 })).toBeInTheDocument();
    const status = screen.getByRole('status', { name: '' });
    expect(status).toHaveTextContent('Unsaved');
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-describedby', status.id);
  });

  it('keeps save failures visible and turns the primary action into an explicit retry', async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    render(<DocumentWorkspace
      workspace={workspace({ save, saveError: 'Storage is unavailable' })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    expect(screen.getByRole('status', { name: '' })).toHaveTextContent('Save failed');
    expect(screen.getByRole('alert')).toHaveTextContent('Storage is unavailable');
    await user.click(screen.getByRole('button', { name: 'Retry save' }));
    expect(save).toHaveBeenCalledOnce();
  });

  it('uses a page-level heading for the empty document state', () => {
    render(<DocumentWorkspace
      workspace={workspace({ title: '', source: '', dirty: false })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    expect(screen.getByRole('heading', { name: /Choose a document/, level: 1 })).toBeInTheDocument();
  });

  it('shows a failed document load with a retry action instead of stale editor content', async () => {
    const user = userEvent.setup();
    const reloadFromDisk = vi.fn();
    render(<DocumentWorkspace
      workspace={workspace({
        title: 'Other.md',
        source: '',
        dirty: false,
        loadFailed: true,
        error: 'The selected document is temporarily unavailable.',
        reloadFromDisk,
      })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    expect(screen.getByRole('heading', { name: 'Other.md', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('temporarily unavailable');
    expect(screen.queryByTestId('code-editor')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(reloadFromDisk).toHaveBeenCalledOnce();
  });

  it('keeps primary view and save controls visible while progressively disclosing disk actions', async () => {
    const user = userEvent.setup();
    const refreshPreview = vi.fn();
    const reloadFromDisk = vi.fn();
    render(<DocumentWorkspace
      workspace={workspace({ refreshPreview, reloadFromDisk })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    expect(screen.getByRole('button', { name: 'Preview' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Source' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Split' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Refresh current preview' })).not.toBeInTheDocument();

    const moreActions = screen.getByRole('button', { name: 'More actions' });
    await user.click(moreActions);
    await user.click(screen.getByRole('menuitem', { name: 'Refresh current preview' }));
    expect(refreshPreview).toHaveBeenCalledOnce();
    expect(moreActions).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    const reload = screen.getByRole('menuitem', { name: 'Reload from disk' });
    expect(screen.getByRole('menuitem', { name: 'Download Markdown' })).toHaveFocus();
    await user.click(reload);
    expect(reloadFromDisk).toHaveBeenCalledOnce();
  });

  it('downloads the current local Markdown buffer from the document actions', async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => 'blob:local-draft');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    render(<DocumentWorkspace
      workspace={workspace({ source: '# Latest local draft' })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    await user.click(screen.getByRole('button', { name: 'More actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Download Markdown' }));

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector('a[download="Guide.md"]')).not.toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:local-draft');
  });

  it('keeps the activated editor mounted while previewing so undo history survives mode changes', async () => {
    const { rerender } = render(<DocumentWorkspace
      workspace={workspace({ mode: 'source' })}
      dark={false}
      editorLineWrap={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);
    // The editor is intentionally code-split. Keep this assertion resilient when
    // the full suite is saturating the transform workers in CI.
    const editorHost = await screen.findByTestId('code-editor', {}, { timeout: 3_000 });
    const editorPane = editorHost.closest('.editor-pane');
    expect(editorPane).not.toHaveAttribute('hidden');

    rerender(<DocumentWorkspace
      workspace={workspace({ mode: 'preview' })}
      dark={false}
      editorLineWrap={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    expect(editorHost).toBeInTheDocument();
    expect(editorPane).toHaveAttribute('hidden');
    expect(editorPane).toHaveAttribute('inert');
  });

  it('describes an unresolved local-editing conflict without dismissing it', async () => {
    const user = userEvent.setup();
    const keepLocal = vi.fn();
    const loadDiskVersion = vi.fn();
    const conflict = {
      source: 'external' as const,
      diskSource: '# Disk revision',
      diskHtml: '<h1>Disk revision</h1>',
      diskVersion: 'v2',
    };
    const { rerender } = render(<DocumentWorkspace
      workspace={workspace({ conflict, keepLocal, loadDiskVersion })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    await user.click(screen.getByRole('button', { name: 'Continue editing' }));
    expect(keepLocal).toHaveBeenCalledOnce();

    rerender(<DocumentWorkspace
      workspace={workspace({ conflict, continuingLocal: true, keepLocal, loadDiskVersion })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);
    expect(screen.getByRole('alert')).toHaveTextContent('The conflict stays visible');
    expect(screen.queryByRole('button', { name: 'Continue editing' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Load disk version' }));
    expect(loadDiskVersion).toHaveBeenCalledOnce();
  });

  it('offers recovery for the most recently replaced local draft', async () => {
    const user = userEvent.setup();
    const recoverLocalDraft = vi.fn();
    render(<DocumentWorkspace
      workspace={workspace({
        recoverableDraft: { path: 'Guide.md', source: '# Local draft' },
        recoverLocalDraft,
      })}
      dark={false}
      splitRatio={0.5}
      onSplitRatioChange={vi.fn()}
    />);

    expect(screen.getByText('Local draft available')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Restore draft' }));
    expect(recoverLocalDraft).toHaveBeenCalledOnce();
  });
});
