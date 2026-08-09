import { beforeEach, describe, expect, it, vi } from 'vitest';

const AI_CREDENTIALS_KEY = 'markinote.ai.credentials.v1';
const LEGACY_API_KEY = 'markinote.apiKey';

describe('AI API key storage', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it('removes legacy browser credentials without restoring them', async () => {
    localStorage.setItem(AI_CREDENTIALS_KEY, JSON.stringify({
      version: 1,
      keys: { deepseek: 'persisted-secret' },
    }));
    localStorage.setItem(LEGACY_API_KEY, 'legacy-secret');

    const { loadApiKey } = await import('./apiKeyStorage');

    expect(loadApiKey('deepseek')).toBe('');
    expect(localStorage.getItem(AI_CREDENTIALS_KEY)).toBeNull();
    expect(localStorage.getItem(LEGACY_API_KEY)).toBeNull();
  });

  it('keeps credentials independently per provider without writing browser storage', async () => {
    const { loadApiKey, removeApiKey, saveApiKey } = await import('./apiKeyStorage');

    saveApiKey('deepseek', 'deepseek-secret');
    saveApiKey('kimi', 'kimi-secret');

    expect(loadApiKey('deepseek')).toBe('deepseek-secret');
    expect(loadApiKey('kimi')).toBe('kimi-secret');
    expect(localStorage.getItem(AI_CREDENTIALS_KEY)).toBeNull();
    expect(localStorage.getItem(LEGACY_API_KEY)).toBeNull();

    removeApiKey('deepseek');
    expect(loadApiKey('deepseek')).toBe('');
    expect(loadApiKey('kimi')).toBe('kimi-secret');
  });

  it('discards credentials when page memory is cleared or the module is reloaded', async () => {
    const firstPage = await import('./apiKeyStorage');
    firstPage.saveApiKey('deepseek', 'page-secret');
    expect(firstPage.loadApiKey('deepseek')).toBe('page-secret');

    firstPage.clearApiKeys();
    expect(firstPage.loadApiKey('deepseek')).toBe('');

    firstPage.saveApiKey('deepseek', 'next-page-secret');

    vi.resetModules();
    const refreshedPage = await import('./apiKeyStorage');

    expect(refreshedPage.loadApiKey('deepseek')).toBe('');
    expect(Object.values(localStorage).join(' ')).not.toMatch(/page-secret|next-page-secret/u);
  });
});
