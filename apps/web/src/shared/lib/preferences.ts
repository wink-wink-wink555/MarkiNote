export type ThemePreference = 'light' | 'dark' | 'blue' | 'pink';
export type ReadingLineHeightPreference = 1.58 | 1.68 | 1.78;
export type ReadingWidthPreference = 64 | 72 | 86 | 'adaptive' | 'fluid';
export type DensityPreference = 'compact' | 'comfortable';

export interface UiPreferencesV1 {
  version: 1;
  theme: ThemePreference;
  language: string;
  sidebarOpen: boolean;
  aiOpen: boolean;
  sidebarWidth: number;
  aiWidth: number;
  splitRatio: number;
  aiProvider: string;
  aiModel: string;
}

export interface UiPreferencesV2 extends Omit<UiPreferencesV1, 'version'> {
  version: 2;
  readingFontSize: number;
  editorFontSize: number;
  readingLineHeight: ReadingLineHeightPreference;
  readingWidth: ReadingWidthPreference;
  density: DensityPreference;
  editorLineWrap: boolean;
}

export const UI_PREFERENCES_KEY = 'markinote.preferences.v2';
export const LEGACY_UI_PREFERENCES_KEY = 'markinote.preferences.v1';

export const READING_LINE_HEIGHTS = [1.58, 1.68, 1.78] as const;
export const READING_WIDTHS = [64, 72, 86, 'adaptive', 'fluid'] as const;
export const DENSITY_PREFERENCES = ['compact', 'comfortable'] as const;
export const readingWidthCssValue = (value: ReadingWidthPreference): string => (
  value === 'adaptive' ? 'var(--reading-width-adaptive)' : value === 'fluid' ? '100%' : `${value}ch`
);
const READING_GEOMETRY_VERSION = 2;
const READING_GEOMETRY_VERSION_KEY = 'readingGeometryVersion';

const THEMES: readonly ThemePreference[] = ['light', 'dark', 'blue', 'pink'];
const LANGUAGES = ['zh-CN', 'en', 'fr', 'ja'] as const;

type PreferenceCandidate = Partial<Omit<UiPreferencesV2, 'version'>> & {
  version?: unknown;
};

function browserStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

function readStorage(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(storage: Storage, key: string, value: string): boolean {
  try {
    storage.setItem(key, value);
    return true;
  } catch {
    // Storage may be blocked or full. Preferences must remain optional.
    return false;
  }
}

function removeStorage(storage: Storage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // A redundant legacy value is harmless when storage cannot be changed.
  }
}

function numericValue(value: unknown): number {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim()) return Number(value);
  return Number.NaN;
}

function clamp(value: unknown, minimum: number, maximum: number, fallback: number): number {
  const numeric = numericValue(value);
  return Number.isFinite(numeric) ? Math.min(maximum, Math.max(minimum, numeric)) : fallback;
}

function clampInteger(value: unknown, minimum: number, maximum: number, fallback: number): number {
  return Math.round(clamp(value, minimum, maximum, fallback));
}

function selectionId(value: unknown): string {
  return typeof value === 'string' ? value.trim().slice(0, 128).trim() : '';
}

