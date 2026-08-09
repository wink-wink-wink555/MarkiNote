import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import type { Extension } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { tags } from '@lezer/highlight';

export type EditorThemeName = 'light' | 'dark' | 'blue' | 'pink';

interface EditorSyntaxPalette {
  caret: string;
  selection: string;
  search: string;
  searchSelected: string;
  heading: string;
  link: string;
  emphasis: string;
  strong: string;
  code: string;
  keyword: string;
  string: string;
  number: string;
  name: string;
  type: string;
  comment: string;
  meta: string;
  punctuation: string;
  invalid: string;
}

/*
 * CodeMirror's generated highlighting classes live outside the app stylesheet,
 * so syntax colors are kept as a small, semantic editor token set here.
 * Every light palette uses deliberately dark values for readable contrast.
 */
const syntaxPalettes: Record<EditorThemeName, EditorSyntaxPalette> = {
  light: {
    caret: '#0668c9',
    selection: '#c9e3ff',
    search: '#fff0a8',
    searchSelected: '#ffd56a',
    heading: '#075fae',
    link: '#075fae',
    emphasis: '#8a4b08',
    strong: '#71338f',
    code: '#a23124',
    keyword: '#6639a6',
    string: '#087365',
    number: '#9a4c00',
    name: '#9d174d',
    type: '#006d84',
    comment: '#596579',
    meta: '#87520a',
    punctuation: '#667085',
    invalid: '#b42318',
  },
  dark: {
    caret: '#8abbff',
    selection: '#315780',
    search: '#5c4b16',
    searchSelected: '#7b6118',
    heading: '#8abbff',
    link: '#86b9ff',
    emphasis: '#ffd084',
    strong: '#d8b4fe',
    code: '#ffaaa5',
    keyword: '#c4b5fd',
    string: '#75dfbd',
    number: '#ffc078',
    name: '#f9a8d4',
    type: '#78d9ec',
    comment: '#a8b1bf',
    meta: '#f6c177',
    punctuation: '#b5becc',
    invalid: '#ff99aa',
  },
  blue: {
    caret: '#075fae',
    selection: '#c2e0ff',
    search: '#ffefaa',
    searchSelected: '#ffd264',
    heading: '#0057a6',
    link: '#005eae',
    emphasis: '#854807',
    strong: '#683198',
    code: '#9f3023',
    keyword: '#6037a1',
    string: '#087063',
    number: '#914900',
    name: '#97184a',
    type: '#006b82',
    comment: '#526a82',
    meta: '#80500c',
    punctuation: '#5f7184',
    invalid: '#aa2431',
  },
  pink: {
    caret: '#a33562',
    selection: '#f1c6d8',
    search: '#ffeda7',
    searchSelected: '#ffd06a',
    heading: '#9a2d59',
    link: '#963159',
    emphasis: '#824707',
    strong: '#71338f',
    code: '#9f3024',
    keyword: '#65379a',
    string: '#0a7065',
    number: '#904800',
    name: '#99184d',
    type: '#006b80',
    comment: '#6d5863',
    meta: '#81500d',
    punctuation: '#75616b',
    invalid: '#aa243f',
  },
};

const editorThemeNames: readonly EditorThemeName[] = ['light', 'dark', 'blue', 'pink'];

export function readEditorTheme(darkFallback: boolean): EditorThemeName {
  if (typeof document !== 'undefined') {
    const theme = document.documentElement.dataset.theme;
    if (editorThemeNames.includes(theme as EditorThemeName)) return theme as EditorThemeName;
  }
  return darkFallback ? 'dark' : 'light';
}

