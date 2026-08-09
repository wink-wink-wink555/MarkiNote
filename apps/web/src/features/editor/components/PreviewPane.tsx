import DOMPurify from 'dompurify';
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

const MAX_EXPORT_DIMENSION = 4096;
const MAX_MERMAID_DISPLAY_WIDTH = 2_400;
const ACTION_RESET_DELAY = 1_400;
const IMAGE_DIMENSION_CACHE_LIMIT = 96;
const IMAGE_DIMENSION_CACHE_KEY_LIMIT = 2_048;
const MERMAID_CONFIG = {
  startOnLoad: false,
  securityLevel: 'strict',
  logLevel: 'fatal',
  suppressErrorRendering: true,
} as const;
const MATH_DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '\\[', right: '\\]', display: true },
  { left: '\\(', right: '\\)', display: false },
  { left: '$', right: '$', display: false },
];
const MATH_IGNORED_TAGS = new Set(['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option']);

interface PreviewPaneProps {
  html: string;
  dark: boolean;
  onFindInSource?: (text: string) => void;
}

interface SelectionMenu {
  text: string;
  x: number;
  y: number;
}

interface MathSource {
  raw: string;
  display: boolean;
}

interface ImageDimensions {
  width: number;
  height: number;
}

interface PreviewScrollSnapshot {
  top: number;
  left: number;
  maxTop: number;
  maxLeft: number;
}

/**
 * A small LRU cache lets recurring preview renders reserve image space before
 * the resource loads again. Entries are intentionally bounded because source
 * URLs can be user-controlled and a document may reference many images.
 */
const imageDimensionCache = new Map<string, ImageDimensions>();

function imageDimensionCacheKey(image: HTMLImageElement): string | null {
  const source = image.getAttribute('src')?.trim();
  if (!source) return null;
  const key = `${source}\n${image.getAttribute('srcset') ?? ''}\n${image.getAttribute('sizes') ?? ''}`;
  return key.length <= IMAGE_DIMENSION_CACHE_KEY_LIMIT ? key : null;
}

function cachedImageDimensions(key: string): ImageDimensions | undefined {
  const dimensions = imageDimensionCache.get(key);
  if (!dimensions) return undefined;
  imageDimensionCache.delete(key);
  imageDimensionCache.set(key, dimensions);
  return dimensions;
}

function cacheImageDimensions(key: string, dimensions: ImageDimensions): void {
  imageDimensionCache.delete(key);
  imageDimensionCache.set(key, dimensions);
  while (imageDimensionCache.size > IMAGE_DIMENSION_CACHE_LIMIT) {
    const oldest = imageDimensionCache.keys().next().value;
    if (typeof oldest !== 'string') break;
    imageDimensionCache.delete(oldest);
  }
}

function previewScroller(element: HTMLElement): HTMLElement | null {
  return element.closest<HTMLElement>('.preview-pane') ?? element.parentElement;
}

function capturePreviewScroll(scroller: HTMLElement): PreviewScrollSnapshot {
  return {
    top: scroller.scrollTop,
    left: scroller.scrollLeft,
    maxTop: Math.max(0, scroller.scrollHeight - scroller.clientHeight),
    maxLeft: Math.max(0, scroller.scrollWidth - scroller.clientWidth),
  };
}

function restoredScrollOffset(
  offset: number,
  previousMaximum: number,
  nextMaximum: number,
  viewportSize: number,
): number {
  if (nextMaximum <= 0) return 0;
  if (previousMaximum <= 0) return Math.min(offset, nextMaximum);
  const sizeChangedMaterially = Math.abs(nextMaximum - previousMaximum)
    > Math.max(viewportSize, previousMaximum * 0.1);
  return sizeChangedMaterially
    ? Math.min(nextMaximum, Math.max(0, (offset / previousMaximum) * nextMaximum))
    : Math.min(offset, nextMaximum);
}

