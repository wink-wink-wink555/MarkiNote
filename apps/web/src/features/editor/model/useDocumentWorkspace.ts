import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, errorMessage } from '@/shared/api';
import { basename, dirname } from '@/shared/lib/format';
import { useDebouncedValue } from '@/shared/lib/useDebouncedValue';
import { useToast } from '@/shared/ui/Toast';
import { editorApi, type UpdateStamp } from '../api/editorApi';

export type ViewMode = 'preview' | 'source' | 'split';
export interface ExternalConflict { source: 'external' | 'ai' | 'rollback'; diskSource: string; diskHtml: string; diskVersion: string }
export interface RecoverableDraft { path: string; source: string }
export type ExternalRefreshResult = 'ignored' | 'unchanged' | 'updated' | 'conflict' | 'missing' | 'error';
const LIVE_PREVIEW_LIMIT = 768 * 1024;
const AUTO_SAVE_DELAY = 700;

function exceedsLivePreviewLimit(value: string): boolean {
  // UTF-8 is at least one byte per UTF-16 code unit and at most three bytes
  // per unit. Most documents can therefore skip an allocating byte count.
  if (value.length > LIVE_PREVIEW_LIMIT) return true;
  if (value.length * 3 <= LIVE_PREVIEW_LIMIT) return false;
  return new Blob([value]).size > LIVE_PREVIEW_LIMIT;
}

interface WorkspaceOptions { confirmDiscard?: () => boolean }

