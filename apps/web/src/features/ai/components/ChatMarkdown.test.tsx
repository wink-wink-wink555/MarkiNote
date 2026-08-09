import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ChatMarkdown } from './ChatMarkdown';

describe('ChatMarkdown', () => {
  it('adds compact rich-content structure without changing semantic elements', () => {
    const { container } = render(<ChatMarkdown content={[
      '# Compact heading',
      '',
      '| Name | Value |',
      '| --- | --- |',
      '| MarkiNote | 1 |',
      '',
      '```typescript',
      'const answer = 42;',
      '```',
      '',
      '![Diagram](/diagram.png)',
    ].join('\n')} />);

    expect(screen.getByRole('heading', { name: 'Compact heading', level: 1 })).toBeInTheDocument();
    expect(container.querySelector('.chat-table-scroll > table')).toBeInTheDocument();
    expect(container.querySelector('pre.chat-code-block[data-language="typescript"] > code.language-typescript'))
      .toHaveTextContent('const answer = 42;');
    expect(screen.getByRole('img', { name: 'Diagram' })).toHaveAttribute('loading', 'lazy');
    expect(screen.getByRole('img', { name: 'Diagram' })).toHaveAttribute('decoding', 'async');
  });

  it('keeps enhanced output sanitized', () => {
    const { container } = render(<ChatMarkdown content={'<img src="/safe.png" alt="Safe" onerror="alert(1)"><script>alert(2)</script>'} />);

    expect(container.querySelector('script')).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Safe' })).not.toHaveAttribute('onerror');
  });
});
