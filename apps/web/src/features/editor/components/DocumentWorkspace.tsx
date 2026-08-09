import { type CSSProperties, lazy, Suspense, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { AlertTriangle, Eye, FileDown, MoreHorizontal, RefreshCw, RotateCcw, Save, SplitSquareHorizontal, TextCursorInput } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { DropdownMenu } from '@/shared/ui/DropdownMenu';
import { ResizeHandle } from '@/shared/ui/ResizeHandle';
import { downloadMarkdown } from '../model/downloadMarkdown';
import { PreviewPane } from './PreviewPane';
import type { ReturnTypeOfWorkspace } from './types';

const CodeEditor = lazy(() => import('./CodeEditor'));

interface Props {
  workspace: ReturnTypeOfWorkspace;
  dark: boolean;
  editorLineWrap?: boolean;
  splitRatio: number;
  onSplitRatioChange: (ratio: number) => void;
}

// A two-column source/preview split is too cramped at common 768px tablet
// widths; stack it until each pane can retain a comfortable reading measure.
const STACKED_SPLIT_MAX_WIDTH = 800;

export function DocumentWorkspace({ workspace, dark, editorLineWrap = true, splitRatio, onSplitRatioChange }: Props) {
  const { t, i18n } = useTranslation();
  const titleId = useId();
  const saveStatusId = useId();
  const conflictBodyId = useId();
  const draftRecoveryBodyId = useId();
  const panes = useRef<HTMLDivElement>(null);
  const revealSequence = useRef(0);
  const [revealRequest, setRevealRequest] = useState<{ id: number; text: string } | null>(null);
  const [findError, setFindError] = useState('');
  const [stackedSplit, setStackedSplit] = useState(false);
  const [editorActivated, setEditorActivated] = useState(workspace.mode !== 'preview');
  const save = useRef(workspace.save);
  save.current = workspace.save;
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.defaultPrevented || (!(event.ctrlKey || event.metaKey)) || event.key.toLowerCase() !== 's') return;
      event.preventDefault();
      void save.current();
    };
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, []);
  useEffect(() => {
    if (workspace.mode !== 'preview') setEditorActivated(true);
  }, [workspace.mode]);
  useLayoutEffect(() => {
    const node = panes.current;
    if (!node || workspace.loading || workspace.mode !== 'split') {
      setStackedSplit(false);
      return undefined;
    }
    const update = () => {
      const width = node.getBoundingClientRect().width;
      setStackedSplit(width > 0 && width <= STACKED_SPLIT_MAX_WIDTH);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [workspace.loading, workspace.mode]);
  if (workspace.loadFailed) return <section className="empty-workspace workspace-load-error" aria-labelledby={titleId}>
    <div className="empty-illustration danger" aria-hidden="true"><AlertTriangle size={34} /></div>
    <h1 id={titleId}>{workspace.title}</h1>
    <p role="alert">{workspace.error || t('documentLoadFailed', { defaultValue: 'This document could not be loaded.' })}</p>
    <button type="button" className="button button-primary" onClick={() => void workspace.reloadFromDisk()}>{t('retry')}</button>
  </section>;
  if (!workspace.title && !workspace.loading) return <section className="empty-workspace" aria-labelledby={titleId}>
    <div className="empty-illustration" aria-hidden="true"><TextCursorInput size={34} /></div>
    <h1 id={titleId}>{t('selectDocument')}</h1>
    <p>{t('selectHint')}</p>
  </section>;
  const saveLabel = workspace.saveError
    ? t('saveFailed', { defaultValue: 'Save failed' })
    : workspace.saving ? t('saving') : workspace.dirty ? t('unsaved') : t('saved');
  return <section className="document-workspace" aria-labelledby={titleId} aria-busy={workspace.loading}>
    <header className="document-toolbar">
      <div className="document-title">
        <h1 id={titleId} className="document-title-heading">{workspace.title || t('loading')}</h1>
        <span
          id={saveStatusId}
          className={`save-status status-announcement ${workspace.dirty ? 'dirty' : ''} ${workspace.saving ? 'saving' : ''} ${workspace.saveError ? 'error' : ''}`.trim()}
          data-state={workspace.saveError ? 'error' : workspace.saving ? 'saving' : workspace.dirty ? 'pending' : 'saved'}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >{saveLabel}</span>
      </div>
      <div className="toolbar-actions">
        <div className="segmented view-mode-segmented" role="group" aria-label={t('viewMode')}>
          <button type="button" className={`touch-target ${workspace.mode === 'preview' ? 'active' : ''}`} aria-label={t('preview')} title={t('preview')} aria-pressed={workspace.mode === 'preview'} onClick={() => workspace.setMode('preview')}><Eye size={16} aria-hidden="true" /></button>
          <button type="button" className={`touch-target ${workspace.mode === 'source' ? 'active' : ''}`} aria-label={t('source')} title={t('source')} aria-pressed={workspace.mode === 'source'} onClick={() => workspace.setMode('source')}><TextCursorInput size={16} aria-hidden="true" /></button>
          <button type="button" className={`touch-target ${workspace.mode === 'split' ? 'active' : ''}`} aria-label={t('split')} title={t('split')} aria-pressed={workspace.mode === 'split'} onClick={() => workspace.setMode('split')}><SplitSquareHorizontal size={16} aria-hidden="true" /></button>
        </div>
        <DropdownMenu
          label={t('actions')}
          align="end"
          className="document-action-menu"
          trigger={<MoreHorizontal size={18} aria-hidden="true" />}
          triggerClassName="icon-button touch-target"
          items={[
            {
              id: 'download-markdown',
              label: t('downloadMarkdown', { defaultValue: 'Download Markdown' }),
              icon: <FileDown size={16} />,
              onSelect: () => downloadMarkdown(workspace.title, workspace.source),
            },
            {
              id: 'refresh-preview',
              label: t('refreshPreview'),
              icon: <RefreshCw size={16} />,
              onSelect: () => void workspace.refreshPreview(),
            },
            {
              id: 'reload-disk',
              label: t('reloadDisk'),
              icon: <RotateCcw size={16} />,
              onSelect: () => void workspace.reloadFromDisk(),
            },
          ]}
        />
        <button
          type="button"
          className="button button-primary touch-target"
          disabled={!workspace.dirty || workspace.saving}
          aria-describedby={saveStatusId}
          aria-keyshortcuts="Control+S Meta+S"
          onClick={() => void workspace.save()}
        ><Save size={15} aria-hidden="true" />{workspace.saving
            ? t('saving')
            : workspace.saveError
              ? t('retrySave', { defaultValue: 'Retry save' })
              : t('save')}</button>
      </div>
    </header>
    <div className="workspace-notices">
      {workspace.conflict && <div className={`conflict-banner ${workspace.continuingLocal ? 'is-continuing' : ''}`.trim()} role="alert"><AlertTriangle size={19} aria-hidden="true" /><div><strong>{t('conflictTitle')}</strong><p id={conflictBodyId}>{workspace.continuingLocal
        ? t('conflictContinueBody', { defaultValue: 'Editing continues locally. This conflict remains unresolved until you reconcile the disk version.' })
        : t('conflictBody', { source: workspace.conflict.source })}</p></div><div className="conflict-actions">{!workspace.continuingLocal && <button type="button" className="button" onClick={workspace.keepLocal}>{t('continueEditing', { defaultValue: 'Continue editing' })}</button>}<button type="button" className="button button-danger" aria-describedby={conflictBodyId} onClick={() => void workspace.loadDiskVersion()}>{t('loadDisk')}</button></div></div>}
      {workspace.recoverableDraft && <div className="conflict-banner draft-recovery-banner" role="status" aria-live="polite"><RotateCcw size={19} aria-hidden="true" /><div><strong>{t('draftRecoveryTitle', { defaultValue: 'Local draft available' })}</strong><p id={draftRecoveryBodyId}>{t('draftRecoveryBody', { defaultValue: 'The most recently replaced local draft is preserved and can be restored.' })}</p></div><div className="conflict-actions"><button type="button" className="button" aria-describedby={draftRecoveryBodyId} onClick={() => void workspace.recoverLocalDraft()}>{t('restoreDraft', { defaultValue: 'Restore draft' })}</button></div></div>}
      {workspace.largeFile && workspace.mode !== 'preview' && <div className="large-file-banner" role="status">{t('largeFile')}</div>}
      {(workspace.saveError || workspace.error || findError) && <div className="workspace-error" role="alert"><AlertTriangle size={18} />{workspace.saveError || workspace.error || findError}</div>}
    </div>
    {workspace.loading ? <div className="workspace-loading" role="status" aria-live="polite">{t('loading')}</div> : <div
      ref={panes}
      className={`workspace-panes mode-${workspace.mode} ${stackedSplit ? 'stacked-split' : ''}`.trim()}
      style={{ '--split-ratio': `${splitRatio * 100}%`, '--split-remainder': `${(1 - splitRatio) * 100}%` } as CSSProperties}
    >
      {(editorActivated || workspace.mode !== 'preview') && <div
        className="editor-pane content-visibility-auto"
        hidden={workspace.mode === 'preview'}
        inert={workspace.mode === 'preview' ? true : undefined}
      ><Suspense fallback={<div className="workspace-loading" role="status">{t('loading')}</div>}><CodeEditor value={workspace.source} onChange={workspace.setSource} dark={dark} lineWrap={editorLineWrap} label={t('sourceEditor')} onSave={() => void workspace.save()} revealRequest={revealRequest} onRevealResult={(found) => setFindError(found ? '' : t('sourceNotFound'))} /></Suspense></div>}
      {workspace.mode === 'split' && <ResizeHandle label={t('resizeSplit')} orientation={stackedSplit ? 'horizontal' : 'vertical'} value={splitRatio * 100} minimum={20} maximum={80} valueText={`${Math.round(splitRatio * 100)}%`} onResize={(delta) => {
        const bounds = panes.current?.getBoundingClientRect();
        const availableSize = stackedSplit ? bounds?.height ?? 0 : bounds?.width ?? 0;
        if (availableSize > 0) onSplitRatioChange(Math.min(0.8, Math.max(0.2, splitRatio + delta / availableSize)));
      }} />}
      {workspace.mode !== 'source' && <div className="preview-pane content-visibility-auto"><PreviewPane html={workspace.html} dark={dark} onFindInSource={(text) => {
        setFindError('');
        revealSequence.current += 1;
        setRevealRequest({ id: revealSequence.current, text });
        if (workspace.mode === 'preview') workspace.setMode('source');
      }} /></div>}
    </div>}
    <footer className="document-status"><span>{t('characterCount', { count: workspace.source.length.toLocaleString(i18n.resolvedLanguage ?? i18n.language) })}</span><span>{t('autoSaveHint', { defaultValue: 'Autosave is on · Ctrl/⌘+S saves now' })}</span></footer>
  </section>;
}
