import { notifyAuthenticationRequired } from '@/shared/auth/authEvents';

const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const MAX_DISPLAY_MESSAGE_LENGTH = 512;

function safeRequestId(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const candidate = value.trim();
  return REQUEST_ID.test(candidate) ? candidate : undefined;
}

function safeDisplayMessage(value: string): string {
  const withoutUnsafeControls = [...value].map((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f)
      || (codePoint >= 0x202a && codePoint <= 0x202e) || (codePoint >= 0x2066 && codePoint <= 0x2069)
      ? ' '
      : character;
  }).join('');
  return withoutUnsafeControls
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, MAX_DISPLAY_MESSAGE_LENGTH);
}

export interface ApiErrorPayload {
  detail?: string;
  title?: string;
  code?: string;
  requestId?: string;
  status?: number;
  type?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly payload?: ApiErrorPayload;

  constructor(message: string, status = 0, code = 'network_error', payload?: ApiErrorPayload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = safeRequestId(payload?.requestId);
    this.payload = payload;
  }
}

/** Normalize RFC 9457 Problem Details into the application error type. */
export function apiErrorFromProblem(body: unknown, status: number, statusText = ''): ApiError {
  const payload = typeof body === 'object' && body !== null ? body as ApiErrorPayload : undefined;
  const plainText = typeof body === 'string' ? body.trim() : '';
  const payloadMessage = [payload?.detail, payload?.title]
    .find((value): value is string => typeof value === 'string');
  const message = safeDisplayMessage(payloadMessage ?? (plainText || statusText));
  const error = new ApiError(message || `HTTP ${status}`, status, payload?.code ?? 'request_error', payload);
  if (error.code === 'authentication_required') notifyAuthenticationRequired();
  return error;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const message = safeDisplayMessage(error.message) || 'Unexpected error';
    return error.requestId ? `${message} (request: ${error.requestId})` : message;
  }
  if (error instanceof Error) return safeDisplayMessage(error.message) || 'Unexpected error';
  return 'Unexpected error';
}
