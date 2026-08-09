import { redo, undo } from '@codemirror/commands';
import { openSearchPanel } from '@codemirror/search';
import { EditorSelection } from '@codemirror/state';
import type { EditorView } from '@codemirror/view';

export type MarkdownToolbarAction = 'undo' | 'redo' | 'bold' | 'italic' | 'strikethrough' | 'inlineCode' | 'heading' | 'quote' | 'bulletList' | 'orderedList' | 'link' | 'codeBlock' | 'find';

function wrapSelection(view: EditorView, before: string, after = before, placeholder = 'text'): void {
  const transaction = view.state.changeByRange((range) => {
    const selected = view.state.sliceDoc(range.from, range.to);
    const selectedIncludesWrapper = selected.startsWith(before)
      && selected.endsWith(after)
      && selected.length >= before.length + after.length;
    if (selectedIncludesWrapper) {
      const content = selected.slice(before.length, selected.length - after.length);
      return {
        changes: { from: range.from, to: range.to, insert: content },
        range: EditorSelection.range(range.from, range.from + content.length),
      };
    }

    const wrapperFrom = range.from - before.length;
    const wrapperTo = range.to + after.length;
    if (
      wrapperFrom >= 0
      && wrapperTo <= view.state.doc.length
      && view.state.sliceDoc(wrapperFrom, range.from) === before
      && view.state.sliceDoc(range.to, wrapperTo) === after
    ) {
      return {
        changes: { from: wrapperFrom, to: wrapperTo, insert: selected },
        range: EditorSelection.range(wrapperFrom, wrapperFrom + selected.length),
      };
    }

    const content = selected || placeholder;
    const selectionStart = range.from + before.length;
    return {
      changes: { from: range.from, to: range.to, insert: `${before}${content}${after}` },
      range: EditorSelection.range(selectionStart, selectionStart + content.length),
    };
  });
  view.dispatch(transaction);
  view.focus();
}

interface LinePrefix {
  insert: string;
  match: (line: string) => string | null;
}

function selectedLines(view: EditorView, from: number, to: number) {
  const firstLine = view.state.doc.lineAt(from);
  const selectionEndsAtLineStart = to > from && view.state.doc.lineAt(to).from === to;
  const lastLine = view.state.doc.lineAt(selectionEndsAtLineStart ? to - 1 : to);
  return Array.from(
    { length: lastLine.number - firstLine.number + 1 },
    (_, index) => view.state.doc.line(firstLine.number + index),
  );
}

function prefixSelectedLines(view: EditorView, prefix: LinePrefix): void {
  const transaction = view.state.changeByRange((range) => {
    const lines = selectedLines(view, range.from, range.to);
    const matches = lines.map((line) => prefix.match(line.text));
    const shouldRemove = matches.every((match) => match !== null);
    const changes = lines.map((line, index) => {
      const matchedPrefix = matches[index] ?? '';
      return shouldRemove
        ? { from: line.from, to: line.from + matchedPrefix.length, insert: '' }
        : { from: line.from, to: line.from, insert: prefix.insert };
    });
    const firstDelta = shouldRemove ? -(matches[0]?.length ?? 0) : prefix.insert.length;
    const totalDelta = shouldRemove
      ? -matches.reduce((total, match) => total + (match?.length ?? 0), 0)
      : prefix.insert.length * lines.length;
    return {
      changes,
      range: EditorSelection.range(
        Math.max(lines[0]?.from ?? 0, range.from + firstDelta),
        Math.max(lines[0]?.from ?? 0, range.to + totalDelta),
      ),
    };
  });
  view.dispatch(transaction);
  view.focus();
}

const headingPrefix: LinePrefix = {
  insert: '## ',
  match: (line) => line.match(/^#{1,6}\s/)?.[0] ?? null,
};

const quotePrefix: LinePrefix = {
  insert: '> ',
  match: (line) => line.match(/^>\s?/)?.[0] ?? null,
};

const bulletListPrefix: LinePrefix = {
  insert: '- ',
  match: (line) => line.match(/^[-+*]\s/)?.[0] ?? null,
};

const orderedListPrefix: LinePrefix = {
  insert: '1. ',
  match: (line) => line.match(/^\d+[.)]\s/)?.[0] ?? null,
};

export function applyMarkdownToolbarAction(view: EditorView, action: MarkdownToolbarAction): void {
  switch (action) {
    case 'undo': undo(view); view.focus(); break;
    case 'redo': redo(view); view.focus(); break;
    case 'bold': wrapSelection(view, '**'); break;
    case 'italic': wrapSelection(view, '*'); break;
    case 'strikethrough': wrapSelection(view, '~~'); break;
    case 'inlineCode': wrapSelection(view, '`'); break;
    case 'heading': prefixSelectedLines(view, headingPrefix); break;
    case 'quote': prefixSelectedLines(view, quotePrefix); break;
    case 'bulletList': prefixSelectedLines(view, bulletListPrefix); break;
    case 'orderedList': prefixSelectedLines(view, orderedListPrefix); break;
    case 'link': wrapSelection(view, '[', '](url)'); break;
    case 'codeBlock': wrapSelection(view, '```\n', '\n```', ''); break;
    // openSearchPanel moves focus to its primary field. Do not immediately
    // steal focus back into the editor, or keyboard users cannot type a query.
    case 'find': openSearchPanel(view); break;
  }
}
