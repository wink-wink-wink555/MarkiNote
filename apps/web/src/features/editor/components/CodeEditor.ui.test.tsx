import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import CodeEditor from './CodeEditor';

const rangeClientRectsDescriptor = Object.getOwnPropertyDescriptor(Range.prototype, 'getClientRects');
const rangeBoundingRectDescriptor = Object.getOwnPropertyDescriptor(Range.prototype, 'getBoundingClientRect');

beforeAll(() => {
  Object.defineProperty(Range.prototype, 'getClientRects', {
    configurable: true,
    value: () => [],
  });
  Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => new DOMRect(),
  });
});

afterAll(() => {
  if (rangeClientRectsDescriptor) {
    Object.defineProperty(Range.prototype, 'getClientRects', rangeClientRectsDescriptor);
  } else {
    delete (Range.prototype as Partial<Range>).getClientRects;
  }
  if (rangeBoundingRectDescriptor) {
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', rangeBoundingRectDescriptor);
  } else {
    delete (Range.prototype as Partial<Range>).getBoundingClientRect;
  }
});

afterEach(() => {
  delete document.documentElement.dataset.theme;
});

describe('CodeEditor accessibility', () => {
  it('uses a disabled-aware roving toolbar associated with the editor', async () => {
    render(<CodeEditor
      value=""
      onChange={vi.fn()}
      dark={false}
      label="Markdown source"
      onSave={vi.fn()}
    />);

    const toolbar = screen.getByRole('toolbar', { name: 'Markdown formatting toolbar' });
    const editorHost = screen.getByTestId('code-editor');
    expect(toolbar).toHaveAttribute('aria-controls', editorHost.id);

    const undo = screen.getByRole('button', { name: 'Undo' });
    const redo = screen.getByRole('button', { name: 'Redo' });
    const bold = screen.getByRole('button', { name: 'Bold' });
    const italic = screen.getByRole('button', { name: 'Italic' });
    const find = screen.getByRole('button', { name: 'Find in document' });
    expect(undo).toBeDisabled();
    expect(redo).toBeDisabled();
    expect(undo).toHaveAttribute('tabindex', '-1');
    expect(redo).toHaveAttribute('tabindex', '-1');
    expect(bold).toHaveAttribute('tabindex', '0');
    expect(undo).toHaveAttribute('aria-keyshortcuts', 'Control+Z');
    expect(undo).toHaveAttribute('title', 'Undo (Ctrl+Z)');

    bold.focus();
    fireEvent.keyDown(toolbar, { key: 'ArrowRight' });
    expect(italic).toHaveFocus();
    expect(italic).toHaveAttribute('tabindex', '0');

    fireEvent.keyDown(toolbar, { key: 'End' });
    expect(find).toHaveFocus();
    expect(find).toHaveAttribute('tabindex', '0');

    fireEvent.click(bold);
    await waitFor(() => expect(undo).toBeEnabled());
    undo.focus();
    fireEvent.click(undo);
    await waitFor(() => {
      expect(undo).toBeDisabled();
      expect(redo).toBeEnabled();
      expect(redo).toHaveAttribute('tabindex', '0');
    });
  });

  it('describes how keyboard users can leave the editor', () => {
    render(<CodeEditor
      value=""
      onChange={vi.fn()}
      dark={false}
      label="Markdown source"
      onSave={vi.fn()}
    />);

    expect(screen.getByRole('textbox', { name: 'Markdown source' })).toHaveAttribute(
      'aria-description',
      'Press Escape, then Tab to move focus out of the editor.',
    );
  });

  it('reconfigures its label and all four visual themes without replacing the editor view', async () => {
    document.documentElement.dataset.theme = 'light';
    const { rerender } = render(<CodeEditor
      value="# Heading"
      onChange={vi.fn()}
      dark={false}
      label="Markdown source"
      onSave={vi.fn()}
    />);
    const editor = document.querySelector<HTMLElement>('.cm-editor');
    expect(editor).toHaveAttribute('data-editor-theme', 'light');
    expect(editor?.querySelector('.cm-content')).toHaveClass('cm-lineWrapping');

    rerender(<CodeEditor
      value="# Heading"
      onChange={vi.fn()}
      dark={false}
      label="Source en Markdown"
      lineWrap={false}
      onSave={vi.fn()}
    />);
    expect(document.querySelector('.cm-editor')).toBe(editor);
    expect(screen.getByRole('textbox', { name: 'Source en Markdown' })).toBeInTheDocument();
    expect(editor?.querySelector('.cm-content')).not.toHaveClass('cm-lineWrapping');

    rerender(<CodeEditor
      value="# Heading"
      onChange={vi.fn()}
      dark={false}
      label="Source en Markdown"
      lineWrap
      onSave={vi.fn()}
    />);
    expect(document.querySelector('.cm-editor')).toBe(editor);
    expect(editor?.querySelector('.cm-content')).toHaveClass('cm-lineWrapping');

    for (const theme of ['dark', 'blue', 'pink'] as const) {
      act(() => { document.documentElement.dataset.theme = theme; });
      await waitFor(() => expect(editor).toHaveAttribute('data-editor-theme', theme));
      expect(document.querySelector('.cm-editor')).toBe(editor);
    }
  });

  it('renders distinct syntax colors for Markdown tokens', async () => {
    document.documentElement.dataset.theme = 'light';
    render(<CodeEditor
      value={'# Heading\n\n**strong** and `code` with [link](https://example.com)'}
      onChange={vi.fn()}
      dark={false}
      label="Markdown source"
      onSave={vi.fn()}
    />);

    const content = document.querySelector<HTMLElement>('.cm-content');
    await waitFor(() => expect(content?.querySelectorAll('span').length).toBeGreaterThan(3));
    const tokenColors = [...(content?.querySelectorAll<HTMLElement>('span') ?? [])]
      .map((token) => getComputedStyle(token).color)
      .filter(Boolean);
    expect(new Set(tokenColors).size).toBeGreaterThan(2);
  });

  it('opens an accessible, keyboard-ready find panel with live match feedback', async () => {
    render(<CodeEditor
      value={'# Heading\n\nAnother Heading'}
      onChange={vi.fn()}
      dark={false}
      label="Markdown source"
      onSave={vi.fn()}
    />);

    fireEvent.click(screen.getByRole('button', { name: 'Find in document' }));

    const panel = screen.getByRole('search', { name: 'Find in document' });
    expect(panel).toHaveClass('cm-search-panel');
    const query = screen.getByRole('searchbox', { name: 'Find' });
    expect(query).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Previous match' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next match' })).toBeDisabled();

    fireEvent.input(query, { target: { value: 'Heading' } });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('2 matches'));
    expect(screen.getByRole('button', { name: 'Next match' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Next match' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('1 of 2'));

    fireEvent.click(screen.getByRole('checkbox', { name: 'Regular expression' }));
    fireEvent.input(query, { target: { value: '[' } });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Invalid regular expression'));
    expect(query).toHaveAttribute('aria-invalid', 'true');

    const close = screen.getByRole('button', { name: 'Close find' });
    close.focus();
    fireEvent.click(close);
    expect(panel).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Markdown source' })).toHaveFocus();
  });

  it('reports capped match counts honestly for very repetitive documents', async () => {
    render(<CodeEditor
      value={'needle\n'.repeat(10_005)}
      onChange={vi.fn()}
      dark={false}
      label="Markdown source"
      onSave={vi.fn()}
    />);

    fireEvent.click(screen.getByRole('button', { name: 'Find in document' }));
    fireEvent.input(screen.getByRole('searchbox', { name: 'Find' }), { target: { value: 'needle' } });

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('10000+ matches'));
  });
});
