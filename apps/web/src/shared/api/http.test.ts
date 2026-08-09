import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { ApiError, apiErrorFromProblem, errorMessage } from './error';
import { request } from './http';
import { server } from '@/test/mocks/server';

describe('request', () => {
  it('normalizes Problem Details with status and code', async () => {
    server.use(http.get('http://localhost/api/failure', () => HttpResponse.json({
      type: 'about:blank', title: 'Conflict', status: 409, detail: 'Busy', code: 'conversation_busy', requestId: 'req-problem',
    }, { status: 409 })));
    const error = await request('/api/failure').catch((caught: unknown) => caught);
    expect(error).toMatchObject({ message: 'Busy', status: 409, code: 'conversation_busy', requestId: 'req-problem' } satisfies Partial<ApiError>);
    expect(errorMessage(error)).toBe('Busy (request: req-problem)');
  });

  it('surfaces a validated RFC 9457 request id for operational correlation', () => {
    const error = apiErrorFromProblem({
      type: 'about:blank', title: 'Conflict', status: 409, detail: 'Document changed', code: 'document_conflict', requestId: 'req_a1b2-c3',
    }, 409);

    expect(errorMessage(error)).toBe('Document changed (request: req_a1b2-c3)');
  });

  it('keeps network errors concise and does not invent a request id', async () => {
    server.use(http.get('http://localhost/api/network-failure', () => HttpResponse.error()));
    const error = await request('/api/network-failure').catch((caught: unknown) => caught);

    expect(errorMessage(error)).toBe('Unable to reach the server');
  });

  it('rejects hostile request ids and bounds untrusted display messages', () => {
    const secretSuffix = '<script>payload</script>';
    const error = apiErrorFromProblem({ detail: `${'x'.repeat(800)}\u202e${secretSuffix}`, requestId: `req-ok\n${secretSuffix}` }, 500);
    const displayed = errorMessage(error);

    expect(displayed).toHaveLength(512);
    expect(displayed).not.toContain('(request:');
    expect(displayed).not.toContain('\u202e');
    expect(displayed).not.toContain(secretSuffix);
  });
});
