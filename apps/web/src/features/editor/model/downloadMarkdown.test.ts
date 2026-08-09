import { afterEach, describe, expect, it, vi } from 'vitest';
import { downloadMarkdown, markdownDownloadName } from './downloadMarkdown';

const createObjectUrlDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
const revokeObjectUrlDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  if (createObjectUrlDescriptor) Object.defineProperty(URL, 'createObjectURL', createObjectUrlDescriptor);
  else delete (URL as Partial<typeof URL>).createObjectURL;
  if (revokeObjectUrlDescriptor) Object.defineProperty(URL, 'revokeObjectURL', revokeObjectUrlDescriptor);
  else delete (URL as Partial<typeof URL>).revokeObjectURL;
});

describe('Markdown download', () => {
  it.each([
    ['Guide.md', 'Guide.md'],
    ['notes/Guide.markdown', 'Guide.markdown'],
    ['draft.txt', 'draft.md'],
    ['bad:<name>.txt', 'bad--name-.md'],
    ['CON', '_CON.md'],
    ['', 'document.md'],
  ])('creates a portable filename for %j', (title, expected) => {
    expect(markdownDownloadName(title)).toBe(expected);
  });

  it('downloads the current source and releases its object URL', () => {
    vi.useFakeTimers();
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => 'blob:markdown');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    expect(downloadMarkdown('Guide.md', '# Local draft')).toBe('Guide.md');

    expect(createObjectURL).toHaveBeenCalledOnce();
    const blob = createObjectURL.mock.calls[0]?.[0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob?.type).toBe('text/markdown;charset=utf-8');
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector('a[download="Guide.md"]')).not.toBeInTheDocument();
    expect(revokeObjectURL).not.toHaveBeenCalled();

    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:markdown');
  });
});
