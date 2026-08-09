import { history } from '@codemirror/commands';
import { EditorSelection, EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { afterEach, describe, expect, it } from 'vitest';
import { applyMarkdownToolbarAction, type MarkdownToolbarAction } from './markdownToolbar';

const views: EditorView[] = [];

function editor(doc: string, from = 0, to = doc.length): EditorView {
  const view = new EditorView({
    state: EditorState.create({
      doc,
      selection: EditorSelection.range(from, to),
      extensions: [history()],
    }),
  });
  views.push(view);
  return view;
}

afterEach(() => {
  for (const view of views.splice(0)) view.destroy();
});

describe('Markdown editor toolbar commands', () => {
  it.each<[MarkdownToolbarAction, string, string]>([
    ['bold', 'word', '**word**'],
    ['italic', 'word', '*word*'],
    ['strikethrough', 'word', '~~word~~'],
    ['inlineCode', 'word', '`word`'],
    ['heading', 'one\ntwo', '## one\n## two'],
    ['quote', 'one\ntwo', '> one\n> two'],
    ['bulletList', 'one\ntwo', '- one\n- two'],
    ['orderedList', 'one\ntwo', '1. one\n1. two'],
    ['link', 'word', '[word](url)'],
    ['codeBlock', 'word', '```\nword\n```'],
  ])('applies %s to the current selection', (action, source, expected) => {
    const view = editor(source);

    applyMarkdownToolbarAction(view, action);

    expect(view.state.doc.toString()).toBe(expected);
  });

  it.each<MarkdownToolbarAction>([
    'bold',
    'italic',
    'strikethrough',
    'inlineCode',
    'heading',
    'quote',
    'bulletList',
    'orderedList',
    'link',
    'codeBlock',
  ])('toggles %s off when the selection is already formatted', (action) => {
    const view = editor('word');

    applyMarkdownToolbarAction(view, action);
    applyMarkdownToolbarAction(view, action);

    expect(view.state.doc.toString()).toBe('word');
    expect(view.state.sliceDoc(
      view.state.selection.main.from,
      view.state.selection.main.to,
    )).toBe('word');
  });

  it.each<[MarkdownToolbarAction, string]>([
    ['heading', '### title'],
    ['quote', '> quote'],
    ['bulletList', '* item'],
    ['orderedList', '42) item'],
  ])('recognizes existing Markdown variants when toggling %s', (action, source) => {
    const view = editor(source);

    applyMarkdownToolbarAction(view, action);

    expect(view.state.doc.toString()).toBe(source.replace(/^(?:#{1,6}\s|>\s?|[-+*]\s|\d+[.)]\s)/, ''));
  });

  it('uses CodeMirror history for undo and redo', () => {
    const view = editor('word');
    applyMarkdownToolbarAction(view, 'bold');

    applyMarkdownToolbarAction(view, 'undo');
    expect(view.state.doc.toString()).toBe('word');

    applyMarkdownToolbarAction(view, 'redo');
    expect(view.state.doc.toString()).toBe('**word**');
  });
});
