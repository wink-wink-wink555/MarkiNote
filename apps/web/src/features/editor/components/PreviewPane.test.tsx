import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import renderMathInElement from 'katex/contrib/auto-render';
import mermaid from 'mermaid';
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PreviewPane } from './PreviewPane';

vi.mock('katex/contrib/auto-render', () => ({
  default: vi.fn((element: HTMLElement) => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const textNodes: Text[] = [];
    while (walker.nextNode()) {
      if (walker.currentNode instanceof Text && !walker.currentNode.parentElement?.closest('pre, code')) {
        textNodes.push(walker.currentNode);
      }
    }
    const formulaPattern = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$)/gu;
    for (const textNode of textNodes) {
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      for (const match of textNode.data.matchAll(formulaPattern)) {
        const raw = match[0];
        const start = match.index;
        fragment.append(textNode.data.slice(cursor, start));
        const katex = document.createElement('span');
        katex.className = 'katex';
        katex.textContent = 'rendered formula';
        if (raw.startsWith('$$') || raw.startsWith('\\[')) {
          const display = document.createElement('span');
          display.className = 'katex-display';
          display.append(katex);
          fragment.append(display);
        } else fragment.append(katex);
        cursor = start + raw.length;
      }
      if (cursor > 0) {
        fragment.append(textNode.data.slice(cursor));
        textNode.replaceWith(fragment);
      }
    }
  }),
}));
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    run: vi.fn(({ nodes }: { nodes: HTMLElement[] }) => {
      for (const node of nodes) {
        if (node.textContent?.includes('invalid diagram')) return Promise.reject(new Error('invalid'));
        node.innerHTML = '<svg viewBox="0 0 100 50"></svg>';
      }
      return Promise.resolve();
    }),
  },
}));