export function useDocumentWorkspace(path: string, { confirmDiscard = () => true }: WorkspaceOptions = {}) {
  const toast = useToast();
  const [source, setSource] = useState('');
  const [persisted, setPersisted] = useState('');
  const [html, setHtml] = useState('');
  const [title, setTitle] = useState('');
  const [version, setVersion] = useState('');
  const [mode, setMode] = useState<ViewMode>('preview');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loadErrorPath, setLoadErrorPath] = useState('');
  const [saveError, setSaveError] = useState('');
  const [conflict, setConflict] = useState<ExternalConflict | null>(null);
  const [continuingLocal, setContinuingLocal] = useState(false);
  const [recoverableDraft, setRecoverableDraft] = useState<RecoverableDraft | null>(null);
  const stamp = useRef<UpdateStamp | null>(null);
  const loadedPath = useRef('');
  const currentPath = useRef(path);
  const latest = useRef({ path, source, persisted, version });
  const mounted = useRef(true);
  const conflictRef = useRef(conflict);
  const saveInFlight = useRef<Promise<boolean> | null>(null);
  const saveQueued = useRef(false);
  const forceSaveQueued = useRef(false);
  const failedAutoSave = useRef<{ path: string; source: string } | null>(null);
  latest.current = { path, source, persisted, version };
  currentPath.current = path;
  conflictRef.current = conflict;
  const dirty = source !== persisted;
  const debouncedSource = useDebouncedValue(source, 450);
  const debouncedAutoSaveSource = useDebouncedValue(source, AUTO_SAVE_DELAY);
  const deferredSourceForSize = useDeferredValue(source);
  const largeFile = useMemo(() => exceedsLivePreviewLimit(deferredSourceForSize), [deferredSourceForSize]);

  const applyDocument = useCallback((document: { raw_markdown: string; html: string; filename: string; version: string }) => {
    setSource(document.raw_markdown ?? '');
    setPersisted(document.raw_markdown ?? '');
    setHtml(document.html ?? '');
    setTitle(document.filename);
    setVersion(document.version);
    setSaveError('');
    setLoadErrorPath('');
    failedAutoSave.current = null;
    setConflict(null);
    setContinuingLocal(false);
  }, []);

  const updateSource = useCallback((nextSource: string) => {
    latest.current = { ...latest.current, source: nextSource };
    const failed = failedAutoSave.current;
    if (failed && (failed.path !== latest.current.path || failed.source !== nextSource)) {
      // Editing after a failure is a fresh autosave intent. Clear the
      // snapshot guard so even typing away and back within the debounce
      // window cannot leave that content permanently blocked.
      failedAutoSave.current = null;
      setSaveError('');
    }
    setSource(nextSource);
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    const targetPath = path;
    loadedPath.current = '';
    if (!path) {
      setSource(''); setPersisted(''); setHtml(''); setTitle(''); setVersion(''); setError('');
      setLoadErrorPath('');
      setSaveError(''); setConflict(null); setContinuingLocal(false); setRecoverableDraft(null);
      failedAutoSave.current = null;
      stamp.current = null;
      return null;
    }
    setLoading(true); setError(''); setLoadErrorPath(''); stamp.current = null;
    setSource(''); setPersisted(''); setHtml(''); setTitle(basename(targetPath)); setVersion('');
    setSaveError(''); setConflict(null); setContinuingLocal(false);
    failedAutoSave.current = null;
    try {
      let initialStamp: UpdateStamp | null = null;
      try {
        initialStamp = await editorApi.updates(dirname(targetPath), targetPath, signal);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === 'AbortError') return null;
        // A watcher baseline is optional; the first successful poll reconciles the disk below.
      }
      const document = await editorApi.preview(targetPath, signal);
      if (signal?.aborted || currentPath.current !== targetPath) return null;
      stamp.current = initialStamp;
      loadedPath.current = targetPath;
      applyDocument(document);
      return document;
    }
    catch (caught) {
      if (
        !(caught instanceof DOMException && caught.name === 'AbortError')
        && currentPath.current === targetPath
      ) {
        setError(errorMessage(caught));
        setLoadErrorPath(targetPath);
      }
    }
    finally {
      if (!signal?.aborted && currentPath.current === targetPath) setLoading(false);
    }
    return null;
  }, [applyDocument, path]);

  const reloadFromDisk = useCallback(async () => {
    const localDraft = latest.current.source !== latest.current.persisted
      ? { path: currentPath.current, source: latest.current.source }
      : null;
    if (localDraft && !confirmDiscard()) return false;
    const loaded = await load();
    if (!loaded) return false;
    if (localDraft && localDraft.source !== loaded.raw_markdown) setRecoverableDraft(localDraft);
    return true;
  }, [confirmDiscard, load]);

  const refreshPreview = useCallback(async () => {
    const renderingPath = currentPath.current;
    if (!renderingPath) return;
    setError('');
    try {
      const rendered = await editorApi.render(latest.current.source);
      if (currentPath.current === renderingPath) setHtml(rendered.html);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }, []);

  useEffect(() => {
    setRecoverableDraft(null);
    setContinuingLocal(false);
  }, [path]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (!path || mode === 'preview' || largeFile || debouncedSource === persisted) return undefined;
    const controller = new AbortController();
    void editorApi.render(debouncedSource, controller.signal).then((result) => setHtml(result.html)).catch((caught: unknown) => {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) setError(errorMessage(caught));
    });
    return () => controller.abort();
  }, [debouncedSource, largeFile, mode, path, persisted]);

  const refreshExternal = useCallback(async (
    sourceName: ExternalConflict['source'] = 'external',
    targetPath = currentPath.current,
    signal?: AbortSignal,
  ): Promise<ExternalRefreshResult> => {
    if (!targetPath || targetPath !== currentPath.current || signal?.aborted) return 'ignored';
    try {
      const disk = await editorApi.preview(targetPath, signal);
      if (signal?.aborted || targetPath !== currentPath.current) return 'ignored';
      if (disk.raw_markdown === latest.current.persisted) {
        setConflict(null);
        setContinuingLocal(false);
        return 'unchanged';
      }
      if (latest.current.source !== latest.current.persisted) {
        setConflict({ source: sourceName, diskSource: disk.raw_markdown, diskHtml: disk.html, diskVersion: disk.version });
        setContinuingLocal(false);
        return 'conflict';
      }
      applyDocument(disk);
      return 'updated';
    } catch (caught) {
      if (
        sourceName !== 'external'
        && caught instanceof ApiError
        && (caught.code === 'document_not_found' || caught.status === 404)
        && targetPath === currentPath.current
      ) return 'missing';
      if (
        !(caught instanceof DOMException && caught.name === 'AbortError')
        && targetPath === currentPath.current
      ) toast(errorMessage(caught), 'error');
      return caught instanceof DOMException && caught.name === 'AbortError'
        ? 'ignored'
        : 'error';
    }
  }, [applyDocument, toast]);

  useEffect(() => {
    if (!path) return undefined;
    let active = true;
    let inFlight = false;
    let timer: number | undefined;
    let request: AbortController | undefined;
    const schedule = () => {
      if (!active || document.visibilityState === 'hidden') return;
      if (timer !== undefined) window.clearTimeout(timer);
      timer = window.setTimeout(() => { void poll(); }, 4_000);
    };
    const poll = async () => {
      if (!active || inFlight) return;
      if (document.visibilityState === 'hidden') return;
      if (loadedPath.current !== path) {
        schedule();
        return;
      }
      inFlight = true;
      const controller = new AbortController();
      request = controller;
      try {
        const next = await editorApi.updates(dirname(path), path, controller.signal);
        if (!active) return;
        const previous = stamp.current;
        stamp.current = next;
        if (!previous || (next.file_mtime && next.file_mtime !== previous.file_mtime)) {
          await refreshExternal('external', path, controller.signal);
        }
      } catch { /* transient watcher errors should not interrupt editing */ }
      finally {
        if (request === controller) request = undefined;
        inFlight = false;
        schedule();
      }
    };
    const visibilityChanged = () => {
      if (document.visibilityState === 'hidden') {
        if (timer !== undefined) window.clearTimeout(timer);
        timer = undefined;
        request?.abort();
      } else {
        void poll();
      }
    };
    void poll();
    document.addEventListener('visibilitychange', visibilityChanged);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
      request?.abort();
      document.removeEventListener('visibilitychange', visibilityChanged);
    };
  }, [path, refreshExternal]);

  const requestSave = useCallback((force = false): Promise<boolean> => {
    const requested = latest.current;
    if (!requested.path) {
      return Promise.resolve(true);
    }
    if (loadedPath.current !== requested.path) {
      return Promise.resolve(false);
    }
    // A write may currently be persisting an older buffer. Even when the
    // editor has meanwhile returned to its previously persisted text
    // (`dirty === false`), callers must wait for that write and the compensating
    // save that the queue will schedule afterwards.
    if (saveInFlight.current) {
      saveQueued.current = true;
      forceSaveQueued.current = forceSaveQueued.current || force;
      return saveInFlight.current;
    }
    if (requested.source === requested.persisted) {
      return Promise.resolve(true);
    }
    const failed = failedAutoSave.current;
    if (!force && failed?.path === requested.path && failed.source === requested.source) {
      return Promise.resolve(false);
    }

    saveQueued.current = true;
    forceSaveQueued.current = forceSaveQueued.current || force;
    const run = async () => {
      if (mounted.current) setSaving(true);
      while (saveQueued.current) {
        const forceCurrentSave = forceSaveQueued.current;
        saveQueued.current = false;
        forceSaveQueued.current = false;
        const snapshot = { ...latest.current };
        if (
          !snapshot.path
          || loadedPath.current !== snapshot.path
          || snapshot.source === snapshot.persisted
        ) continue;
        const blocked = failedAutoSave.current;
        if (
          !forceCurrentSave
          && blocked?.path === snapshot.path
          && blocked.source === snapshot.source
        ) continue;

        try {
          const saved = await editorApi.save(snapshot.path, snapshot.source, snapshot.version);
          failedAutoSave.current = null;
          if (latest.current.path === snapshot.path) {
            latest.current = {
              ...latest.current,
              persisted: snapshot.source,
              version: saved.version,
            };
            if (mounted.current) {
              setPersisted(snapshot.source);
              setVersion(saved.version);
              setSaveError('');
              setConflict(null);
              setContinuingLocal(false);
            }

            // Rendering is deliberately detached from the serialized write
            // queue. A slow render must never delay a newer document save or
            // replace the preview for text typed while this save was running.
            void editorApi.render(snapshot.source).then((rendered) => {
              if (
                mounted.current
                && latest.current.path === snapshot.path
                && latest.current.source === snapshot.source
              ) setHtml(rendered.html);
            }).catch((caught: unknown) => {
              if (mounted.current && latest.current.path === snapshot.path) {
                setError(errorMessage(caught));
              }
            });

            // If editing continued during the request, immediately drain the
            // latest buffer with the version returned by this save.
            if (latest.current.source !== snapshot.source) saveQueued.current = true;
          }
        } catch (caught) {
          const message = errorMessage(caught);
          const versionConflict = caught instanceof ApiError && caught.code === 'document_version_conflict';
          const failedSnapshotStillCurrent = latest.current.path === snapshot.path
            && latest.current.source === snapshot.source;
          if (failedSnapshotStillCurrent) {
            failedAutoSave.current = { path: snapshot.path, source: snapshot.source };
            if (mounted.current) setSaveError(message);
          } else {
            // This request belongs to an obsolete buffer. Let the queued
            // current buffer decide the final status instead of permanently
            // blocking it with an error for text the user no longer has.
            failedAutoSave.current = null;
            if (mounted.current && latest.current.path === snapshot.path) setSaveError('');
          }
          if (failedSnapshotStillCurrent || versionConflict) toast(message, 'error');
          if (versionConflict && latest.current.path === snapshot.path) {
            await refreshExternal('external', snapshot.path);
          }
          // A newer buffer explicitly queued while this request was pending
          // still gets one save attempt. The failed snapshot itself is not
          // retried automatically, preventing an error loop.
          const hasQueuedNewerDraft = saveQueued.current
            && latest.current.path === snapshot.path
            && latest.current.source !== snapshot.source
            && !versionConflict;
          saveQueued.current = hasQueuedNewerDraft;
          if (!hasQueuedNewerDraft) break;
        }
      }
      const current = latest.current;
      const failed = failedAutoSave.current;
      return current.source === current.persisted
        && !(failed?.path === current.path && failed.source === current.source);
    };

    const pending = run().finally(() => {
      saveInFlight.current = null;
      if (mounted.current) setSaving(false);
    });
    saveInFlight.current = pending;
    return pending;
  }, [refreshExternal, toast]);

  const save = useCallback(() => requestSave(true), [requestSave]);
  const flushPendingSave = useCallback(() => requestSave(true), [requestSave]);

  useEffect(() => {
    if (
      !path
      || conflict
      || loadedPath.current !== path
      || debouncedAutoSaveSource !== latest.current.source
      || debouncedAutoSaveSource === persisted
    ) return;
    void requestSave(false);
  }, [conflict, debouncedAutoSaveSource, path, persisted, requestSave]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty || saving) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty, saving]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const loadDiskVersion = useCallback(() => {
    if (!conflict || !confirmDiscard()) return false;
    const localDraft = latest.current.source !== conflict.diskSource
      ? { path: currentPath.current, source: latest.current.source }
      : null;
    if (localDraft) setRecoverableDraft(localDraft);
    failedAutoSave.current = null;
    setSource(conflict.diskSource); setPersisted(conflict.diskSource); setHtml(conflict.diskHtml); setVersion(conflict.diskVersion); setSaveError(''); setConflict(null);
    setContinuingLocal(false);
    return true;
  }, [confirmDiscard, conflict]);

  const recoverLocalDraft = useCallback(async () => {
    const draft = recoverableDraft;
    if (!draft || draft.path !== currentPath.current) return false;

    const replacedLocalDraft = latest.current.source !== latest.current.persisted
      && latest.current.source !== draft.source
      ? { path: currentPath.current, source: latest.current.source }
      : null;
    updateSource(draft.source);
    setRecoverableDraft(replacedLocalDraft);
    setError('');

    const recoveringPath = currentPath.current;
    try {
      const rendered = await editorApi.render(draft.source);
      if (currentPath.current === recoveringPath) setHtml(rendered.html);
    } catch (caught) {
      if (currentPath.current === recoveringPath) setError(errorMessage(caught));
    }
    return true;
  }, [recoverableDraft, updateSource]);

  const keepLocal = useCallback(() => {
    if (conflict) setContinuingLocal(true);
  }, [conflict]);

  const documentReady = Boolean(path) && loadedPath.current === path;
  const loadFailed = Boolean(path) && !loading && !documentReady && loadErrorPath === path;
  return {
    source: documentReady ? source : '',
    setSource: updateSource,
    html: documentReady ? html : '',
    title: path ? (documentReady ? title : basename(path)) : '',
    mode,
    setMode,
    dirty: documentReady ? dirty : false,
    loading: Boolean(path) && !loadFailed && (loading || !documentReady),
    loadFailed,
    saving,
    error: path ? error : '',
    saveError: documentReady ? saveError : '',
    conflict: documentReady ? conflict : null,
    continuingLocal: documentReady ? continuingLocal : false,
    recoverableDraft: documentReady && recoverableDraft?.path === path ? recoverableDraft : null,
    largeFile: documentReady && largeFile,
    save, flushPendingSave, refreshPreview, reloadFromDisk, refreshExternal, keepLocal, loadDiskVersion, recoverLocalDraft,
  };
}