function restorePreviewScroll(scroller: HTMLElement, snapshot: PreviewScrollSnapshot): void {
  const nextMaxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  const nextMaxLeft = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
  scroller.scrollTop = restoredScrollOffset(
    snapshot.top,
    snapshot.maxTop,
    nextMaxTop,
    scroller.clientHeight,
  );
  scroller.scrollLeft = restoredScrollOffset(
    snapshot.left,
    snapshot.maxLeft,
    nextMaxLeft,
    scroller.clientWidth,
  );
}

function findMathEnd(rightDelimiter: string, text: string, startIndex: number): number {
  let braceLevel = 0;
  for (let index = startIndex; index < text.length; index += 1) {
    if (braceLevel <= 0 && text.startsWith(rightDelimiter, index)) return index + rightDelimiter.length;
    if (text[index] === '\\') index += 1;
    else if (text[index] === '{') braceLevel += 1;
    else if (text[index] === '}') braceLevel -= 1;
  }
  return -1;
}

function mathSourcesInText(value: string): MathSource[] {
  const sources: MathSource[] = [];
  let text = value;
  while (text) {
    let delimiter: (typeof MATH_DELIMITERS)[number] | undefined;
    let delimiterIndex = -1;
    for (const candidate of MATH_DELIMITERS) {
      const index = text.indexOf(candidate.left);
      if (index >= 0 && (delimiterIndex < 0 || index < delimiterIndex)) {
        delimiter = candidate;
        delimiterIndex = index;
      }
    }
    if (!delimiter) break;
    text = text.slice(delimiterIndex);
    const endIndex = findMathEnd(delimiter.right, text, delimiter.left.length);
    if (endIndex < 0) break;
    sources.push({ raw: text.slice(0, endIndex), display: delimiter.display });
    text = text.slice(endIndex);
  }
  return sources;
}

/** Collect formula source in the same text-node order used by KaTeX auto-render. */
function collectMathSources(root: Element): MathSource[] {
  const sources: MathSource[] = [];
  const visit = (parent: Element) => {
    for (let index = 0; index < parent.childNodes.length; index += 1) {
      const child = parent.childNodes[index];
      if (child?.nodeType === Node.TEXT_NODE) {
        let text = child.textContent ?? '';
        let sibling = child.nextSibling;
        let adjacentTextNodes = 0;
        while (sibling?.nodeType === Node.TEXT_NODE) {
          text += sibling.textContent ?? '';
          sibling = sibling.nextSibling;
          adjacentTextNodes += 1;
        }
        sources.push(...mathSourcesInText(text));
        index += adjacentTextNodes;
      } else if (child instanceof Element && !MATH_IGNORED_TAGS.has(child.tagName.toLowerCase())) {
        visit(child);
      }
    }
  };
  visit(root);
  return sources;
}

async function exportDiagramAsPng(svg: SVGSVGElement): Promise<void> {
  const viewBox = svg.viewBox.baseVal;
  const bounds = svg.getBoundingClientRect();
  const width = Math.max(1, Math.ceil(viewBox.width || bounds.width || 800));
  const height = Math.max(1, Math.ceil(viewBox.height || bounds.height || 600));
  const scale = Math.min(2, MAX_EXPORT_DIMENSION / width, MAX_EXPORT_DIMENSION / height);
  const exportSvg = svg.cloneNode(true) as SVGSVGElement;
  exportSvg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  exportSvg.setAttribute('width', String(width));
  exportSvg.setAttribute('height', String(height));
  const serialized = new XMLSerializer().serializeToString(exportSvg);
  const sourceUrl = URL.createObjectURL(new Blob([serialized], { type: 'image/svg+xml;charset=utf-8' }));

  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => { image.onload = null; image.onerror = null; resolve(); };
      image.onerror = () => { image.onload = null; image.onerror = null; reject(new Error('Unable to render Mermaid SVG')); };
      image.src = sourceUrl;
    });
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(width * scale);
    canvas.height = Math.ceil(height * scale);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas rendering is unavailable');
    const background = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff';
    context.fillStyle = background;
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const png = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error('Unable to encode Mermaid PNG')),
      'image/png',
    ));
    const downloadUrl = URL.createObjectURL(png);
    try {
      const anchor = document.createElement('a');
      anchor.href = downloadUrl;
      anchor.download = 'markinote-mermaid.png';
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    } finally {
      URL.revokeObjectURL(downloadUrl);
    }
  } finally {
    URL.revokeObjectURL(sourceUrl);
  }
}

