import { describe, expect, it, vi } from 'vitest';
import { parseEventStream } from './sse';

describe('parseEventStream', () => {
  it('parses fragmented CRLF frames and multiline data', async () => {
    const encoder = new TextEncoder();
    const chunks = ['event: to', 'ken\r\ndata: {"content":', '"hello"}\r\n\r\nevent: note\ndata: line one\ndata: line two\n\n'];
    const stream = new ReadableStream<Uint8Array>({ start(controller) { chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk))); controller.close(); } });
    const events = [];
    for await (const event of parseEventStream(stream)) events.push(event);
    expect(events).toEqual([{ event: 'token', data: '{"content":"hello"}' }, { event: 'note', data: 'line one\nline two' }]);
  });

  it('emits a final frame without a trailing blank line', async () => {
    const bytes = new TextEncoder().encode('event: done\ndata: {}');
    const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(bytes); controller.close(); } });
    const events = [];
    for await (const event of parseEventStream(stream)) events.push(event);
    expect(events).toEqual([{ event: 'done', data: '{}' }]);
  });

  it('resets an event-only empty frame while retaining the SSE id', async () => {
    const bytes = new TextEncoder().encode('id: durable\nevent: token\n\ndata: next\n\n');
    const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(bytes); controller.close(); } });
    const events = [];

    for await (const event of parseEventStream(stream)) events.push(event);

    expect(events).toEqual([{ event: 'message', data: 'next', id: 'durable' }]);
  });

  it('accepts an SSE frame exactly at the configured byte boundary', async () => {
    const raw = 'data: x\n\n';
    const bytes = new TextEncoder().encode(raw);
    const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(bytes); controller.close(); } });
    const events = [];

    for await (const event of parseEventStream(stream, undefined, {
      maxBufferBytes: bytes.byteLength,
      maxFrameBytes: bytes.byteLength,
      maxStreamBytes: bytes.byteLength,
    })) events.push(event);

    expect(events).toEqual([{ event: 'message', data: 'x' }]);
  });

  it('fails with a stable ApiError and cancels the reader when a frame is oversized', async () => {
    const cancel = vi.fn();
    const bytes = new TextEncoder().encode('data: provider-secret-sentinel\n\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(bytes); },
      cancel,
    });
    const events = parseEventStream(stream, undefined, { maxFrameBytes: 8 });

    await expect(events.next()).rejects.toMatchObject({
      message: 'Agent stream exceeded the client safety limit', code: 'stream_limit_error', status: 0,
    });
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('bounds an unterminated parser buffer without echoing its contents', async () => {
    const cancel = vi.fn();
    const bytes = new TextEncoder().encode('provider-secret-sentinel-without-newline');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(bytes); },
      cancel,
    });
    const error = await parseEventStream(stream, undefined, { maxBufferBytes: 4 }).next()
      .catch((caught: unknown) => caught);

    expect(error).toMatchObject({ code: 'stream_limit_error' });
    expect(String(error)).not.toContain('provider-secret-sentinel');
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('applies the frame limit to an unterminated line before the larger buffer limit', async () => {
    const cancel = vi.fn();
    const bytes = new TextEncoder().encode('123456789');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(bytes); },
      cancel,
    });
    const events = parseEventStream(stream, undefined, {
      maxBufferBytes: 64,
      maxFrameBytes: 8,
    });

    await expect(events.next()).rejects.toMatchObject({ code: 'stream_limit_error' });
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('bounds total bytes across otherwise valid small frames', async () => {
    const encoder = new TextEncoder();
    const first = encoder.encode('data: a\n\n');
    const second = encoder.encode('data: b\n\n');
    const stream = new ReadableStream<Uint8Array>({ start(controller) {
      controller.enqueue(first);
      controller.enqueue(second);
      controller.close();
    } });
    const events = parseEventStream(stream, undefined, { maxStreamBytes: first.byteLength });

    await expect(events.next()).resolves.toMatchObject({ value: { data: 'a' }, done: false });
    await expect(events.next()).rejects.toMatchObject({ code: 'stream_limit_error' });
  });
});