export function editorTheme(theme: EditorThemeName): Extension {
  const palette = syntaxPalettes[theme];
  const highlightStyle = HighlightStyle.define([
    { tag: [tags.heading, tags.heading1, tags.heading2, tags.heading3, tags.heading4, tags.heading5, tags.heading6], color: palette.heading, fontWeight: '700' },
    { tag: [tags.link, tags.url], color: palette.link, textDecoration: 'underline', textUnderlinePosition: 'under' },
    { tag: tags.emphasis, color: palette.emphasis, fontStyle: 'italic' },
    { tag: tags.strong, color: palette.strong, fontWeight: '700' },
    { tag: [tags.monospace, tags.regexp, tags.escape], color: palette.code },
    { tag: [tags.keyword, tags.modifier, tags.controlKeyword, tags.definitionKeyword, tags.operatorKeyword], color: palette.keyword },
    { tag: [tags.string, tags.character, tags.attributeValue], color: palette.string },
    { tag: [tags.number, tags.bool, tags.null, tags.atom], color: palette.number },
    { tag: [tags.variableName, tags.propertyName, tags.attributeName, tags.labelName], color: palette.name },
    { tag: [tags.typeName, tags.className, tags.namespace, tags.tagName], color: palette.type },
    { tag: [tags.comment, tags.docComment], color: palette.comment, fontStyle: 'italic' },
    { tag: [tags.meta, tags.documentMeta, tags.annotation, tags.processingInstruction], color: palette.meta },
    { tag: [tags.punctuation, tags.bracket, tags.separator, tags.list, tags.quote], color: palette.punctuation },
    { tag: tags.strikethrough, textDecoration: 'line-through' },
    { tag: tags.invalid, color: palette.invalid, textDecoration: 'underline wavy' },
  ]);

  return [
    EditorView.editorAttributes.of({ 'data-editor-theme': theme }),
    EditorView.theme({
      '&': {
        color: 'var(--text)',
        backgroundColor: 'var(--surface)',
      },
      '.cm-content': {
        caretColor: palette.caret,
      },
      '.cm-cursor, .cm-dropCursor': {
        borderLeftColor: palette.caret,
      },
      '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
        backgroundColor: palette.selection,
      },
      '.cm-searchMatch': {
        backgroundColor: palette.search,
        outline: `1px solid ${palette.searchSelected}`,
      },
      '.cm-searchMatch.cm-searchMatch-selected': {
        backgroundColor: palette.searchSelected,
      },
      '.cm-panel.cm-search-panel': {
        padding: '8px 10px',
        display: 'grid',
        gap: '7px',
        borderBottom: '1px solid var(--border)',
        backgroundColor: 'var(--surface-muted)',
        color: 'var(--text)',
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--font-size-caption)',
      },
      '.cm-search-main-row, .cm-search-secondary-row, .cm-search-replace-row': {
        minWidth: '0',
        display: 'flex',
        alignItems: 'center',
        gap: '7px',
        flexWrap: 'wrap',
      },
      '.cm-search-field': {
        minWidth: 'min(210px, 100%)',
        flex: '1 1 250px',
        display: 'grid',
        gridTemplateColumns: 'max-content minmax(100px, 1fr)',
        alignItems: 'center',
        gap: '7px',
        color: 'var(--text-muted)',
        fontWeight: '600',
      },
      '.cm-search-field-label': {
        whiteSpace: 'nowrap',
      },
      '.cm-search-panel .cm-textfield': {
        width: '100%',
        minWidth: '0',
        height: '32px',
        padding: '0 9px',
        border: '1px solid var(--border-strong)',
        borderRadius: '6px',
        outline: 'none',
        backgroundColor: 'var(--surface)',
        color: 'var(--text)',
        font: 'inherit',
      },
      '.cm-search-panel .cm-textfield:focus-visible': {
        borderColor: palette.caret,
        boxShadow: `0 0 0 2px color-mix(in srgb, ${palette.caret} 22%, transparent)`,
      },
      '.cm-search-navigation, .cm-search-replace-actions, .cm-search-options': {
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
      },
      '.cm-search-panel .cm-search-action, .cm-search-panel .cm-search-close': {
        minWidth: '32px',
        minHeight: '32px',
        padding: '0 9px',
        border: '1px solid var(--border)',
        borderRadius: '6px',
        background: 'var(--surface)',
        color: 'var(--text-muted)',
        font: '600 var(--font-size-caption)/1 var(--font-sans)',
        cursor: 'pointer',
      },
      '.cm-search-panel .cm-search-action:hover:not(:disabled), .cm-search-panel .cm-search-action:focus-visible, .cm-search-panel .cm-search-close:hover, .cm-search-panel .cm-search-close:focus-visible': {
        borderColor: 'var(--border-strong)',
        backgroundColor: 'var(--surface-hover)',
        color: 'var(--text)',
        outline: 'none',
      },
      '.cm-search-panel .cm-search-action:focus-visible, .cm-search-panel .cm-search-close:focus-visible': {
        boxShadow: `0 0 0 2px color-mix(in srgb, ${palette.caret} 22%, transparent)`,
      },
      '.cm-search-panel .cm-search-action:disabled': {
        opacity: '.48',
        cursor: 'not-allowed',
      },
      '.cm-search-panel .cm-search-icon-action': {
        paddingInline: '0',
        fontSize: '16px',
      },
      '.cm-search-panel .cm-search-close': {
        marginLeft: 'auto',
        borderColor: 'transparent',
        backgroundColor: 'transparent',
        fontSize: '18px',
      },
      '.cm-search-options': {
        flexWrap: 'wrap',
        gap: '8px 12px',
      },
      '.cm-search-option': {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        color: 'var(--text-muted)',
        whiteSpace: 'nowrap',
        cursor: 'pointer',
      },
      '.cm-search-option input': {
        width: '15px',
        height: '15px',
        margin: '0',
        accentColor: palette.caret,
      },
      '.cm-search-status': {
        minHeight: '18px',
        marginLeft: 'auto',
        color: 'var(--text-faint)',
        whiteSpace: 'nowrap',
      },
      '.cm-search-replace-row': {
        paddingTop: '1px',
      },
      '@media (pointer: coarse)': {
        '.cm-search-panel .cm-textfield': {
          minHeight: '44px',
        },
        '.cm-search-panel .cm-search-action, .cm-search-panel .cm-search-close': {
          minWidth: '44px',
          minHeight: '44px',
        },
        '.cm-search-option': {
          minHeight: '44px',
          padding: '0 4px',
        },
        '.cm-search-option input': {
          width: '18px',
          height: '18px',
        },
      },
      '.cm-matchingBracket': {
        backgroundColor: palette.selection,
        outline: `1px solid ${palette.caret}`,
      },
    }, { dark: theme === 'dark' }),
    syntaxHighlighting(highlightStyle),
  ];
}