describe('PreviewPane actions', () => {
  const writeText = vi.fn<() => Promise<void>>();

  beforeEach(() => {
    writeText.mockResolvedValue(undefined);
    vi.mocked(renderMathInElement).mockClear();
    vi.mocked(mermaid.initialize).mockClear();
    vi.mocked(mermaid.run).mockClear();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  });

  it('does not initialize KaTeX for an ordinary document without formulas', async () => {
    render(<PreviewPane html="<p>A regular document with code-like prose.</p>" dark={false} />);

    expect(await screen.findByText('A regular document with code-like prose.')).toBeInTheDocument();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(renderMathInElement).not.toHaveBeenCalled();
  });

  it('copies a rendered code block without logging its contents', async () => {
    render(<PreviewPane html={'<pre><code class="language-ts">const secret = 1;</code></pre>'} dark={false} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Copy code' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('const secret = 1;'));
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('copies Pygments-highlighted blocks that do not contain a code wrapper', async () => {
    render(<PreviewPane html={'<div class="highlight"><pre><span class="k">const</span> answer = <span class="mi">42</span>;</pre></div>'} dark={false} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Copy code' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('const answer = 42;'));
  });

  it('offers source copy and PNG export for a Mermaid diagram', async () => {
    render(<PreviewPane html={'<pre><code class="language-mermaid">graph TD; A--&gt;B</code></pre>'} dark />);

    expect(await screen.findByRole('button', { name: 'Copy code' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export Mermaid diagram as PNG' })).toBeInTheDocument();
  });

  it('isolates an invalid Mermaid diagram while rendering the valid diagrams around it', async () => {
    render(<PreviewPane
      html={[
        '<pre><code class="language-mermaid">graph TD; A--&gt;B</code></pre>',
        '<pre><code class="language-mermaid">invalid diagram</code></pre>',
        '<pre><code class="language-mermaid">sequenceDiagram; A-&gt;&gt;B: hello</code></pre>',
      ].join('')}
      dark={false}
    />);

    await waitFor(() => expect(screen.getAllByRole('img', { name: 'Mermaid diagram' })).toHaveLength(2));
    expect(screen.getByText('This Mermaid diagram is invalid. Its source is preserved for review.')).toBeInTheDocument();
    expect(screen.getByText('invalid diagram')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Copy code' })).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: 'Export Mermaid diagram as PNG' })).toHaveLength(2);
  });

  it('preserves inline and display LaTeX sources with StrictMode-safe accessible copy actions', async () => {
    const html = '<p>Inline $E = mc^2$.</p><div>$$\\sum_{i=1}^{n} i$$</div>';
    const { rerender } = render(<StrictMode><PreviewPane html={html} dark={false} /></StrictMode>);

    const originalButtons = await screen.findAllByRole('button', { name: 'Copy LaTeX formula' });
    expect(originalButtons).toHaveLength(2);
    const originalInlineButton = originalButtons[0];
    if (!originalInlineButton) throw new Error('Inline formula copy action was not rendered');
    fireEvent.click(originalInlineButton);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('$E = mc^2$'));

    rerender(<StrictMode><PreviewPane html={html} dark /></StrictMode>);
    await waitFor(() => expect(originalInlineButton.isConnected).toBe(false));
    const currentButtons = await screen.findAllByRole('button', { name: 'Copy LaTeX formula' });
    expect(currentButtons).toHaveLength(2);
    const currentDisplayButton = currentButtons[1];
    if (!currentDisplayButton) throw new Error('Display formula copy action was not rendered');
    writeText.mockClear();
    fireEvent.click(originalInlineButton);
    expect(writeText).not.toHaveBeenCalled();
    fireEvent.click(currentDisplayButton);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('$$\\sum_{i=1}^{n} i$$'));
  });

  it('reports formula clipboard failure without logging the formula body', async () => {
    const formula = '$private-formula-source$';
    writeText.mockRejectedValueOnce(new Error(formula));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(<PreviewPane html={`<p>${formula}</p>`} dark={false} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Copy LaTeX formula' }));

    expect(await screen.findByRole('button', { name: 'Copy failed' })).toBeInTheDocument();
    expect(JSON.stringify([...warn.mock.calls, ...error.mock.calls])).not.toContain(formula);
  });

  it('provides accessible copy, safe Bing search, and source-find actions for selected preview text', async () => {
    const findInSource = vi.fn();
    const openedWindow = { opener: window } as unknown as Window;
    const open = vi.spyOn(window, 'open').mockReturnValue(openedWindow);
    render(<PreviewPane html="<p>selected text</p>" dark={false} onFindInSource={findInSource} />);
    const selectParagraph = () => {
      const paragraph = screen.getByText('selected text');
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      return paragraph;
    };

    fireEvent.contextMenu(selectParagraph(), { clientX: 20, clientY: 30 });
    expect(await screen.findByRole('menu', { name: 'Selected text actions' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Copy selection' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('selected text'));
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());

    fireEvent.contextMenu(selectParagraph(), { clientX: 20, clientY: 30 });
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Search with Bing' }));
    expect(open).toHaveBeenCalledWith('https://www.bing.com/search?q=selected%20text&setlang=en-US', '_blank', 'noopener,noreferrer');
    expect(openedWindow.opener).toBeNull();
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());

    fireEvent.contextMenu(selectParagraph(), { clientX: 20, clientY: 30 });
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Find in source' }));
    expect(findInSource).toHaveBeenCalledWith('selected text');
  });

  it('portals the selection menu and restores focus to the preview on Escape', async () => {
    render(<PreviewPane html="<p>keyboard selected text</p>" dark={false} />);
    const paragraph = screen.getByText('keyboard selected text');
    const article = paragraph.closest('article');
    if (!article) throw new Error('Preview article was not rendered');
    article.focus();
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);

    fireEvent.contextMenu(article, { clientX: 40, clientY: 50 });
    const menu = await screen.findByRole('menu');
    expect(menu.parentElement).toBe(document.body);
    expect(screen.getByRole('menuitem', { name: 'Copy selection' })).toHaveFocus();

    fireEvent.keyDown(menu, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(article).toHaveFocus();
  });

  it('adds resilient long-content wrappers and native image loading hints', async () => {
    const { container } = render(<PreviewPane
      html={'<table><tbody><tr><td>Wide content</td></tr></tbody></table><img src="/image.png" alt="Example" />'}
      dark={false}
    />);

    await waitFor(() => expect(container.querySelector('.preview-table-scroll > table')).toBeInTheDocument());
    const image = screen.getByRole('img', { name: 'Example' });
    expect(image).toHaveAttribute('loading', 'lazy');
    expect(image).toHaveAttribute('decoding', 'async');
  });

  it('reuses bounded natural image dimensions on later preview renders', async () => {
    const html = '<img src="/cached-image-unique.png" alt="Cached example" />';
    const { rerender } = render(<PreviewPane html={html} dark={false} />);
    const firstImage = await screen.findByRole('img', { name: 'Cached example' });
    Object.defineProperty(firstImage, 'naturalWidth', { configurable: true, value: 1_280 });
    Object.defineProperty(firstImage, 'naturalHeight', { configurable: true, value: 720 });

    fireEvent.load(firstImage);
    expect(firstImage).toHaveAttribute('width', '1280');
    expect(firstImage).toHaveAttribute('height', '720');

    rerender(<PreviewPane html={html} dark />);
    const currentImage = await screen.findByRole('img', { name: 'Cached example' });
    expect(currentImage).not.toBe(firstImage);
    expect(currentImage).toHaveAttribute('width', '1280');
    expect(currentImage).toHaveAttribute('height', '720');
    expect(currentImage).toHaveAttribute('loading', 'lazy');
    expect(currentImage).toHaveAttribute('decoding', 'async');
  });

  it('preserves relative preview scroll when a rerender materially changes document height', async () => {
    const { container, rerender } = render(<div className="preview-pane">
      <PreviewPane html="<p>First document</p>" dark={false} />
    </div>);
    const scroller = container.querySelector<HTMLElement>('.preview-pane');
    if (!scroller) throw new Error('Preview scroller was not rendered');
    Object.defineProperties(scroller, {
      clientHeight: { configurable: true, value: 200 },
      clientWidth: { configurable: true, value: 400 },
      scrollHeight: {
        configurable: true,
        get: () => scroller.textContent?.includes('Second document') ? 1_800 : 1_000,
      },
      scrollWidth: { configurable: true, value: 400 },
    });
    scroller.scrollTop = 400;

    rerender(<div className="preview-pane">
      <PreviewPane html="<p>Second document</p>" dark={false} />
    </div>);

    await screen.findByText('Second document');
    await waitFor(() => expect(scroller.scrollTop).toBe(800));
  });

  it('does not write rich-preview failures or document contents to the console', async () => {
    const secret = 'private-mermaid-source';
    vi.mocked(mermaid.run).mockImplementationOnce(() => Promise.reject(new Error(secret)));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    render(<PreviewPane html={`<pre><code class="language-mermaid">${secret}</code></pre>`} dark={false} />);

    expect(await screen.findByText('This Mermaid diagram is invalid. Its source is preserved for review.')).toBeInTheDocument();
    expect(warn).not.toHaveBeenCalled();
    expect(JSON.stringify(warn.mock.calls)).not.toContain(secret);
  });
});
