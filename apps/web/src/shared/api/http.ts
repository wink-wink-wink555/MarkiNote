import { ApiError, apiErrorFromProblem } from './error';

const configuredApiRoot = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '');
const API_ROOT = configuredApiRoot ?? (import.meta.env.MODE === 'test' ? 'http://localhost' : '');

function url(path: string): string {
  return `${API_ROOT}${path.startsWith('/') ? path : `/${path}`}`;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  try { return JSON.parse(text) as unknown; } catch { return text; }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(url(path), { credentials: 'same-origin', ...init, headers });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError('Unable to reach the server', 0, 'network_error');
  }
  const body = await parseBody(response);
  if (!response.ok) {
    throw apiErrorFromProblem(body, response.status, response.statusText);
  }
  return body as T;
}

export const http = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) => request<T>(path, {
    method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}), signal,
  }),
  put: <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: 'PUT', body: JSON.stringify(body), signal }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

export function apiUrl(path: string): string { return url(path); }
