import { defaultKeymap, history, historyKeymap, indentWithTab, redoDepth, undoDepth } from '@codemirror/commands';
import { markdown } from '@codemirror/lang-markdown';
import { search, searchKeymap } from '@codemirror/search';
import { Annotation, Compartment, EditorSelection, EditorState, Transaction } from '@codemirror/state';
import { drawSelection, dropCursor, EditorView, highlightActiveLine, highlightActiveLineGutter, highlightSpecialChars, keymap, lineNumbers } from '@codemirror/view';
import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { editorTheme, readEditorTheme, type EditorThemeName } from '../theme/syntaxTheme';
import { createEditorSearchPanel, type EditorSearchLabels } from './editorSearchPanel';
import { applyMarkdownToolbarAction, type MarkdownToolbarAction } from './markdownToolbar';

interface RevealRequest { id: number; text: string }

interface Props {
  value: string;
  onChange: (value: string) => void;
  dark: boolean;
  label: string;
  onSave: () => void;
  lineWrap?: boolean;
  revealRequest?: RevealRequest | null;
  onRevealResult?: (found: boolean) => void;
}

const toolbarActions: ReadonlyArray<{ action: MarkdownToolbarAction; label: string; glyph: string }> = [
  { action: 'undo', label: 'formatUndo', glyph: '↶' },
  { action: 'redo', label: 'formatRedo', glyph: '↷' },
  { action: 'bold', label: 'formatBold', glyph: 'B' },
  { action: 'italic', label: 'formatItalic', glyph: 'I' },
  { action: 'strikethrough', label: 'formatStrikethrough', glyph: 'S' },
  { action: 'inlineCode', label: 'formatInlineCode', glyph: '</>' },
  { action: 'heading', label: 'formatHeading', glyph: 'H' },
  { action: 'quote', label: 'formatQuote', glyph: '“' },
  { action: 'bulletList', label: 'formatBulletList', glyph: '•' },
  { action: 'orderedList', label: 'formatOrderedList', glyph: '1.' },
  { action: 'link', label: 'formatLink', glyph: '↗' },
  { action: 'codeBlock', label: 'formatCodeBlock', glyph: '{ }' },
  { action: 'find', label: 'findInDocument', glyph: '⌕' },
];

interface HistoryAvailability {
  undo: number;
  redo: number;
}

const externalValueChange = Annotation.define<boolean>();

function editorContentAttributes(label: string, exitHint: string) {
  return EditorView.contentAttributes.of({
    'aria-label': label,
    'aria-description': exitHint,
    'aria-multiline': 'true',
  });
}

function isApplePlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent);
}

function toolbarShortcut(action: MarkdownToolbarAction, applePlatform: boolean): string | null {
  const modifier = applePlatform ? '⌘' : 'Ctrl+';
  switch (action) {
    case 'undo': return `${modifier}Z`;
    case 'redo': return applePlatform ? '⇧⌘Z' : 'Ctrl+Y';
    case 'bold': return `${modifier}B`;
    case 'italic': return `${modifier}I`;
    case 'find': return `${modifier}F`;
    default: return null;
  }
}

function toolbarAriaShortcut(action: MarkdownToolbarAction, applePlatform: boolean): string | undefined {
  const modifier = applePlatform ? 'Meta' : 'Control';
  switch (action) {
    case 'undo': return `${modifier}+Z`;
    case 'redo': return applePlatform ? 'Meta+Shift+Z' : 'Control+Y';
    case 'bold': return `${modifier}+B`;
    case 'italic': return `${modifier}+I`;
    case 'find': return `${modifier}+F`;
    default: return undefined;
  }
}

function isToolbarActionDisabled(action: MarkdownToolbarAction, availability: HistoryAvailability): boolean {
  return (action === 'undo' && availability.undo === 0)
    || (action === 'redo' && availability.redo === 0);
}

function enabledFallbackAction(action: MarkdownToolbarAction, availability: HistoryAvailability): MarkdownToolbarAction {
  if (action === 'undo' && availability.redo > 0) return 'redo';
  if (action === 'redo' && availability.undo > 0) return 'undo';
  const currentIndex = toolbarActions.findIndex((item) => item.action === action);
  for (let offset = 1; offset <= toolbarActions.length; offset += 1) {
    const candidate = toolbarActions[(currentIndex + offset) % toolbarActions.length]?.action;
    if (candidate && !isToolbarActionDisabled(candidate, availability)) return candidate;
  }
  return 'bold';
}

