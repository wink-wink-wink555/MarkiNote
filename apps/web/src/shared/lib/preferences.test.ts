import { beforeEach, describe, expect, it } from 'vitest';
import {
  LEGACY_UI_PREFERENCES_KEY,
  loadUiPreferences,
  UI_PREFERENCES_KEY,
  updateUiPreferences,
} from './preferences';

describe('versioned UI preferences', () => {
  beforeEach(() => localStorage.clear());

  it('loads and bounds every V2 layout and reading preference', () => {
    localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify({
      version: 2,
      readingGeometryVersion: 2,
      theme: 'blue',
      language: 'fr',
      sidebarOpen: false,
      aiOpen: true,
      sidebarWidth: 999,
      aiWidth: 250,
      splitRatio: 0.65,
      aiProvider: 'deepseek',
      aiModel: 'deepseek-v4-flash',
      readingFontSize: 99,
      editorFontSize: 1,
      readingLineHeight: 1.77,
      readingWidth: 86,
      density: 'compact',
      editorLineWrap: false,
    }));

    expect(loadUiPreferences()).toEqual({
      version: 2,
      theme: 'blue',
      language: 'fr',
      sidebarOpen: false,
      aiOpen: true,
      sidebarWidth: 480,
      aiWidth: 320,
      splitRatio: 0.65,
      aiProvider: 'deepseek',
      aiModel: 'deepseek-v4-flash',
      readingFontSize: 20,
      editorFontSize: 12,
      readingLineHeight: 1.78,
      readingWidth: 86,
      density: 'compact',
      editorLineWrap: false,
    });
  });

  it('upgrades legacy fixed reading geometry once while preserving later explicit choices', () => {
    localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify({
      version: 2,
      theme: 'light',
      readingFontSize: 15,
      readingLineHeight: 1.68,
      readingWidth: 86,
    }));

    expect(loadUiPreferences().readingWidth).toBe('adaptive');
    expect(JSON.parse(localStorage.getItem(UI_PREFERENCES_KEY) ?? '{}')).toMatchObject({
      version: 2,
      readingGeometryVersion: 2,
      readingWidth: 'adaptive',
    });

    updateUiPreferences({ readingWidth: 86 });
    expect(loadUiPreferences().readingWidth).toBe(86);
  });

  it('migrates every V1 value, persists V2, then removes the redundant legacy copy', () => {
    localStorage.setItem(LEGACY_UI_PREFERENCES_KEY, JSON.stringify({
      version: 1,
      theme: 'pink',
      language: 'ja',
      sidebarOpen: false,
      aiOpen: true,
      sidebarWidth: 280,
      aiWidth: 440,
      splitRatio: 0.6,
      aiProvider: 'openai',
      aiModel: 'gpt-test',
    }));

    expect(loadUiPreferences()).toEqual({
      version: 2,
      theme: 'pink',
      language: 'ja',
      sidebarOpen: false,
      aiOpen: true,
      sidebarWidth: 280,
      aiWidth: 440,
      splitRatio: 0.6,
      aiProvider: 'openai',
      aiModel: 'gpt-test',
      readingFontSize: 15,
      editorFontSize: 14,
      readingLineHeight: 1.68,
      readingWidth: 'adaptive',
      density: 'comfortable',
      editorLineWrap: true,
    });
    expect(JSON.parse(localStorage.getItem(UI_PREFERENCES_KEY) ?? '{}')).toMatchObject({
      version: 2,
      theme: 'pink',
      language: 'ja',
      aiProvider: 'openai',
    });
    expect(localStorage.getItem(LEGACY_UI_PREFERENCES_KEY)).toBeNull();
  });

  it('keeps V1 intact when the migrated V2 value cannot be written', () => {
    const legacyValue = JSON.stringify({
      version: 1,
      theme: 'dark',
      language: 'en',
      sidebarWidth: 300,
    });
    let removed = false;
    const storage = {
      getItem: (key: string) => key === LEGACY_UI_PREFERENCES_KEY ? legacyValue : null,
      setItem: () => { throw new DOMException('Full', 'QuotaExceededError'); },
      removeItem: () => { removed = true; },
    } as unknown as Storage;

    expect(loadUiPreferences(storage)).toMatchObject({
      version: 2,
      theme: 'dark',
      language: 'en',
      sidebarWidth: 300,
    });
    expect(removed).toBe(false);
    expect(storage.getItem(LEGACY_UI_PREFERENCES_KEY)).toBe(legacyValue);
  });

  it('recovers malformed values and persists normalized updates', () => {
    localStorage.setItem(UI_PREFERENCES_KEY, '{broken');
    expect(loadUiPreferences()).toMatchObject({
      version: 2,
      readingFontSize: 15,
      editorFontSize: 14,
      readingLineHeight: 1.68,
      readingWidth: 'adaptive',
      density: 'comfortable',
      editorLineWrap: true,
    });

    expect(updateUiPreferences({
      splitRatio: 0.99,
      sidebarWidth: 300,
      aiProvider: 'x'.repeat(200),
      readingFontSize: 13.6,
      editorFontSize: 17.6,
      readingLineHeight: 0 as 1.58,
      readingWidth: 999 as 72,
      density: 'dense' as 'compact',
      editorLineWrap: false,
    })).toMatchObject({
      splitRatio: 0.8,
      sidebarWidth: 300,
      readingFontSize: 14,
      editorFontSize: 18,
      readingLineHeight: 1.58,
      readingWidth: 'adaptive',
      density: 'comfortable',
      editorLineWrap: false,
    });
    expect(loadUiPreferences().aiProvider.length).toBe(128);
  });

  it('accepts safe serialized numeric preset values', () => {
    localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify({
      version: 2,
      readingGeometryVersion: 2,
      readingFontSize: '18',
      editorFontSize: '16',
      readingLineHeight: '1.78',
      readingWidth: '64',
    }));

    expect(loadUiPreferences()).toMatchObject({
      readingFontSize: 18,
      editorFontSize: 16,
      readingLineHeight: 1.78,
      readingWidth: 64,
    });
  });

  it('falls back safely when browser storage is unavailable', () => {
    const blockedStorage = {
      getItem: () => { throw new DOMException('Blocked', 'SecurityError'); },
      setItem: () => { throw new DOMException('Blocked', 'SecurityError'); },
      removeItem: () => { throw new DOMException('Blocked', 'SecurityError'); },
    } as unknown as Storage;

    expect(loadUiPreferences(blockedStorage)).toMatchObject({
      version: 2,
      language: 'zh-CN',
      readingFontSize: 15,
    });
    expect(updateUiPreferences({
      language: 'unsupported',
      sidebarWidth: 999,
      readingLineHeight: Number.NaN as 1.68,
    }, blockedStorage)).toMatchObject({
      language: 'zh-CN',
      sidebarWidth: 480,
      readingLineHeight: 1.68,
    });
  });
});
