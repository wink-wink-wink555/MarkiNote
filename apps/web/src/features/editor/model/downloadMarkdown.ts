const MARKDOWN_EXTENSION = /\.(?:md|markdown)$/i;
const WINDOWS_RESERVED_NAME = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i;
const UNSAFE_FILENAME_CHARACTER = /[<>:"/\\|?*]/;

function replaceUnsafeFilenameCharacters(value: string): string {
  return Array.from(value, (character) => (
    character.charCodeAt(0) <= 0x1f || UNSAFE_FILENAME_CHARACTER.test(character)
      ? '-'
      : character
  )).join('');
}

export function markdownDownloadName(title: string): string {
  const leaf = title.split(/[\\/]/).at(-1)?.trim() || 'document';
  const withoutUnsupportedExtension = MARKDOWN_EXTENSION.test(leaf)
    ? leaf.replace(MARKDOWN_EXTENSION, '')
    : leaf.replace(/\.[^.]+$/, '');
  let safe = replaceUnsafeFilenameCharacters(withoutUnsupportedExtension)
    .replace(/[.\s]+$/g, '')
    .trim();
  if (!safe) safe = 'document';
  if (WINDOWS_RESERVED_NAME.test(safe)) safe = `_${safe}`;

  const extension = MARKDOWN_EXTENSION.exec(leaf)?.[0] ?? '.md';
  const maximumStemLength = Math.max(1, 180 - extension.length);
  return `${safe.slice(0, maximumStemLength)}${extension}`;
}

export function downloadMarkdown(title: string, source: string): string {
  const filename = markdownDownloadName(title);
  const objectUrl = URL.createObjectURL(new Blob([source], { type: 'text/markdown;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.append(anchor);

  try {
    anchor.click();
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  } finally {
    anchor.remove();
  }

  // Give the browser one task to consume the object URL before releasing it.
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  return filename;
}