export default function CodeEditor({ value, onChange, dark, label, onSave, lineWrap = true, revealRequest, onRevealResult }: Props) {
  const { t } = useTranslation();
  const exitHint = t('editorExitHint');
  const searchLabels = useMemo<EditorSearchLabels>(() => ({
    title: t('findInDocument'),
    find: t('findQuery', { defaultValue: 'Find' }),
    replace: t('replaceQuery', { defaultValue: 'Replace with' }),
    previous: t('previousMatch', { defaultValue: 'Previous match' }),
    next: t('nextMatch', { defaultValue: 'Next match' }),
    selectAll: t('selectAllMatches', { defaultValue: 'Select all' }),
    matchCase: t('matchCase', { defaultValue: 'Match case' }),
    regularExpression: t('regularExpression', { defaultValue: 'Regular expression' }),
    wholeWord: t('wholeWord', { defaultValue: 'Whole word' }),
    replaceNext: t('replaceNext', { defaultValue: 'Replace' }),
    replaceAll: t('replaceAll', { defaultValue: 'Replace all' }),
    close: t('closeFind', { defaultValue: 'Close find' }),
    enterQuery: t('enterFindQuery', { defaultValue: 'Enter text to find' }),
    invalidExpression: t('invalidExpression', { defaultValue: 'Invalid regular expression' }),
    noMatches: t('noFindMatches', { defaultValue: 'No matches' }),
    matchTotal: (total) => t('findMatchTotal', { count: total, defaultValue: '{{count}} matches' }),
    matchOverflow: (minimum) => t('findMatchOverflow', { count: minimum, defaultValue: '{{count}}+ matches' }),
    matchPosition: (current, total) => t('findMatchPosition', {
      current,
      total,
      defaultValue: '{{current}} of {{total}}',
    }),
  }), [t]);
  const editorId = useId();
  const host = useRef<HTMLDivElement>(null);
  const toolbar = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const compartments = useRef<{
    attributes: Compartment;
    history: Compartment;
    lineWrapping: Compartment;
    theme: Compartment;
  } | null>(null);
  if (!compartments.current) {
    compartments.current = {
      attributes: new Compartment(),
      history: new Compartment(),
      lineWrapping: new Compartment(),
      theme: new Compartment(),
    };
  }
  const [activeToolbarAction, setActiveToolbarAction] = useState<MarkdownToolbarAction>('bold');
  const [historyAvailability, setHistoryAvailability] = useState<HistoryAvailability>({ undo: 0, redo: 0 });
  const valueRef = useRef(value);
  const darkRef = useRef(dark);
  const labelRef = useRef(label);
  const exitHintRef = useRef(exitHint);
  const lineWrapRef = useRef(lineWrap);
  const currentTheme = useRef<EditorThemeName | null>(null);
  const changeHandler = useRef(onChange);
  const saveHandler = useRef(onSave);
  const revealResultHandler = useRef(onRevealResult);
  const searchLabelsRef = useRef(searchLabels);
  valueRef.current = value; darkRef.current = dark; labelRef.current = label; exitHintRef.current = exitHint; lineWrapRef.current = lineWrap; changeHandler.current = onChange; saveHandler.current = onSave; revealResultHandler.current = onRevealResult;
  searchLabelsRef.current = searchLabels;

  useEffect(() => {
    if (!host.current) return undefined;
    const editorCompartments = compartments.current;
    if (!editorCompartments) return undefined;
    const initialTheme = readEditorTheme(darkRef.current);
    currentTheme.current = initialTheme;
    const syncHistoryAvailability = (state: EditorState) => {
      const next = { undo: undoDepth(state), redo: redoDepth(state) };
      setHistoryAvailability((previous) => (
        previous.undo === next.undo && previous.redo === next.redo ? previous : next
      ));
    };
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: valueRef.current,
        extensions: [
          lineNumbers(), highlightActiveLineGutter(), highlightSpecialChars(),
          editorCompartments.history.of(history()), drawSelection(), dropCursor(),
          highlightActiveLine(), markdown(),
          editorCompartments.theme.of(editorTheme(initialTheme)),
          editorCompartments.attributes.of(editorContentAttributes(labelRef.current, exitHintRef.current)),
          editorCompartments.lineWrapping.of(lineWrapRef.current ? EditorView.lineWrapping : []),
          search({ createPanel: (editorView) => createEditorSearchPanel(editorView, searchLabelsRef) }),
          keymap.of([
            { key: 'Mod-s', preventDefault: true, run: () => { saveHandler.current(); return true; } },
            { key: 'Mod-b', preventDefault: true, run: (editorView) => { applyMarkdownToolbarAction(editorView, 'bold'); return true; } },
            { key: 'Mod-i', preventDefault: true, run: (editorView) => { applyMarkdownToolbarAction(editorView, 'italic'); return true; } },
            indentWithTab, ...defaultKeymap, ...historyKeymap, ...searchKeymap,
          ]),
          EditorView.updateListener.of((update) => {
            const external = update.transactions.some((transaction) => transaction.annotation(externalValueChange));
            if (update.docChanged && !external) changeHandler.current(update.state.doc.toString());
            syncHistoryAvailability(update.state);
          }),
        ],
      }),
    });
    view.current = editor;
    syncHistoryAvailability(editor.state);
    const themeObserver = typeof MutationObserver === 'undefined'
      ? null
      : new MutationObserver(() => {
        const nextTheme = readEditorTheme(darkRef.current);
        if (currentTheme.current === nextTheme || view.current !== editor) return;
        currentTheme.current = nextTheme;
        editor.dispatch({ effects: editorCompartments.theme.reconfigure(editorTheme(nextTheme)) });
      });
    themeObserver?.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => {
      themeObserver?.disconnect();
      editor.destroy();
      if (view.current === editor) view.current = null;
    };
  }, []);

  useEffect(() => {
    // A no-op transaction lets an open, non-React CodeMirror panel refresh
    // its labels immediately when the application language changes.
    view.current?.dispatch({});
  }, [searchLabels]);

  useEffect(() => {
    const editor = view.current;
    const editorCompartments = compartments.current;
    if (!editor || !editorCompartments) return;
    editor.dispatch({ effects: editorCompartments.attributes.reconfigure(editorContentAttributes(label, exitHint)) });
  }, [exitHint, label]);

  useEffect(() => {
    const editor = view.current;
    const editorCompartments = compartments.current;
    if (!editor || !editorCompartments) return;
    editor.dispatch({
      effects: editorCompartments.lineWrapping.reconfigure(lineWrap ? EditorView.lineWrapping : []),
    });
  }, [lineWrap]);

  useEffect(() => {
    const editor = view.current;
    const editorCompartments = compartments.current;
    if (!editor || !editorCompartments) return;
    const nextTheme = readEditorTheme(dark);
    if (currentTheme.current === nextTheme) return;
    currentTheme.current = nextTheme;
    editor.dispatch({ effects: editorCompartments.theme.reconfigure(editorTheme(nextTheme)) });
  }, [dark]);

  useEffect(() => {
    const editor = view.current;
    if (!editor || editor.state.doc.toString() === value) return;
    const historyCompartment = compartments.current?.history;
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: value },
      annotations: [externalValueChange.of(true), Transaction.addToHistory.of(false)],
      effects: historyCompartment?.reconfigure(history()) ?? [],
    });
  }, [value]);

  useEffect(() => {
    const editor = view.current;
    const query = revealRequest?.text.trim() ?? '';
    if (!editor || !query) return;
    const from = editor.state.doc.toString().indexOf(query);
    if (from < 0) {
      revealResultHandler.current?.(false);
      return;
    }
    editor.dispatch({
      selection: EditorSelection.range(from, from + query.length),
      effects: EditorView.scrollIntoView(from, { y: 'center' }),
    });
    editor.focus();
    revealResultHandler.current?.(true);
  }, [revealRequest]);

  useEffect(() => {
    if (!isToolbarActionDisabled(activeToolbarAction, historyAvailability)) return;
    const hadToolbarFocus = toolbar.current?.contains(document.activeElement) ?? false;
    const fallback = enabledFallbackAction(activeToolbarAction, historyAvailability);
    setActiveToolbarAction(fallback);
    if (hadToolbarFocus) {
      queueMicrotask(() => {
        toolbar.current?.querySelector<HTMLButtonElement>(`[data-toolbar-action="${fallback}"]`)?.focus();
      });
    }
  }, [activeToolbarAction, historyAvailability]);

  const navigateToolbar = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...(toolbar.current?.querySelectorAll<HTMLButtonElement>('[data-toolbar-action]') ?? [])]
      .filter((button) => !button.disabled);
    if (!buttons.length) return;
    event.preventDefault();
    const focused = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const active = buttons.findIndex((button) => button.dataset.toolbarAction === activeToolbarAction);
    const current = focused >= 0 ? focused : Math.max(0, active);
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? buttons.length - 1
        : event.key === 'ArrowRight' ? (current + 1) % buttons.length
          : (current - 1 + buttons.length) % buttons.length;
    const button = buttons[next];
    if (!button) return;
    setActiveToolbarAction(button.dataset.toolbarAction as MarkdownToolbarAction);
    button.focus();
  };

  const applePlatform = isApplePlatform();

  return <div className="code-editor">
    <div
      ref={toolbar}
      className="editor-format-toolbar"
      role="toolbar"
      aria-label={t('editorToolbar')}
      aria-controls={editorId}
      onKeyDown={navigateToolbar}
    >
      {toolbarActions.map(({ action, label: labelKey, glyph }) => {
        const translatedLabel = t(labelKey);
        const shortcut = toolbarShortcut(action, applePlatform);
        const disabled = isToolbarActionDisabled(action, historyAvailability);
        return <button
          type="button"
          className={`editor-format-button touch-target has-tooltip format-${action}`}
          key={action}
          data-toolbar-action={action}
          disabled={disabled}
          tabIndex={activeToolbarAction === action && !disabled ? 0 : -1}
          aria-label={translatedLabel}
          aria-keyshortcuts={toolbarAriaShortcut(action, applePlatform)}
          title={shortcut ? `${translatedLabel} (${shortcut})` : translatedLabel}
          onFocus={() => setActiveToolbarAction(action)}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => { if (view.current) applyMarkdownToolbarAction(view.current, action); }}
        ><span aria-hidden="true">{glyph}</span></button>;
      })}
    </div>
    <div id={editorId} className="code-editor-host" ref={host} data-testid="code-editor" />
  </div>;
}