export function PreviewPane({ html, dark, onFindInSource }: PreviewPaneProps) {
  const { t, i18n } = useTranslation();
  const root = useRef<HTMLElement>(null);
  const menuRoot = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const scrollSnapshot = useRef<PreviewScrollSnapshot | null>(null);
  const [selectionMenu, setSelectionMenu] = useState<SelectionMenu | null>(null);
  const [selectionActionError, setSelectionActionError] = useState('');
  const [richRenderError, setRichRenderError] = useState('');
  const language = i18n.resolvedLanguage ?? i18n.language;
  const deferredHtml = useDeferredValue(html);
  const safeHtml = useMemo(
    () => DOMPurify.sanitize(deferredHtml, { ADD_TAGS: ['mjx-container'], ADD_ATTR: ['display'] }),
    [deferredHtml],
  );

  const closeSelectionMenu = useCallback((restoreFocus: boolean) => {
    setSelectionMenu(null);
    setSelectionActionError('');
    if (restoreFocus) returnFocus.current?.focus();
  }, []);

  useEffect(() => {
    if (!selectionMenu) return undefined;
    menuRoot.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !menuRoot.current?.contains(event.target)) closeSelectionMenu(false);
    };
    const closeOnScroll = () => closeSelectionMenu(false);
    document.addEventListener('pointerdown', closeOutside);
    window.addEventListener('blur', closeOnScroll);
    window.addEventListener('scroll', closeOnScroll, true);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      window.removeEventListener('blur', closeOnScroll);
      window.removeEventListener('scroll', closeOnScroll, true);
    };
  }, [closeSelectionMenu, selectionMenu]);

  useLayoutEffect(() => {
    const menu = menuRoot.current;
    if (!menu || !selectionMenu) return;
    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(selectionMenu.x, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(selectionMenu.y, window.innerHeight - rect.height - 8));
    if (left !== selectionMenu.x || top !== selectionMenu.y) {
      setSelectionMenu((current) => current ? { ...current, x: left, y: top } : current);
    }
  }, [selectionMenu]);

  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return undefined;
    const scroller = previewScroller(element);
    // React StrictMode intentionally replays effects in development. Rebuild the
    // sanitized source DOM so each replay can enhance Mermaid, KaTeX, and code
    // blocks independently instead of inheriting half-enhanced nodes.
    element.innerHTML = safeHtml;
    if (scroller && scrollSnapshot.current) restorePreviewScroll(scroller, scrollSnapshot.current);
    return () => {
      if (scroller) scrollSnapshot.current = capturePreviewScroll(scroller);
    };
  }, [dark, language, safeHtml]);

  useEffect(() => {
    const element = root.current;
    if (!element) return undefined;
    setRichRenderError('');
    if (!safeHtml) return undefined;
    let disposed = false;
    const cleanups: Array<() => void> = [];
    const timers: number[] = [];
    const mathSources = collectMathSources(element);

    const resetButtonLater = (button: HTMLButtonElement, label: string, text: string) => {
      timers.push(window.setTimeout(() => {
        if (!disposed && button.isConnected) {
          button.disabled = false;
          button.textContent = text;
          button.setAttribute('aria-label', label);
          button.title = label;
        }
      }, ACTION_RESET_DELAY));
    };
    const addCopyButton = (
      parent: HTMLElement,
      source: () => string,
      className: string,
      label = t('copyCode'),
      text = label,
    ) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `button button-small rich-preview-action ${className}`;
      button.textContent = text;
      button.setAttribute('aria-label', label);
      button.title = label;
      const copy = async () => {
        button.disabled = true;
        try {
          if (!navigator.clipboard?.writeText) throw new Error('Clipboard is unavailable');
          await navigator.clipboard.writeText(source());
          button.textContent = t('copied');
          button.setAttribute('aria-label', t('copied'));
        } catch {
          button.textContent = t('copyFailed');
          button.setAttribute('aria-label', t('copyFailed'));
        }
        resetButtonLater(button, label, text);
      };
      const onClick = () => { void copy(); };
      button.addEventListener('click', onClick);
      cleanups.push(() => button.removeEventListener('click', onClick));
      parent.append(button);
    };

    for (const pre of element.querySelectorAll<HTMLPreElement>('pre')) {
      const code = pre.querySelector<HTMLElement>(':scope > code');
      if (code?.classList.contains('language-mermaid')) continue;
      const source = (code ?? pre).textContent ?? '';
      pre.classList.add('preview-code-block');
      addCopyButton(pre, () => source, 'code-copy');
    }

    for (const image of element.querySelectorAll<HTMLImageElement>('img')) {
      image.setAttribute('loading', 'lazy');
      image.setAttribute('decoding', 'async');
      const cacheKey = imageDimensionCacheKey(image);
      const authoredDimensions = image.hasAttribute('width') || image.hasAttribute('height');
      if (cacheKey && !authoredDimensions) {
        const dimensions = cachedImageDimensions(cacheKey);
        if (dimensions) {
          image.setAttribute('width', String(dimensions.width));
          image.setAttribute('height', String(dimensions.height));
        }
      }
      if (cacheKey) {
        const rememberDimensions = () => {
          const width = Math.round(image.naturalWidth);
          const height = Math.round(image.naturalHeight);
          if (width <= 0 || height <= 0) return;
          cacheImageDimensions(cacheKey, { width, height });
          if (!authoredDimensions) {
            image.setAttribute('width', String(width));
            image.setAttribute('height', String(height));
          }
        };
        image.addEventListener('load', rememberDimensions);
        cleanups.push(() => image.removeEventListener('load', rememberDimensions));
        if (image.complete) rememberDimensions();
      }
    }
    for (const table of element.querySelectorAll<HTMLTableElement>('table')) {
      if (table.parentElement?.classList.contains('preview-table-scroll')) continue;
      const wrapper = document.createElement('div');
      wrapper.className = 'preview-table-scroll content-visibility-auto';
      table.before(wrapper);
      wrapper.append(table);
    }

    const scroller = previewScroller(element);
    const preEnhancementScroll = scroller ? capturePreviewScroll(scroller) : null;
    const preEnhancementTop = scroller?.scrollTop ?? 0;
    const preEnhancementLeft = scroller?.scrollLeft ?? 0;
    const renderRichContent = async () => {
      const mermaidNodes = [...element.querySelectorAll<HTMLElement>('pre > code.language-mermaid')];
      if (mermaidNodes.length) {
        const mermaid = (await import('mermaid')).default;
        if (disposed || !element.isConnected) return;
        mermaid.initialize({ ...MERMAID_CONFIG, theme: dark ? 'dark' : 'default' });
        for (const node of mermaidNodes) {
          if (disposed || !element.isConnected) return;
          const source = node.textContent ?? '';
          const originalPre = node.parentElement;
          if (!(originalPre instanceof HTMLPreElement)) continue;
          const container = document.createElement('div');
          container.className = 'mermaid';
          container.dataset.source = source;
          container.textContent = source;
          originalPre.replaceWith(container);
          try {
            await mermaid.run({ nodes: [container] });
            if (disposed || !element.isConnected) return;
            const svg = container.querySelector('svg');
            if (!svg) throw new Error('Mermaid did not produce an SVG');
            svg.setAttribute('role', 'img');
            svg.setAttribute('aria-label', t('mermaidDiagram'));
            const logicalWidth = Math.ceil(svg.viewBox.baseVal.width);
            if (logicalWidth > container.clientWidth && container.clientWidth > 0) {
              svg.style.maxWidth = 'none';
              svg.style.width = `${Math.min(logicalWidth, MAX_MERMAID_DISPLAY_WIDTH)}px`;
              svg.style.height = 'auto';
            }
            const actions = document.createElement('div');
            actions.className = 'mermaid-actions';
            addCopyButton(actions, () => container.dataset.source ?? '', 'mermaid-copy');
            const exportLabel = t('exportDiagram');
            const exportButton = document.createElement('button');
            exportButton.type = 'button';
            exportButton.className = 'button button-small rich-preview-action mermaid-export';
            exportButton.textContent = 'PNG';
            exportButton.setAttribute('aria-label', exportLabel);
            exportButton.title = exportLabel;
            const exportPng = async () => {
              exportButton.disabled = true;
              try {
                await exportDiagramAsPng(svg);
                exportButton.disabled = false;
              } catch {
                exportButton.textContent = '!';
                exportButton.setAttribute('aria-label', t('exportFailed'));
                resetButtonLater(exportButton, exportLabel, 'PNG');
              }
            };
            const onExport = () => { void exportPng(); };
            exportButton.addEventListener('click', onExport);
            cleanups.push(() => exportButton.removeEventListener('click', onExport));
            actions.append(exportButton);
            container.append(actions);
          } catch {
            if (disposed || !element.isConnected || !container.isConnected) return;
            const fallback = document.createElement('div');
            fallback.className = 'mermaid-fallback';
            const message = document.createElement('p');
            message.className = 'mermaid-fallback-message';
            message.setAttribute('role', 'status');
            message.textContent = t('mermaidRenderError');
            originalPre.classList.add('preview-code-block');
            addCopyButton(originalPre, () => source, 'code-copy');
            fallback.append(message, originalPre);
            container.replaceWith(fallback);
          }
        }
      }
      if (mathSources.length) {
        const [{ default: renderMathInElement }] = await Promise.all([
          import('katex/contrib/auto-render'),
          import('katex/dist/katex.min.css'),
        ]);
        if (disposed || !element.isConnected) return;
        renderMathInElement(element, {
          throwOnError: false,
          errorCallback: () => undefined,
          delimiters: MATH_DELIMITERS,
        });
        if (disposed || !element.isConnected) return;
        const renderedMath = element.querySelectorAll<HTMLElement>('.katex, .katex-error');
        renderedMath.forEach((rendered, index) => {
          const source = mathSources[index];
          if (!source) return;
          const displayHost = rendered.closest<HTMLElement>('.katex-display');
          let actionHost = displayHost;
          if (actionHost) actionHost.classList.add('preview-math-display');
          else if (source.display) {
            actionHost = document.createElement('span');
            actionHost.className = 'katex-display preview-math-display';
            rendered.before(actionHost);
            actionHost.append(rendered);
          } else {
            actionHost = document.createElement('span');
            actionHost.className = 'preview-math-inline';
            rendered.before(actionHost);
            actionHost.append(rendered);
          }
          actionHost.dataset.mathSource = source.raw;
          addCopyButton(actionHost, () => source.raw, 'math-copy', t('copyFormula'), 'LaTeX');
        });
      }
      if (
        scroller
        && preEnhancementScroll
        && Math.abs(scroller.scrollTop - preEnhancementTop) < 1
        && Math.abs(scroller.scrollLeft - preEnhancementLeft) < 1
      ) {
        restorePreviewScroll(scroller, preEnhancementScroll);
      }
    };
    void renderRichContent().catch(() => {
      if (!disposed) {
        setRichRenderError(t('previewRichError'));
        console.warn('Rich preview rendering failed [PREVIEW_RICH_RENDER]');
      }
    });
    return () => {
      disposed = true;
      for (const cleanup of cleanups) cleanup();
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, [dark, language, safeHtml, t]);

  const showSelectionMenu = (event: ReactMouseEvent<HTMLElement>) => {
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? '';
    const article = root.current;
    if (!text || !article || !selection?.anchorNode || !selection.focusNode
      || !article.contains(selection.anchorNode) || !article.contains(selection.focusNode)) return;
    event.preventDefault();
    event.stopPropagation();
    const activeElement = document.activeElement;
    returnFocus.current = activeElement instanceof HTMLElement && activeElement !== document.body
      ? activeElement
      : article;
    const selectedRange = selection.rangeCount ? selection.getRangeAt(0) : null;
    const selectionRect = selectedRange && typeof selectedRange.getBoundingClientRect === 'function'
      ? selectedRange.getBoundingClientRect()
      : null;
    const requestedX = event.clientX || selectionRect?.left || article.getBoundingClientRect().left;
    const requestedY = event.clientY || selectionRect?.bottom || article.getBoundingClientRect().top;
    setSelectionActionError('');
    setSelectionMenu({
      text,
      x: requestedX,
      y: requestedY,
    });
  };
  const copySelection = async () => {
    if (!selectionMenu) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard is unavailable');
      await navigator.clipboard.writeText(selectionMenu.text);
      closeSelectionMenu(true);
    } catch {
      setSelectionActionError(t('copyFailed'));
    }
  };
  const searchSelection = () => {
    if (!selectionMenu) return;
    const locale = language === 'en' ? 'en-US' : language;
    const host = locale.toLocaleLowerCase().startsWith('zh') ? 'cn.bing.com' : 'www.bing.com';
    const opened = window.open(
      `https://${host}/search?q=${encodeURIComponent(selectionMenu.text)}&setlang=${encodeURIComponent(locale)}`,
      '_blank',
      'noopener,noreferrer',
    );
    if (opened) opened.opener = null;
    closeSelectionMenu(true);
  };
  const findSelection = () => {
    if (!selectionMenu || !onFindInSource) return;
    onFindInSource(selectionMenu.text);
    closeSelectionMenu(true);
  };
  const navigateMenu = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeSelectionMenu(true);
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const items = [...(menuRoot.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])];
    if (!items.length) return;
    event.preventDefault();
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? items.length - 1
        : event.key === 'ArrowDown' ? (current + 1) % items.length
          : (current - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  const selectionMenuPortal = selectionMenu ? createPortal(<div
    ref={menuRoot}
    className="preview-selection-menu surface-elevated focus-scope"
    role="menu"
    aria-label={t('selectionActions')}
    style={{ left: selectionMenu.x, top: selectionMenu.y }}
    onKeyDown={navigateMenu}
    onBlurCapture={() => {
      window.setTimeout(() => {
        if (menuRoot.current && !menuRoot.current.contains(document.activeElement)) closeSelectionMenu(false);
      }, 0);
    }}
  >
    <button type="button" role="menuitem" onClick={() => void copySelection()}>{t('copySelection')}</button>
    <button type="button" role="menuitem" onClick={searchSelection}>{t('searchSelectionBing')}</button>
    {!/[\r\n]/.test(selectionMenu.text) && onFindInSource
      ? <button type="button" role="menuitem" onClick={findSelection}>{t('findSelectionInSource')}</button>
      : null}
    {selectionActionError && <span className="preview-selection-error" role="alert">{selectionActionError}</span>}
  </div>, document.body) : null;

  return <>
    <article
      ref={root}
      className="markdown-body preview-content-visibility content-visibility-auto"
      aria-label={t('previewRegion')}
      aria-busy={html !== deferredHtml}
      tabIndex={0}
      onContextMenu={showSelectionMenu}
    />
    {richRenderError ? <div className="preview-rich-error" role="status">{richRenderError}</div> : null}
    {selectionMenuPortal}
  </>;
}
