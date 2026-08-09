import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { App } from '@/app/App';
import { server } from '@/test/mocks/server';
import { renderApp } from '@/test/render';

const apiRoot = { name: 'MarkiNote API', version: '1.0.0', contract: 1 };
const authenticationProblem = { type: 'about:blank', title: 'Authentication required', status: 401, detail: 'A valid access token is required.', code: 'authentication_required', requestId: 'req-auth' };

function storageContents(storage: Storage): string {
  return Array.from({ length: storage.length }, (_, index) => storage.key(index))
    .map((key) => key ? storage.getItem(key) : '')
    .join(' ');
}

describe('AuthenticationBoundary', () => {
  it('exchanges an in-memory token through POST, clears it, and retries the app', async () => {
    const user = userEvent.setup();
    let authenticated = false;
    let exchangeBody: unknown;
    server.use(
      http.get('http://localhost/api/v1', () => authenticated ? HttpResponse.json(apiRoot) : HttpResponse.json(authenticationProblem, { status: 401 })),
      http.post('*/auth/access-token', async ({ request }) => {
        expect(new URL(request.url).origin).toBe(window.location.origin);
        exchangeBody = await request.json();
        authenticated = true;
        return HttpResponse.json({ authenticated: true });
      }),
    );
    renderApp(<App />);
    const token = await screen.findByLabelText('Access token');
    expect(token).toHaveAttribute('autocomplete', 'off');
    expect(token).toHaveAttribute('autocapitalize', 'none');
    expect(token).toHaveAttribute('spellcheck', 'false');
    expect(token).toHaveAttribute('name', 'markinote-session-access-token');
    await user.type(token, 'temporary-browser-secret');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    expect(exchangeBody).toEqual({ accessToken: 'temporary-browser-secret' });
    expect(screen.queryByLabelText('Access token')).not.toBeInTheDocument();
    expect(window.location.href).not.toContain('temporary-browser-secret');
    expect(storageContents(localStorage)).not.toContain('temporary-browser-secret');
    expect(storageContents(sessionStorage)).not.toContain('temporary-browser-secret');
  });

  it('shows a rate-limit error and discards the submitted token', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('http://localhost/api/v1', () => HttpResponse.json(authenticationProblem, { status: 401 })),
      http.post('*/auth/access-token', () => HttpResponse.json({ type: 'about:blank', title: 'Too many attempts', status: 429, detail: 'Wait before trying another access token.', code: 'authentication_rate_limited', requestId: 'req-limit' }, { status: 429 })),
    );
    renderApp(<App />);
    const token = await screen.findByLabelText('Access token');
    await user.type(token, 'discard-me');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts');
    expect(token).toHaveValue('');
    expect(token).toHaveFocus();
    expect(token).toHaveAttribute('aria-invalid', 'true');
    const errorId = token.getAttribute('aria-errormessage');
    expect(errorId).toBeTruthy();
    expect(document.getElementById(errorId!)).toHaveTextContent('Too many attempts');
    expect(token.getAttribute('aria-describedby')).toContain(errorId);
    expect(storageContents(localStorage)).not.toContain('discard-me');
    expect(storageContents(sessionStorage)).not.toContain('discard-me');
  });

  it('returns to the login gate when a protected request reports an expired session', async () => {
    server.use(
      http.get('http://localhost/api/v1', () => HttpResponse.json(apiRoot)),
      http.get('http://localhost/api/v1/documents', () => HttpResponse.json(authenticationProblem, { status: 401 })),
    );

    renderApp(<App />);

    expect(await screen.findByLabelText('Access token')).toBeInTheDocument();
  });
});
