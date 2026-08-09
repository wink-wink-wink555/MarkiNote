export function formatBytes(bytes?: number): string {
  if (bytes === undefined) return '';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function interfaceLocale(): string | undefined {
  if (typeof document === 'undefined') return undefined;
  return document.documentElement.lang.trim() || undefined;
}

export function formatTime(value?: string | null, locale = interfaceLocale()): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' };
  try {
    return new Intl.DateTimeFormat(locale, options).format(date);
  } catch {
    return new Intl.DateTimeFormat(undefined, options).format(date);
  }
}

export function basename(path: string): string { return path.split('/').at(-1) ?? path; }
export function dirname(path: string): string { return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''; }
export function uid(prefix = 'id'): string { return `${prefix}-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`; }
