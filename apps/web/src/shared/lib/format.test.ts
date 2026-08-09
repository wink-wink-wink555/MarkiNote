import { describe, expect, it } from 'vitest';
import { formatTime } from './format';

describe('formatTime', () => {
  it('uses the interface language and accepts an explicit locale', () => {
    const value = '2026-07-23T12:34:00Z';
    document.documentElement.lang = 'fr';

    expect(formatTime(value)).toBe(new Intl.DateTimeFormat('fr', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value)));
    expect(formatTime(value, 'ja')).toBe(new Intl.DateTimeFormat('ja', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value)));
  });

  it('returns an empty value for missing or invalid timestamps', () => {
    expect(formatTime()).toBe('');
    expect(formatTime('not-a-date')).toBe('');
  });
});
