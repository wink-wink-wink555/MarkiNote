import { useQueryClient } from '@tanstack/react-query';
import { Bot, Menu, NotebookPen, PanelLeftClose, Settings } from 'lucide-react';
import {
  type CSSProperties,
  type RefObject,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { AuthenticationBoundary } from '@/features/auth/components/AuthenticationBoundary';
import { DocumentWorkspace } from '@/features/editor/components/DocumentWorkspace';
import { useDocumentWorkspace } from '@/features/editor/model/useDocumentWorkspace';
import { selectedPathAfterMutations } from './documentMutations';
import { LibrarySidebar } from '@/features/library/components/LibrarySidebar';
import type { DocumentMutation } from '@/shared/api';
import { changeLanguage, languages } from '@/shared/i18n';
import {
  DENSITY_PREFERENCES,
  loadUiPreferences,
  READING_LINE_HEIGHTS,
  READING_WIDTHS,
  readingWidthCssValue,
  type ThemePreference,
  updateUiPreferences,
} from '@/shared/lib/preferences';
import { Modal } from '@/shared/ui/Modal';
import { ResizeHandle } from '@/shared/ui/ResizeHandle';

const themes: ThemePreference[] = ['light', 'dark', 'blue', 'pink'];

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));
const DRAWER_LAYOUT_MAX_WIDTH = 980;
const PANEL_TRANSITION_MS = 240;
const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

let chatPanelImport: Promise<typeof import('@/features/ai/components/ChatPanel')> | undefined;
const loadChatPanel = () => {
  chatPanelImport ??= import('@/features/ai/components/ChatPanel');
  return chatPanelImport;
};
const ChatPanel = lazy(async () => {
  const module = await loadChatPanel();
  return { default: module.ChatPanel };
});

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [query]);
  return matches;
}

function useExitPresence(visible: boolean, duration: number): boolean {
  const [present, setPresent] = useState(visible);
  useEffect(() => {
    if (visible) {
      setPresent(true);
      return undefined;
    }
    const timer = window.setTimeout(() => setPresent(false), duration);
    return () => window.clearTimeout(timer);
  }, [duration, visible]);
  return present;
}

