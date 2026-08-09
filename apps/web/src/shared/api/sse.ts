import { ApiError } from './error';

export interface SseMessage { event: string; data: string; id?: string }

export interface EventStreamLimits {
  maxBufferBytes: number;
  maxFrameBytes: number;
  maxStreamBytes: number;
}

export const DEFAULT_EVENT_STREAM_LIMITS: Readonly<EventStreamLimits> = Object.freeze({
  // Match the server's validated maxima so any accepted production setting
  // remains consumable, while retaining a hard browser-side memory budget.
  maxBufferBytes: 4 * 1024 * 1024,
  maxFrameBytes: 4 * 1024 * 1024,
  maxStreamBytes: 64 * 1024 * 1024,
});

function streamLimitError(): ApiError {
  return new ApiError('Agent stream exceeded the client safety limit', 0, 'stream_limit_error');
}

function resolveLimits(overrides?: Partial<EventStreamLimits>): EventStreamLimits {
  const limits = { ...DEFAULT_EVENT_STREAM_LIMITS, ...overrides };
  if (Object.values(limits).some((value) => !Number.isSafeInteger(value) || value <= 0)) throw streamLimitError();
  return limits;
}

export async function* parseEventStream(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
  limitOverrides?: Partial<EventStreamLimits>,
): AsyncGenerator<SseMessage> {
  const limits = resolveLimits(limitOverrides);
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = '';
  let event = 'message';
  let id: string | undefined;
  let data: string[] = [];
  let frameBytes = 0;
  let streamBytes = 0;
  let completed = false;

  const emit = (): SseMessage | undefined => {
    const hasData = data.length > 0;
    const message = hasData
      ? { event, data: data.join('\n'), ...(id === undefined ? {} : { id }) }
      : undefined;
    event = 'message';
    data = [];
    return message;
  };

  const processLine = (line: string): SseMessage | undefined => {
    frameBytes += encoder.encode(line).byteLength + 1;
    if (frameBytes > limits.maxFrameBytes) throw streamLimitError();
    if (line === '') {
      const message = emit();
      frameBytes = 0;
      return message;
    }
    if (line.startsWith(':')) return undefined;
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') event = value;
    else if (field === 'data') data.push(value);
    else if (field === 'id' && !value.includes('\0')) id = value;
    return undefined;
  };

  try {
    while (true) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const { done, value } = await reader.read();
      if (value) {
        streamBytes += value.byteLength;
        if (streamBytes > limits.maxStreamBytes) throw streamLimitError();
      }
      buffer += decoder.decode(value, { stream: !done });
      let newline = buffer.indexOf('\n');
      while (newline >= 0) {
        const raw = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        const message = processLine(raw.endsWith('\r') ? raw.slice(0, -1) : raw);
        if (message) yield message;
        newline = buffer.indexOf('\n');
      }
      const bufferedBytes = encoder.encode(buffer).byteLength;
      if (bufferedBytes > limits.maxBufferBytes || frameBytes + bufferedBytes > limits.maxFrameBytes) {
        throw streamLimitError();
      }
      if (done) break;
    }
    if (buffer) processLine(buffer.endsWith('\r') ? buffer.slice(0, -1) : buffer);
    const last = emit();
    if (last) yield last;
    completed = true;
  } finally {
    if (!completed) {
      // Cancellation is best-effort: a transport is allowed to leave its
      // cancellation promise pending, which must not suppress the safety error.
      void reader.cancel().catch(() => undefined);
    }
    reader.releaseLock();
  }
}