function defaultTheme(): ThemePreference {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

function normalizeReadingLineHeight(value: unknown): ReadingLineHeightPreference {
  const bounded = clamp(value, READING_LINE_HEIGHTS[0], READING_LINE_HEIGHTS.at(-1) ?? 1.78, 1.68);
  return READING_LINE_HEIGHTS.reduce((nearest, candidate) => (
    Math.abs(candidate - bounded) < Math.abs(nearest - bounded) ? candidate : nearest
  ), 1.68 as ReadingLineHeightPreference);
}

function normalizeReadingWidth(value: unknown): ReadingWidthPreference {
  if (value === 'adaptive' || value === 'fluid') return value;
  const numeric = numericValue(value);
  return READING_WIDTHS.includes(numeric as 64 | 72 | 86) ? numeric as 64 | 72 | 86 : 'adaptive';
}

function migrateLegacyReadingWidth(candidate: Record<string, unknown>): ReadingWidthPreference {
  const width = normalizeReadingWidth(candidate.readingWidth);
  if (width === 86) return 'adaptive';
  const defaultReadingGeometry = width === 72
    && clampInteger(candidate.readingFontSize, 14, 20, 15) === 15
    && normalizeReadingLineHeight(candidate.readingLineHeight) === 1.68;
  return defaultReadingGeometry ? 'adaptive' : width;
}

function writePreferences(storage: Storage, value: UiPreferencesV2): boolean {
  return writeStorage(storage, UI_PREFERENCES_KEY, JSON.stringify({
    ...value,
    [READING_GEOMETRY_VERSION_KEY]: READING_GEOMETRY_VERSION,
  }));
}

function normalize(candidate: PreferenceCandidate): UiPreferencesV2 {
  const theme = THEMES.includes(candidate.theme as ThemePreference)
    ? candidate.theme as ThemePreference
    : defaultTheme();
  return {
    version: 2,
    theme,
    language: LANGUAGES.includes(candidate.language as typeof LANGUAGES[number]) ? candidate.language as string : 'zh-CN',
    sidebarOpen: typeof candidate.sidebarOpen === 'boolean' ? candidate.sidebarOpen : true,
    aiOpen: typeof candidate.aiOpen === 'boolean' ? candidate.aiOpen : false,
    sidebarWidth: clamp(candidate.sidebarWidth, 220, 480, 310),
    aiWidth: clamp(candidate.aiWidth, 320, 520, 390),
    splitRatio: clamp(candidate.splitRatio, 0.2, 0.8, 0.5),
    aiProvider: selectionId(candidate.aiProvider),
    aiModel: selectionId(candidate.aiModel),
    readingFontSize: clampInteger(candidate.readingFontSize, 14, 20, 15),
    editorFontSize: clampInteger(candidate.editorFontSize, 12, 18, 14),
    readingLineHeight: normalizeReadingLineHeight(candidate.readingLineHeight),
    readingWidth: normalizeReadingWidth(candidate.readingWidth),
    density: DENSITY_PREFERENCES.includes(candidate.density as DensityPreference)
      ? candidate.density as DensityPreference
      : 'comfortable',
    editorLineWrap: typeof candidate.editorLineWrap === 'boolean' ? candidate.editorLineWrap : true,
  };
}

function parseStored(serialized: string | null): Record<string, unknown> | undefined {
  if (!serialized) return undefined;
  try {
    const parsed: unknown = JSON.parse(serialized);
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : undefined;
  } catch {
    // A malformed client preference must never prevent the workspace loading.
    return undefined;
  }
}

export function loadUiPreferences(storage: Storage | undefined = browserStorage()): UiPreferencesV2 {
  if (!storage) return normalize({});

  const current = parseStored(readStorage(storage, UI_PREFERENCES_KEY));
  if (current?.version === 2) {
    const needsReadingGeometryMigration = current[READING_GEOMETRY_VERSION_KEY] !== READING_GEOMETRY_VERSION;
    const normalized = normalize({
      ...current,
      readingWidth: needsReadingGeometryMigration
        ? migrateLegacyReadingWidth(current)
        : normalizeReadingWidth(current.readingWidth),
    });
    if (needsReadingGeometryMigration) writePreferences(storage, normalized);
    // Once V2 is known to be readable, its V1 predecessor is redundant.
    removeStorage(storage, LEGACY_UI_PREFERENCES_KEY);
    return normalized;
  }

  const legacy = parseStored(readStorage(storage, LEGACY_UI_PREFERENCES_KEY));
  if (legacy?.version === 1) {
    const migrated = normalize(legacy);
    // Never remove the only readable copy until its complete V2 replacement is stored.
    if (writePreferences(storage, migrated)) {
      removeStorage(storage, LEGACY_UI_PREFERENCES_KEY);
    }
    return migrated;
  }

  const defaults = normalize({});
  writePreferences(storage, defaults);
  return defaults;
}

export function updateUiPreferences(
  patch: Partial<Omit<UiPreferencesV2, 'version'>>,
  storage: Storage | undefined = browserStorage(),
): UiPreferencesV2 {
  const next = normalize({ ...loadUiPreferences(storage), ...patch, version: 2 });
  if (storage) writePreferences(storage, next);
  return next;
}
