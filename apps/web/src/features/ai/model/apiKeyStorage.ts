const AI_CREDENTIALS_KEY = 'markinote.ai.credentials.v1';
const LEGACY_API_KEY = 'markinote.apiKey';
const MAX_PROVIDER_ID_LENGTH = 64;
const MAX_API_KEY_LENGTH = 8 * 1024;

const pageApiKeys = new Map<string, string>();
let legacyStorageCleared = false;

export function clearApiKeys(): void {
  pageApiKeys.clear();
}

function clearLegacyBrowserStorage(): void {
  if (legacyStorageCleared || typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(AI_CREDENTIALS_KEY);
    window.localStorage.removeItem(LEGACY_API_KEY);
    legacyStorageCleared = true;
  } catch {
    // Managed devices and private browsing may deny storage access. Credentials
    // still remain confined to this module's page-lifetime memory.
  }
}

function safeProvider(value: string): string {
  return value.trim().slice(0, MAX_PROVIDER_ID_LENGTH);
}

export function loadApiKey(provider: string): string {
  clearLegacyBrowserStorage();
  const normalizedProvider = safeProvider(provider);
  return normalizedProvider ? pageApiKeys.get(normalizedProvider) ?? '' : '';
}

export function saveApiKey(provider: string, apiKey: string): void {
  clearLegacyBrowserStorage();
  const normalizedProvider = safeProvider(provider);
  if (!normalizedProvider) return;
  const normalizedKey = apiKey.slice(0, MAX_API_KEY_LENGTH);
  if (normalizedKey) pageApiKeys.set(normalizedProvider, normalizedKey);
  else pageApiKeys.delete(normalizedProvider);
}

export function removeApiKey(provider: string): void {
  saveApiKey(provider, '');
}
