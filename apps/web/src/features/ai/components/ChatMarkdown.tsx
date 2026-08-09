import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { memo, useMemo } from 'react';

function enhanceChatMarkdown(html: string): string {
  const template = document.createElement('template');
  template.innerHTML = html;

  for (const table of template.content.querySelectorAll('table')) {
    if (table.parentElement?.classList.contains('chat-table-scroll')) continue;
    const wrapper = document.createElement('div');
    wrapper.className = 'chat-table-scroll';
    table.before(wrapper);
    wrapper.append(table);
  }

  for (const image of template.content.querySelectorAll('img')) {
    image.setAttribute('loading', 'lazy');
    image.setAttribute('decoding', 'async');
  }

  for (const code of template.content.querySelectorAll<HTMLElement>('pre > code')) {
    const languageClass = [...code.classList].find((className) => className.startsWith('language-'));
    const language = (languageClass?.slice('language-'.length) || 'text')
      .replace(/[^a-z0-9_+#.-]/gi, '')
      .slice(0, 24);
    const pre = code.parentElement;
    if (!pre) continue;
    pre.classList.add('chat-code-block');
    pre.dataset.language = language || 'text';
  }

  return template.innerHTML;
}

export const ChatMarkdown = memo(function ChatMarkdown({ content }: { content: string }) {
  const html = useMemo(() => enhanceChatMarkdown(
    DOMPurify.sanitize(marked.parse(content, { async: false, breaks: true })),
  ), [content]);
  return <div className="chat-markdown" dangerouslySetInnerHTML={{ __html: html }} />;
});
