import { act, renderHook, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { PropsWithChildren } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/shared/ui/Toast';
import { server } from '@/test/mocks/server';
import { useDocumentWorkspace } from './useDocumentWorkspace';

function wrapper({ children }: PropsWithChildren) {
  return <ToastProvider>{children}</ToastProvider>;
}

describe('useDocumentWorkspace', () => {
  it('refreshes the preview from the local buffer and guards disk reloads', async () => {
    const confirmDiscard = vi.fn(() => false);
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md', { confirmDiscard }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Unsaved local draft'));
    await act(async () => result.current.refreshPreview());
    expect(result.current.source).toBe('# Unsaved local draft');
    expect(result.current.dirty).toBe(true);

    await act(async () => result.current.reloadFromDisk());
    expect(confirmDiscard).toHaveBeenCalledOnce();
    expect(result.current.source).toBe('# Unsaved local draft');
  });

  it('keeps conflicts visible, confirms disk replacement, and restores the replaced draft', async () => {
    const confirmDiscard = vi.fn(() => false);
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md', { confirmDiscard }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Local draft'));
    server.use(http.get('http://localhost/api/v1/documents/content', () => HttpResponse.json({
      path: 'Guide.md',
      filename: 'Guide.md',
      content: '# Disk revision',
      size: 15,
      modified: '2026-01-04T12:00:00',
      version: 'v2',
    })));

    await act(async () => result.current.refreshExternal());
    expect(result.current.conflict?.diskSource).toBe('# Disk revision');

    act(() => result.current.keepLocal());
    expect(result.current.continuingLocal).toBe(true);
    expect(result.current.conflict).not.toBeNull();

    let loaded = true;
    act(() => { loaded = result.current.loadDiskVersion(); });
    expect(loaded).toBe(false);
    expect(confirmDiscard).toHaveBeenCalledOnce();
    expect(result.current.source).toBe('# Local draft');
    expect(result.current.conflict).not.toBeNull();

    confirmDiscard.mockReturnValue(true);
    act(() => { loaded = result.current.loadDiskVersion(); });
    expect(loaded).toBe(true);
    expect(result.current.source).toBe('# Disk revision');
    expect(result.current.conflict).toBeNull();
    expect(result.current.recoverableDraft?.source).toBe('# Local draft');

    await act(async () => result.current.recoverLocalDraft());
    expect(result.current.source).toBe('# Local draft');
    expect(result.current.dirty).toBe(true);
    expect(result.current.recoverableDraft).toBeNull();
  });

  it('uses the persistent save status instead of duplicating success in a toast', async () => {
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Updated'));
    await act(async () => result.current.save());

    expect(result.current.dirty).toBe(false);
    expect(screen.queryByText('Saved')).not.toBeInTheDocument();
  });

  it('automatically saves the latest buffer after a short idle period', async () => {
    const savedBodies: Array<Record<string, unknown>> = [];
    server.use(http.put('http://localhost/api/v1/documents/content', async ({ request }) => {
      savedBodies.push(await request.json() as Record<string, unknown>);
      return HttpResponse.json({ success: true, version: 'v2' });
    }));
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Automatically saved'));
    expect(result.current.dirty).toBe(true);

    await waitFor(() => expect(savedBodies).toHaveLength(1), { timeout: 2_000 });
    await waitFor(() => expect(result.current.dirty).toBe(false));
    expect(savedBodies[0]).toMatchObject({
      content: '# Automatically saved',
      expectedVersion: 'v1',
    });
  });

  it('serializes saves and drains text entered while a write is in flight', async () => {
    const savedBodies: Array<Record<string, unknown>> = [];
    let releaseFirstRequest: () => void = () => undefined;
    let markFirstRequestStarted: () => void = () => undefined;
    const firstRequestStarted = new Promise<void>((resolve) => { markFirstRequestStarted = resolve; });
    const firstRequestGate = new Promise<void>((resolve) => { releaseFirstRequest = resolve; });
    server.use(http.put('http://localhost/api/v1/documents/content', async ({ request }) => {
      const body = await request.json() as Record<string, unknown>;
      savedBodies.push(body);
      if (savedBodies.length === 1) {
        markFirstRequestStarted();
        await firstRequestGate;
      }
      return HttpResponse.json({ success: true, version: savedBodies.length === 1 ? 'v2' : 'v3' });
    }));
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# First queued version'));
    let firstSave: Promise<boolean> = Promise.resolve(false);
    act(() => { firstSave = result.current.save(); });
    await firstRequestStarted;

    act(() => result.current.setSource('# Newest version while saving'));
    let flush: Promise<boolean> = Promise.resolve(false);
    act(() => { flush = result.current.flushPendingSave(); });
    expect(savedBodies).toHaveLength(1);

    releaseFirstRequest();
    let outcomes: boolean[] = [];
    await act(async () => {
      outcomes = await Promise.all([firstSave, flush]);
    });

    expect(outcomes).toEqual([true, true]);
    expect(savedBodies).toEqual([
      expect.objectContaining({ content: '# First queued version', expectedVersion: 'v1' }),
      expect.objectContaining({ content: '# Newest version while saving', expectedVersion: 'v2' }),
    ]);
    expect(result.current.source).toBe('# Newest version while saving');
    expect(result.current.dirty).toBe(false);
    expect(result.current.saving).toBe(false);
  });

  it('waits for a compensating save when editing returns to persisted text during an in-flight write', async () => {
    const original = '# Guide\n\nWelcome to **MarkiNote**.';
    const savedBodies: Array<Record<string, unknown>> = [];
    let releaseFirstRequest: () => void = () => undefined;
    let markFirstRequestStarted: () => void = () => undefined;
    const firstRequestStarted = new Promise<void>((resolve) => { markFirstRequestStarted = resolve; });
    const firstRequestGate = new Promise<void>((resolve) => { releaseFirstRequest = resolve; });
    server.use(http.put('http://localhost/api/v1/documents/content', async ({ request }) => {
      const body = await request.json() as Record<string, unknown>;
      savedBodies.push(body);
      if (savedBodies.length === 1) {
        markFirstRequestStarted();
        await firstRequestGate;
      }
      return HttpResponse.json({ success: true, version: savedBodies.length === 1 ? 'v2' : 'v3' });
    }));
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Temporary in-flight text'));
    act(() => { void result.current.save(); });
    await firstRequestStarted;

    act(() => result.current.setSource(original));
    expect(result.current.dirty).toBe(false);
    expect(result.current.saving).toBe(true);
    let flushSettled = false;
    let flush: Promise<boolean> = Promise.resolve(false);
    act(() => {
      flush = result.current.flushPendingSave().then((saved) => {
        flushSettled = true;
        return saved;
      });
    });
    await Promise.resolve();
    expect(flushSettled).toBe(false);

    releaseFirstRequest();
    let saved = false;
    await act(async () => { saved = await flush; });

    expect(saved).toBe(true);
    expect(savedBodies).toEqual([
      expect.objectContaining({ content: '# Temporary in-flight text', expectedVersion: 'v1' }),
      expect.objectContaining({ content: original, expectedVersion: 'v2' }),
    ]);
    expect(result.current.dirty).toBe(false);
    expect(result.current.saving).toBe(false);
  });

  it('keeps a failed draft dirty, avoids retry loops, and supports an explicit flush retry', async () => {
    let attempts = 0;
    server.use(http.put('http://localhost/api/v1/documents/content', () => {
      attempts += 1;
      return HttpResponse.json({ detail: 'Storage is unavailable' }, { status: 503 });
    }));
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Preserved after failure'));
    let firstFlush = true;
    await act(async () => { firstFlush = await result.current.flushPendingSave(); });

    expect(firstFlush).toBe(false);
    expect(attempts).toBe(1);
    expect(result.current.dirty).toBe(true);
    expect(result.current.saveError).not.toBe('');

    // The pending debounce may still wake up, but the exact failed snapshot
    // must remain blocked until a new edit or an explicit retry.
    await new Promise((resolve) => window.setTimeout(resolve, 850));
    expect(attempts).toBe(1);

    server.use(http.put('http://localhost/api/v1/documents/content', () => {
      attempts += 1;
      return HttpResponse.json({ success: true, version: 'v2' });
    }));
    let retried = false;
    await act(async () => { retried = await result.current.flushPendingSave(); });
    expect(retried).toBe(true);
    expect(attempts).toBe(2);
    expect(result.current.dirty).toBe(false);
    expect(result.current.saveError).toBe('');
  });

  it('does not permanently block autosave when editing away from and back to a failed snapshot', async () => {
    let attempts = 0;
    server.use(http.put('http://localhost/api/v1/documents/content', () => {
      attempts += 1;
      return attempts === 1
        ? HttpResponse.json({ detail: 'Temporary failure' }, { status: 503 })
        : HttpResponse.json({ success: true, version: 'v2' });
    }));
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Same final draft'));
    await act(async () => { await result.current.flushPendingSave(); });
    expect(attempts).toBe(1);

    act(() => {
      result.current.setSource('# Briefly different');
      result.current.setSource('# Same final draft');
    });

    await waitFor(() => expect(attempts).toBe(2), { timeout: 2_000 });
    await waitFor(() => expect(result.current.dirty).toBe(false));
  });

  it('prevents unloading while a local draft is waiting for autosave', async () => {
    const { result } = renderHook(
      () => useDocumentWorkspace('Guide.md'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    act(() => result.current.setSource('# Pending draft'));
    const event = new Event('beforeunload', { cancelable: true });
    const allowed = window.dispatchEvent(event);

    expect(allowed).toBe(false);
    expect(event.defaultPrevented).toBe(true);
  });

  it('does not let an obsolete external refresh replace a newly selected document', async () => {
    const { result, rerender } = renderHook(
      ({ selectedPath }: { selectedPath: string }) => useDocumentWorkspace(selectedPath),
      { initialProps: { selectedPath: 'Guide.md' }, wrapper },
    );
    await waitFor(() => expect(result.current.title).toBe('Guide.md'));

    let releaseOldRequest: () => void = () => undefined;
    let markOldRequestStarted: () => void = () => undefined;
    const oldRequestStarted = new Promise<void>((resolve) => { markOldRequestStarted = resolve; });
    const oldRequestGate = new Promise<void>((resolve) => { releaseOldRequest = resolve; });
    server.use(http.get('http://localhost/api/v1/documents/content', async ({ request }) => {
      const requestedPath = new URL(request.url).searchParams.get('path');
      if (requestedPath === 'Guide.md') {
        markOldRequestStarted();
        await oldRequestGate;
        return HttpResponse.json({
          path: 'Guide.md',
          filename: 'Guide.md',
          content: '# Obsolete disk revision',
          size: 24,
          modified: '2026-01-04T12:00:00',
          version: 'v2',
        });
      }
      return HttpResponse.json({
        path: 'Other.md',
        filename: 'Other.md',
        content: '# Current document',
        size: 18,
        modified: '2026-01-04T12:00:01',
        version: 'v1',
      });
    }));

    let obsoleteRefresh: ReturnType<typeof result.current.refreshExternal> | undefined;
    act(() => { obsoleteRefresh = result.current.refreshExternal(); });
    await oldRequestStarted;
    rerender({ selectedPath: 'Other.md' });
    await waitFor(() => expect(result.current.title).toBe('Other.md'));

    releaseOldRequest();
    await act(async () => { await obsoleteRefresh; });
    expect(result.current.title).toBe('Other.md');
    expect(result.current.source).toBe('# Current document');
  });

  it('never exposes the previous document when a newly selected document fails to load', async () => {
    const { result, rerender } = renderHook(
      ({ selectedPath }: { selectedPath: string }) => useDocumentWorkspace(selectedPath),
      { initialProps: { selectedPath: 'Guide.md' }, wrapper },
    );
    await waitFor(() => expect(result.current.source).not.toBe(''));
    const previousSource = result.current.source;

    server.use(http.get('http://localhost/api/v1/documents/content', ({ request }) => {
      const requestedPath = new URL(request.url).searchParams.get('path');
      if (requestedPath === 'Other.md') {
        return HttpResponse.json({
          detail: 'The selected document is temporarily unavailable.',
          code: 'document_unavailable',
        }, { status: 503 });
      }
      return HttpResponse.json({
        path: 'Guide.md',
        filename: 'Guide.md',
        content: '# Guide',
        size: 7,
        version: 'v1',
      });
    }));

    rerender({ selectedPath: 'Other.md' });
    expect(result.current.source).toBe('');
    expect(result.current.title).toBe('Other.md');
    await waitFor(() => expect(result.current.loadFailed).toBe(true));
    expect(result.current.source).toBe('');
    expect(result.current.source).not.toContain(previousSource);
    expect(result.current.title).toBe('Other.md');
    expect(result.current.error).toContain('temporarily unavailable');
  });
});
