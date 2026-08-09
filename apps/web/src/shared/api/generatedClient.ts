import { createMarkiNoteClient, type components, type paths } from '@markinote/api-client';
import { apiErrorFromProblem } from './error';

const configuredApiRoot = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '');
// Browsers resolve relative requests against the current origin. Node's Request
// implementation (used by Vitest/MSW) requires an absolute URL instead.
const API_ROOT = configuredApiRoot ?? (import.meta.env.MODE === 'test' ? 'http://localhost' : '');
// Resolve fetch at request time so test/service-worker interceptors can replace
// the global implementation after this module has been imported.
const runtimeFetch: typeof fetch = (input, init) => globalThis.fetch(input, init);

export const apiClient = createMarkiNoteClient({ baseUrl: API_ROOT, fetch: runtimeFetch });
export type ApiComponents = components;
export type ApiPaths = paths;

interface ClientResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

export function unwrap<T>(result: ClientResult): T {
  if (result.data !== undefined) return result.data as T;
  throw apiErrorFromProblem(result.error, result.response.status, result.response.statusText);
}
