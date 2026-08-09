import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { DEFAULT_EVENT_STREAM_LIMITS } from '@/shared/api/sse';
import { server } from '@/test/mocks/server';
import { aiApi } from './aiApi';

const chatRequest = { message: 'hello', conversation_id: '', run_id: 'test-run', provider: 'deepseek', model: 'deepseek-v4-flash', api_key: 'memory-only', context_file: '', attached_files: [], language: 'en' as const, allow_write_tools: false };
const stream = (body: string) => new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } });
const frame = (event: string, payload: unknown) => `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;

describe('aiApi.chat', () => {
  it('preserves the validated v1 SSE envelope and event order', async () => {
    const events = [];
    for await (const event of aiApi.chat(chatRequest, new AbortController().signal)) events.push(event);
    expect(events).toEqual([
      { schemaVersion: 1, runId: 'mock-run', sequence: 1, type: 'conversation_id', data: { id: 'conv-1' } },
      { schemaVersion: 1, runId: 'mock-run', sequence: 2, type: 'token', data: { content: 'Hello' } },
      { schemaVersion: 1, runId: 'mock-run', sequence: 3, type: 'done', data: { conversation_id: 'conv-1' } },
    ]);
  });

  it('preserves the external-content approval reason from a validated tool result', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(
      frame('tool_result', {
        schemaVersion: 1,
        runId: 'run-external-approval',
        sequence: 1,
        type: 'tool_result',
        data: {
          call_id: 'call-external-approval',
          name: 'write_file',
          args: { path: 'Guide.md' },
          result: 'Approval required',
          approval: {
            id: 'approval-external',
            status: 'pending',
            target: 'Guide.md',
            reason: 'external_content',
          },
        },
      })
      + frame('done', {
        schemaVersion: 1,
        runId: 'run-external-approval',
        sequence: 2,
        type: 'done',
        data: { conversation_id: 'conv-external-approval' },
      }),
    )));
    const events = [];

    for await (const event of aiApi.chat(chatRequest, new AbortController().signal)) events.push(event);

    expect(events[0]).toMatchObject({
      type: 'tool_result',
      data: { approval: { id: 'approval-external', reason: 'external_content' } },
    });
  });

  it('ignores unknown additive events while retaining known sequence numbers', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(
      frame('conversation_id', { schemaVersion: 1, runId: 'run-additive', sequence: 1, type: 'conversation_id', data: { id: 'conv-2' } })
      + frame('future_event', { schemaVersion: 1, runId: 'run-additive', sequence: 2, type: 'future_event', data: { future: true } })
      + frame('done', { schemaVersion: 1, runId: 'run-additive', sequence: 3, type: 'done', data: { conversation_id: 'conv-2' } }),
    )));
    const events = [];

    for await (const event of aiApi.chat(chatRequest, new AbortController().signal)) events.push(event);

    expect(events.map(({ type, sequence }) => ({ type, sequence }))).toEqual([
      { type: 'conversation_id', sequence: 1 },
      { type: 'done', sequence: 3 },
    ]);
  });

  it('rejects malformed known frames with a stable contract error', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(frame('token', {
      schemaVersion: 1, runId: 'run-invalid', sequence: 1, type: 'token', data: { content: 42 },
    }))));
    const events = aiApi.chat(chatRequest, new AbortController().signal);

    await expect(events.next()).rejects.toMatchObject({ message: 'Agent stream contract violation', code: 'stream_contract_error' });
  });

  it('rejects non-monotonic sequence numbers within one run', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(
      frame('conversation_id', { schemaVersion: 1, runId: 'run-order', sequence: 2, type: 'conversation_id', data: { id: 'conv-order' } })
      + frame('done', { schemaVersion: 1, runId: 'run-order', sequence: 1, type: 'done', data: { conversation_id: 'conv-order' } }),
    )));
    const events = aiApi.chat(chatRequest, new AbortController().signal);

    await expect(events.next()).resolves.toMatchObject({ value: { sequence: 2, type: 'conversation_id' }, done: false });
    await expect(events.next()).rejects.toMatchObject({ code: 'stream_contract_error' });
  });

  it('rejects a naturally closed stream without done or error as incomplete', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(frame('token', {
      schemaVersion: 1, runId: 'run-incomplete', sequence: 1, type: 'token', data: { content: 'Partial' },
    }))));
    const events = aiApi.chat(chatRequest, new AbortController().signal);

    await expect(events.next()).resolves.toMatchObject({ value: { type: 'token', data: { content: 'Partial' } }, done: false });
    await expect(events.next()).rejects.toMatchObject({
      message: 'Agent stream ended before a terminal event', code: 'stream_incomplete_error', status: 0,
    });
  });

  it('preserves a stable server error code and rejects an error without one', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(frame('error', {
      schemaVersion: 1, runId: 'run-error', sequence: 1, type: 'error',
      data: { code: 'provider_error', message: 'AI provider request failed.' },
    }))));
    const events = aiApi.chat(chatRequest, new AbortController().signal);

    await expect(events.next()).resolves.toMatchObject({
      value: { type: 'error', data: { code: 'provider_error' } }, done: false,
    });
    await expect(events.next()).resolves.toEqual({ value: undefined, done: true });

    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(frame('error', {
      schemaVersion: 1, runId: 'run-invalid-error', sequence: 1, type: 'error',
      data: { message: 'missing code' },
    }))));
    const invalid = aiApi.chat(chatRequest, new AbortController().signal);
    await expect(invalid.next()).rejects.toMatchObject({ code: 'stream_contract_error' });
  });

  it('rejects known events received after a terminal frame', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(
      frame('done', { schemaVersion: 1, runId: 'run-terminal', sequence: 1, type: 'done', data: { conversation_id: 'conv-terminal' } })
      + frame('token', { schemaVersion: 1, runId: 'run-terminal', sequence: 2, type: 'token', data: { content: 'late' } }),
    )));
    const events = aiApi.chat(chatRequest, new AbortController().signal);

    await expect(events.next()).resolves.toMatchObject({ value: { type: 'done' }, done: false });
    await expect(events.next()).rejects.toMatchObject({ code: 'stream_contract_error' });
  });

  it('surfaces the parser safety limit as a stable ApiError without echoing content', async () => {
    const sentinel = 'provider-secret-sentinel';
    server.use(http.post('http://localhost/api/v1/agent/chat', () => stream(frame('token', {
      schemaVersion: 1,
      runId: 'run-oversized',
      sequence: 1,
      type: 'token',
      data: { content: sentinel + 'x'.repeat(DEFAULT_EVENT_STREAM_LIMITS.maxFrameBytes + 1) },
    }))));
    const events = aiApi.chat(chatRequest, new AbortController().signal);
    const error = await events.next().catch((caught: unknown) => caught);

    expect(error).toMatchObject({
      message: 'Agent stream exceeded the client safety limit', code: 'stream_limit_error', status: 0,
    });
    expect(String(error)).not.toContain(sentinel);
  });

  it('does not expose duplicate client-side partial persistence on cancellation', () => {
    expect(aiApi).not.toHaveProperty('savePartial');
  });

  it('requests a single-operation rollback with its backup index', async () => {
    let body: unknown;
    server.use(http.post('http://localhost/api/v1/operations/rollback', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ success: true, message: 'Rolled back' });
    }));

    await aiApi.rollback('group-1', 3);

    expect(body).toEqual({ backupGroupId: 'group-1', operationIndex: 3 });
  });

  it('surfaces Problem Details when an SSE connection is rejected', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => HttpResponse.json({
      type: 'https://markinote.dev/problems/conversation-busy', title: 'Conflict', status: 409,
      detail: 'This conversation already has an active run.', code: 'conversation_busy', requestId: 'req-409',
    }, { status: 409 })));

    const rejectedStream = aiApi.chat({ ...chatRequest, conversation_id: 'busy', api_key: '' }, new AbortController().signal);

    await expect(rejectedStream.next()).rejects.toMatchObject({
      message: 'This conversation already has an active run.', status: 409, code: 'conversation_busy', requestId: 'req-409',
    });
  });
});