function useDrawerFocus(
  active: boolean,
  panelId: string,
  returnFocus: RefObject<HTMLButtonElement | null>,
  onClose: () => void,
) {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!active) return undefined;
    const previous = returnFocus.current ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    let panel: HTMLElement | null = null;
    let replacementFocusTimer: number | undefined;
    let original: { role: string | null; modal: string | null; tabIndex: string | null } | null = null;
    const restorePanel = () => {
      if (!panel || !original) return;
      if (original.role === null) panel.removeAttribute('role'); else panel.setAttribute('role', original.role);
      if (original.modal === null) panel.removeAttribute('aria-modal'); else panel.setAttribute('aria-modal', original.modal);
      if (original.tabIndex === null) panel.removeAttribute('tabindex'); else panel.setAttribute('tabindex', original.tabIndex);
    };
    const applyPanelSemantics = () => {
      const next = document.getElementById(panelId);
      if (!(next instanceof HTMLElement) || next === panel) return false;
      restorePanel();
      panel = next;
      original = {
        role: panel.getAttribute('role'),
        modal: panel.getAttribute('aria-modal'),
        tabIndex: panel.getAttribute('tabindex'),
      };
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-modal', 'true');
      panel.setAttribute('tabindex', '-1');
      return true;
    };
    const drawerFocusables = () => {
      applyPanelSemantics();
      if (!panel) return [];
      return [...panel.querySelectorAll<HTMLElement>(focusableSelector)]
        .filter((element) => !element.hidden && element.getAttribute('aria-hidden') !== 'true');
    };
    const focusPanel = () => {
      const [first] = drawerFocusables();
      const preferred = panel?.querySelector<HTMLElement>('[data-drawer-initial-focus]');
      (preferred ?? first ?? panel)?.focus();
    };
    applyPanelSemantics();
    const observer = new MutationObserver(() => {
      const replaced = applyPanelSemantics();
      if (replaced) {
        if (replacementFocusTimer !== undefined) window.clearTimeout(replacementFocusTimer);
        replacementFocusTimer = window.setTimeout(focusPanel, 0);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const focusTimer = window.setTimeout(() => {
      focusPanel();
    }, 0);
    const keydown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented
        || document.querySelector('.modal-backdrop')
        || document.querySelector('.menu-popover-portal')
      ) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusables = drawerFocusables();
      if (!focusables.length) {
        event.preventDefault();
        panel?.focus();
        return;
      }
      const first = focusables[0]!;
      const last = focusables.at(-1)!;
      const current = document.activeElement;
      if (event.shiftKey && (current === first || !focusables.includes(current as HTMLElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !focusables.includes(current as HTMLElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', keydown);

    return () => {
      window.clearTimeout(focusTimer);
      if (replacementFocusTimer !== undefined) window.clearTimeout(replacementFocusTimer);
      observer.disconnect();
      document.removeEventListener('keydown', keydown);
      restorePanel();
      if (previous?.isConnected) window.setTimeout(() => previous.focus(), 0);
    };
  }, [active, panelId, returnFocus]);
}

export function App() {
  return <AuthenticationBoundary><WorkspaceApp /></AuthenticationBoundary>;
}

function WorkspaceApp() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [initialPreferences] = useState(loadUiPreferences);
  const [sidebarWidth, setSidebarWidth] = useState(initialPreferences.sidebarWidth);
  const [aiWidth, setAiWidth] = useState(initialPreferences.aiWidth);
  const drawerLayout = useMediaQuery(`(max-width: ${DRAWER_LAYOUT_MAX_WIDTH}px)`);
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const [currentPath, setCurrentPath] = useState('');
  const [selectedFile, setSelectedFile] = useState('');
  const [theme, setTheme] = useState<ThemePreference>(initialPreferences.theme);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(initialPreferences.aiOpen);
  const [aiLoaded, setAiLoaded] = useState(initialPreferences.aiOpen);
  const [sidebarOpen, setSidebarOpen] = useState(initialPreferences.sidebarOpen);
  const [activeDrawerPanel, setActiveDrawerPanel] = useState<'library-panel' | 'ai-panel' | ''>(
    initialPreferences.sidebarOpen ? 'library-panel' : initialPreferences.aiOpen ? 'ai-panel' : '',
  );
  const [splitRatio, setSplitRatio] = useState(initialPreferences.splitRatio);
  const [readingFontSize, setReadingFontSize] = useState(initialPreferences.readingFontSize);
  const [editorFontSize, setEditorFontSize] = useState(initialPreferences.editorFontSize);
  const [readingLineHeight, setReadingLineHeight] = useState(initialPreferences.readingLineHeight);
  const [readingWidth, setReadingWidth] = useState(initialPreferences.readingWidth);
  const [density, setDensity] = useState(initialPreferences.density);
  const [editorLineWrap, setEditorLineWrap] = useState(initialPreferences.editorLineWrap);
  const sidebarToggle = useRef<HTMLButtonElement>(null);
  const aiToggle = useRef<HTMLButtonElement>(null);
  const fileSelectionSequence = useRef(0);
  const confirmDiscard = useCallback(() => window.confirm(t('discardConfirm')), [t]);
  const workspace = useDocumentWorkspace(selectedFile, { confirmDiscard });
  const sidebarVisible = sidebarOpen && (!drawerLayout || activeDrawerPanel === 'library-panel');
  const aiVisible = aiOpen && (!drawerLayout || activeDrawerPanel === 'ai-panel');
  const activeDrawer = drawerLayout ? activeDrawerPanel : '';
  const drawerOpen = Boolean(activeDrawer);
  const transitionDuration = reducedMotion ? 0 : PANEL_TRANSITION_MS;
  const aiPresent = useExitPresence(aiLoaded && aiVisible, transitionDuration);
  const drawerPresent = useExitPresence(drawerOpen, transitionDuration);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const themeColors: Record<ThemePreference, string> = {
      light: '#f5f6f8',
      dark: '#0f1217',
      blue: '#f2f7fc',
      pink: '#fbf6f8',
    };
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themeColors[theme]);
    updateUiPreferences({ theme });
  }, [theme]);

  useEffect(() => {
    const persistence = window.setTimeout(() => updateUiPreferences({ aiOpen, sidebarOpen, sidebarWidth, aiWidth, splitRatio }), 120);
    return () => window.clearTimeout(persistence);
  }, [aiOpen, aiWidth, sidebarOpen, sidebarWidth, splitRatio]);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.density = density;
    root.style.setProperty('--reading-font-size', `${readingFontSize}px`);
    root.style.setProperty('--editor-font-size', `${editorFontSize}px`);
    root.style.setProperty('--line-height-reading', String(readingLineHeight));
    root.style.setProperty('--reading-width', readingWidthCssValue(readingWidth));
    const persistence = window.setTimeout(() => updateUiPreferences({
      readingFontSize,
      editorFontSize,
      readingLineHeight,
      readingWidth,
      density,
      editorLineWrap,
    }), 120);
    return () => window.clearTimeout(persistence);
  }, [density, editorFontSize, editorLineWrap, readingFontSize, readingLineHeight, readingWidth]);

  useEffect(() => {
    if (aiOpen) setAiLoaded(true);
  }, [aiOpen]);

  const {
    dirty: workspaceDirty,
    saving: workspaceSaving,
    flushPendingSave: flushWorkspaceSave,
  } = workspace;
  const flushDocumentChange = useCallback(async (affectedPath?: string) => {
    if (!selectedFile) return true;
    if (affectedPath && !(selectedFile === affectedPath || selectedFile.startsWith(`${affectedPath}/`))) return true;
    if (!workspaceDirty && !workspaceSaving) return true;
    return flushWorkspaceSave();
  }, [flushWorkspaceSave, selectedFile, workspaceDirty, workspaceSaving]);
  const selectFile = async (path: string): Promise<boolean> => {
    if (path === selectedFile) return true;
    const sequence = ++fileSelectionSequence.current;
    const saved = await flushDocumentChange();
    if (sequence !== fileSelectionSequence.current) return false;
    if (!saved && !confirmDiscard()) return false;
    setSelectedFile(path);
    if (drawerLayout) setActiveDrawerPanel('');
    return true;
  };
  const itemChanged = (before: string, after?: string) => {
    if (!(selectedFile === before || selectedFile.startsWith(`${before}/`))) return;
    if (!after) { setSelectedFile(''); return; }
    setSelectedFile(`${after}${selectedFile.slice(before.length)}`);
  };
  const filesChanged = useCallback((
    source: 'ai' | 'rollback',
    mutations?: DocumentMutation[],
  ) => {
    void queryClient.invalidateQueries({ queryKey: ['library'] });
    const nextSelectedFile = selectedPathAfterMutations(selectedFile, mutations);
    if (nextSelectedFile !== selectedFile) {
      setSelectedFile(nextSelectedFile);
      return;
    }
    void workspace.refreshExternal(source).then((outcome) => {
      if (outcome === 'missing') {
        setSelectedFile((current) => current === selectedFile ? '' : current);
      }
    });
  }, [queryClient, selectedFile, workspace]);

  const layoutStyle = {
    '--sidebar-width': `clamp(220px, ${sidebarWidth}px, 28vw)`,
    '--ai-width': `clamp(320px, ${aiWidth}px, 34vw)`,
  } as CSSProperties;
  const closeSidebar = useCallback(() => {
    if (drawerLayout) {
      setSidebarOpen(false);
      setActiveDrawerPanel('');
    } else {
      setSidebarOpen(false);
      setActiveDrawerPanel(aiOpen ? 'ai-panel' : '');
    }
  }, [aiOpen, drawerLayout]);
  const closeAi = useCallback(() => {
    if (drawerLayout) {
      setAiOpen(false);
      setActiveDrawerPanel('');
    } else {
      setAiOpen(false);
      setActiveDrawerPanel(sidebarOpen ? 'library-panel' : '');
    }
  }, [drawerLayout, sidebarOpen]);
  const toggleSidebar = () => {
    const next = !sidebarVisible;
    if (drawerLayout) {
      if (next) setSidebarOpen(true);
      else setSidebarOpen(false);
      setActiveDrawerPanel(next ? 'library-panel' : '');
      return;
    }
    setSidebarOpen(next);
    setActiveDrawerPanel(next ? 'library-panel' : aiOpen ? 'ai-panel' : '');
  };
  const toggleAi = () => {
    const next = !aiVisible;
    if (next) setAiLoaded(true);
    if (drawerLayout) {
      if (next) setAiOpen(true);
      else setAiOpen(false);
      setActiveDrawerPanel(next ? 'ai-panel' : '');
      return;
    }
    setAiOpen(next);
    setActiveDrawerPanel(next ? 'ai-panel' : sidebarOpen ? 'library-panel' : '');
  };
  const closeSettings = useCallback(() => {
    // Closing the settings surface is an explicit commit boundary. Persist
    // synchronously so an immediate refresh cannot beat the debounced effects.
    updateUiPreferences({
      theme,
      language: i18n.language,
      readingFontSize,
      editorFontSize,
      readingLineHeight,
      readingWidth,
      density,
      editorLineWrap,
    });
    setSettingsOpen(false);
  }, [
    density,
    editorFontSize,
    editorLineWrap,
    i18n.language,
    readingFontSize,
    readingLineHeight,
    readingWidth,
    theme,
  ]);
  useDrawerFocus(drawerLayout && sidebarVisible, 'library-panel', sidebarToggle, closeSidebar);
  useDrawerFocus(drawerLayout && aiVisible, 'ai-panel', aiToggle, closeAi);

  return <div className={`app-shell ${sidebarVisible ? 'sidebar-open' : 'sidebar-closed'} ${aiVisible ? 'ai-open' : ''} ${drawerLayout ? 'drawer-layout' : ''}`.trim()} style={layoutStyle}>
    <a className="skip-link" href="#workspace-main">{t('skipToWorkspace', { defaultValue: 'Skip to workspace' })}</a>
    <header className="app-topbar">
      <div className="topbar-brand"><button ref={sidebarToggle} className="icon-button sidebar-toggle" onClick={toggleSidebar} aria-label={t('library')} title={t('library')} aria-controls="library-panel" aria-expanded={sidebarVisible}>{sidebarVisible ? <PanelLeftClose size={19} aria-hidden="true" /> : <Menu size={19} aria-hidden="true" />}</button><span className="brand-mark"><NotebookPen size={17} aria-hidden="true" /></span><strong translate="no">{t('appName')}</strong></div>
      <div className="topbar-actions"><button className="icon-button topbar-icon-action" onClick={() => setSettingsOpen(true)} aria-label={t('settings')} title={t('settings')}><Settings size={18} aria-hidden="true" /></button><button ref={aiToggle} className={`icon-button topbar-icon-action ai-toggle ${aiVisible ? 'active' : ''}`} onClick={toggleAi} onPointerEnter={() => void loadChatPanel()} onFocus={() => void loadChatPanel()} aria-label={t('ai')} title={t('ai')} aria-controls="ai-panel" aria-expanded={aiVisible}><Bot size={19} aria-hidden="true" /></button></div>
    </header>
    <div className="app-body">
      {drawerLayout && <div
        className={`app-drawer-scrim ${drawerOpen ? 'is-open' : 'is-closed'}`}
        data-drawer-for={activeDrawer || undefined}
        aria-hidden="true"
        onClick={activeDrawer === 'library-panel' ? closeSidebar : closeAi}
      />}
      <div
        className="panel-slot library-panel-slot"
        aria-hidden={!sidebarVisible}
        inert={!sidebarVisible ? true : undefined}
      >
        <LibrarySidebar currentPath={currentPath} selectedFile={selectedFile} onPathChange={setCurrentPath} onSelectFile={selectFile} onBeforeItemChange={flushDocumentChange} onItemChanged={itemChanged} onClose={drawerLayout ? closeSidebar : undefined} active={sidebarVisible} />
      </div>
      <div
        className="panel-resize-slot library-resize-slot"
        aria-hidden={!sidebarVisible}
        inert={!sidebarVisible ? true : undefined}
      >
        {!drawerLayout && <ResizeHandle label={t('resizeLibrary')} value={sidebarWidth} minimum={220} maximum={480} onResize={(delta) => setSidebarWidth((value) => clamp(value + delta, 220, 480))} />}
      </div>
      <main id="workspace-main" className="workspace-main" tabIndex={-1} inert={drawerPresent ? true : undefined}><DocumentWorkspace workspace={workspace} dark={theme === 'dark'} editorLineWrap={editorLineWrap} splitRatio={splitRatio} onSplitRatioChange={setSplitRatio} /></main>
      <div
        className="panel-resize-slot ai-resize-slot"
        aria-hidden={!aiVisible}
        inert={!aiVisible ? true : undefined}
      >
        {!drawerLayout && <ResizeHandle label={t('resizeAi')} direction={-1} value={aiWidth} minimum={320} maximum={520} onResize={(delta) => setAiWidth((value) => clamp(value + delta, 320, 520))} />}
      </div>
      <div
        className="panel-slot ai-panel-slot"
        aria-hidden={!aiVisible}
        inert={!aiVisible ? true : undefined}
      >
        {aiLoaded && <Suspense fallback={aiPresent ? <aside id="ai-panel" className="ai-panel ai-panel-loading" aria-label={t('ai')} aria-busy="true"><span>{t('loading')}</span></aside> : null}>
          <ChatPanel open={aiPresent} active={aiVisible} onClose={closeAi} contextFile={selectedFile} language={i18n.language} onFilesChanged={filesChanged} />
        </Suspense>}
      </div>
    </div>
    <Modal open={settingsOpen} title={t('settings')} onClose={closeSettings} size="large">
      <div className="modal-body settings-form">
        <section className="settings-section" aria-labelledby="settings-appearance">
          <div className="settings-section-heading">
            <h3 id="settings-appearance">{t('appearanceSection')}</h3>
            <p>{t('appearanceSectionHint')}</p>
          </div>
          <div className="settings-section-content">
            <label>{t('language')}<select name="interface-language" value={i18n.language} onChange={(event) => void changeLanguage(event.target.value)}>{languages.map((language) => <option value={language.id} key={language.id}>{language.label}</option>)}</select></label>
            <fieldset><legend>{t('theme')}</legend><div className="theme-options">{themes.map((value) => <label className={`theme-option ${theme === value ? 'selected' : ''}`} key={value}><input className="theme-radio" type="radio" name="theme" value={value} checked={theme === value} onChange={() => setTheme(value)} /><span className={`theme-swatch theme-${value}`} aria-hidden="true" /><span>{t(`theme${value[0]?.toUpperCase()}${value.slice(1)}`)}</span></label>)}</div></fieldset>
            <fieldset><legend>{t('interfaceDensity')}</legend><div className="preference-options compact-options">{DENSITY_PREFERENCES.map((value) => <label className={`preference-option ${density === value ? 'selected' : ''}`} key={value}><input type="radio" name="density" value={value} checked={density === value} onChange={() => setDensity(value)} /><span>{t(value === 'compact' ? 'densityCompact' : 'densityComfortable')}</span></label>)}</div></fieldset>
          </div>
        </section>

        <section className="settings-section" aria-labelledby="settings-reading">
          <div className="settings-section-heading">
            <h3 id="settings-reading">{t('readingSection')}</h3>
            <p>{t('readingSectionHint')}</p>
          </div>
          <div className="settings-section-content">
            <div className="range-setting">
              <label htmlFor="reading-font-size">{t('readingFontSize')}</label>
              <output htmlFor="reading-font-size">{t('fontSizeValue', { size: readingFontSize })}</output>
              <input id="reading-font-size" name="reading-font-size" type="range" min="14" max="20" step="1" value={readingFontSize} onChange={(event) => setReadingFontSize(Number(event.target.value))} />
            </div>
            <fieldset><legend>{t('readingLineHeight')}</legend><div className="preference-options">{READING_LINE_HEIGHTS.map((value) => <label className={`preference-option ${readingLineHeight === value ? 'selected' : ''}`} key={value}><input type="radio" name="reading-line-height" value={value} checked={readingLineHeight === value} onChange={() => setReadingLineHeight(value)} /><span>{t(value === 1.58 ? 'lineHeightCompact' : value === 1.78 ? 'lineHeightRelaxed' : 'lineHeightComfortable')}</span></label>)}</div></fieldset>
            <fieldset><legend>{t('readingWidth')}</legend><div className="preference-options reading-width-options">{READING_WIDTHS.map((value) => <label className={`preference-option ${readingWidth === value ? 'selected' : ''}`} key={value}><input type="radio" name="reading-width" value={value} checked={readingWidth === value} onChange={() => setReadingWidth(value)} /><span>{t(value === 64 ? 'widthNarrow' : value === 72 ? 'widthStandard' : value === 86 ? 'widthWide' : value === 'adaptive' ? 'widthAdaptive' : 'widthFluid')}</span></label>)}</div></fieldset>
          </div>
        </section>

        <section className="settings-section" aria-labelledby="settings-editor">
          <div className="settings-section-heading">
            <h3 id="settings-editor">{t('editorSection')}</h3>
            <p>{t('editorSectionHint')}</p>
          </div>
          <div className="settings-section-content">
            <div className="range-setting">
              <label htmlFor="editor-font-size">{t('editorFontSize')}</label>
              <output htmlFor="editor-font-size">{t('fontSizeValue', { size: editorFontSize })}</output>
              <input id="editor-font-size" name="editor-font-size" type="range" min="12" max="18" step="1" value={editorFontSize} onChange={(event) => setEditorFontSize(Number(event.target.value))} />
            </div>
            <label className="preference-toggle"><input type="checkbox" name="editor-line-wrap" checked={editorLineWrap} onChange={(event) => setEditorLineWrap(event.target.checked)} /><span><strong>{t('editorLineWrap')}</strong><small>{t('editorLineWrapHint')}</small></span></label>
          </div>
        </section>

        <div className="modal-actions settings-actions"><button className="button button-primary" onClick={closeSettings}>{t('confirm')}</button></div>
      </div>
    </Modal>
  </div>;
}
