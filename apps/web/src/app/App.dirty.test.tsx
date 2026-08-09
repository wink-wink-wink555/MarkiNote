import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';

const { flushPendingSave } = vi.hoisted(() => ({
  flushPendingSave: vi.fn(() => Promise.resolve(false)),
}));

vi.mock('@/features/editor/model/useDocumentWorkspace', () => ({
  useDocumentWorkspace: (path: string) => ({
    source: '# Local draft', setSource: vi.fn(), html: '', title: path, mode: 'preview' as const, setMode: vi.fn(), dirty: Boolean(path), loading: false, saving: false, error: '', conflict: null, largeFile: false,
    save: vi.fn(), flushPendingSave, refreshPreview: vi.fn(), reloadFromDisk: vi.fn(), refreshExternal: vi.fn(), keepLocal: vi.fn(), loadDiskVersion: vi.fn(),
  }),
}));

import { App } from './App';

describe('App dirty-document guard', () => {
  beforeEach(() => {
    flushPendingSave.mockReset();
    flushPendingSave.mockResolvedValue(false);
  });

  it('keeps the current document selected when discarding is rejected', async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    await user.click((await screen.findAllByText('Guide.md'))[0]!);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);

    await user.click(screen.getByText('Other.md'));

    await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    expect(screen.getAllByText('Guide.md')[0]!.closest('.file-row')).toHaveClass('selected');
    expect(screen.getByText('Other.md').closest('.file-row')).not.toHaveClass('selected');
  });

  it('flushes the latest draft before selecting another document', async () => {
    flushPendingSave.mockResolvedValue(true);
    const user = userEvent.setup();
    renderApp(<App />);
    await user.click((await screen.findAllByText('Guide.md'))[0]!);
    const confirm = vi.spyOn(window, 'confirm');

    await user.click(screen.getByText('Other.md'));

    await waitFor(() => expect(screen.getAllByText('Other.md')[0]!.closest('.file-row')).toHaveClass('selected'));
    expect(flushPendingSave).toHaveBeenCalledOnce();
    expect(confirm).not.toHaveBeenCalled();
  });

  it('applies reading and editor preferences immediately and persists the V2 schema', async () => {
    const user = userEvent.setup();
    renderApp(<App />);

    await user.click(await screen.findByRole('button', { name: 'Settings' }));
    fireEvent.change(screen.getByLabelText('Body font size'), { target: { value: '18' } });
    fireEvent.change(screen.getByLabelText('Editor font size'), { target: { value: '16' } });
    await user.click(within(screen.getByRole('group', { name: 'Body line height' })).getByRole('radio', { name: 'Relaxed' }));
    await user.click(screen.getByRole('radio', { name: 'Wide' }));
    await user.click(within(screen.getByRole('group', { name: 'Interface density' })).getByRole('radio', { name: 'Compact' }));
    await user.click(screen.getByRole('checkbox', { name: /Wrap long lines/i }));

    expect(document.documentElement).toHaveAttribute('data-density', 'compact');
    expect(document.documentElement.style.getPropertyValue('--reading-font-size')).toBe('18px');
    expect(document.documentElement.style.getPropertyValue('--editor-font-size')).toBe('16px');
    expect(document.documentElement.style.getPropertyValue('--reading-width')).toBe('86ch');

    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    const stored = JSON.parse(localStorage.getItem('markinote.preferences.v2') ?? '{}') as Record<string, unknown>;
    expect(stored).toMatchObject({
      version: 2,
      readingFontSize: 18,
      editorFontSize: 16,
      readingLineHeight: 1.78,
      readingWidth: 86,
      density: 'compact',
      editorLineWrap: false,
    });
  });
});
