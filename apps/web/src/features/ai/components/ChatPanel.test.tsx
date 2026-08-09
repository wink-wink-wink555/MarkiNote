import { QueryClient } from '@tanstack/react-query';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UI_PREFERENCES_KEY } from '@/shared/lib/preferences';
import { renderApp } from '@/test/render';
import { server } from '@/test/mocks/server';
import { clearApiKeys } from '../model/apiKeyStorage';
import { ChatPanel } from './ChatPanel';

describe('ChatPanel', () => {
  beforeEach(() => clearApiKeys());

  it('exposes panel state, log, and composer semantics with IME-safe submission', async () => {
    const scrollIntoView = vi.spyOn(Element.prototype, 'scrollIntoView');
    const user = userEvent.setup();
    renderApp(<ChatPanel open onClose={vi.fn()} contextFile="" language="en" onFilesChanged={vi.fn()} />);
    expect((await screen.findAllByText(/server-managed API key/i))[0]).toBeInTheDocument();

    const log = screen.getByRole('log');
    expect(log).toHaveAttribute('aria-live', 'polite');
    expect(log).toHaveAttribute('aria-busy', 'false');

    const composer = screen.getByRole('textbox');
    expect(composer).toHaveAccessibleName();
    expect(composer).toHaveAttribute('id', 'ai-composer-input');
    expect(composer).toHaveAttribute('name', 'markinote-ai-message');
    expect(composer).toHaveAttribute('aria-describedby', 'ai-composer-meta');

    const more = screen.getByRole('button', { name: 'More AI actions' });
    expect(more).toHaveAttribute('aria-expanded', 'false');
    await user.click(more);
    expect(screen.getByRole('menuitem', { name: 'History' })).toBeVisible();
    expect(screen.getByRole('menuitem', { name: 'AI settings' })).toBeVisible();
    await user.keyboard('{Escape}');

    await user.type(composer, 'IME message');
    fireEvent.compositionStart(composer);
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    await new Promise((resolve) => window.setTimeout(resolve, 20));
    expect(screen.queryByText('Hello')).not.toBeInTheDocument();
    expect(composer).toHaveValue('IME message');

    fireEvent.compositionEnd(composer);
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    expect(await screen.findByText('Hello')).toBeInTheDocument();
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it('restores focus after transient AI panels close', async () => {
    const user = userEvent.setup();
    const { container } = renderApp(<ChatPanel open onClose={vi.fn()} contextFile="" language="en" onFilesChanged={vi.fn()} />);
    expect((await screen.findAllByText(/server-managed API key/i))[0]).toBeInTheDocument();

    const more = screen.getByRole('button', { name: 'More AI actions' });
    await user.click(more);
    await user.click(screen.getByRole('menuitem', { name: 'History' }));
    await user.click(screen.getByRole('button', { name: 'Go up' }));
    await waitFor(() => expect(more).toHaveFocus());

    const attach = container.querySelector<HTMLButtonElement>('.ai-composer button[aria-haspopup="dialog"]');
    expect(attach).not.toBeNull();
    await user.click(attach!);
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(attach).toHaveFocus());
  });

  it('lets the user remove the automatic current-file context before sending', async () => {
    let payload: Record<string, unknown> | undefined;
    server.use(http.post('http://localhost/api/v1/agent/chat', async ({ request }) => {
      payload = await request.json() as Record<string, unknown>;
      return new HttpResponse(
        'event: token\ndata: {"schemaVersion":1,"runId":"context-run","sequence":1,"type":"token","data":{"content":"No context"}}\n\nevent: done\ndata: {"schemaVersion":1,"runId":"context-run","sequence":2,"type":"done","data":{"conversation_id":"context-conversation"}}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      );
    }));
    const user = userEvent.setup();
    renderApp(<ChatPanel open onClose={vi.fn()} contextFile="Current.md" language="en" onFilesChanged={vi.fn()} />);

    expect(await screen.findByText('Current: Current.md')).toBeInTheDocument();
    expect(screen.queryByText('1/5')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove: Current.md' }));
    expect(screen.queryByText('Current: Current.md')).not.toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: /Message the AI assistant/i }), 'Do not attach it');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByText('No context')).toBeInTheDocument();
    expect(payload).toMatchObject({ context_file: '', attached_files: [] });
  });

  it('uses a server-managed API key without requiring a browser key', async () => {
    const user = userEvent.setup();
    renderApp(<ChatPanel open onClose={vi.fn()} contextFile="" language="en" onFilesChanged={vi.fn()} />);
    expect((await screen.findAllByText(/server-managed API key/i))[0]).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/Ask about docs/i), 'Say hello');
    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toBeEnabled();
    await user.click(send);

    expect(await screen.findByText('Hello')).toBeInTheDocument();
    expect(localStorage.getItem('markinote.apiKey')).toBeNull();
  });

  it('presents an incomplete SSE stream as failure and skips success invalidation', async () => {
    server.use(http.post('http://localhost/api/v1/agent/chat', () => new HttpResponse(
      'event: conversation_id\ndata: {"schemaVersion":1,"runId":"incomplete-run","sequence":1,"type":"conversation_id","data":{"id":"conv-incomplete"}}\n\nevent: token\ndata: {"schemaVersion":1,"runId":"incomplete-run","sequence":2,"type":"token","data":{"content":"Partial response"}}\n\n',
      { headers: { 'Content-Type': 'text/event-stream' } },
    )));
    const invalidateQueries = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    const user = userEvent.setup();
    renderApp(<ChatPanel open onClose={vi.fn()} contextFile="" language="en" onFilesChanged={vi.fn()} />);

    await user.type(screen.getByPlaceholderText(/Ask about docs/i), 'Start a stream');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    const partial = await screen.findByText('Partial response');
    expect(partial.closest('.chat-message')).toHaveClass('error');
    expect(await screen.findByRole('alert')).toHaveTextContent('Agent stream ended before a terminal event');
    await user.type(screen.getByPlaceholderText(/Ask about docs/i), 'Retry');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled());
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it('keeps a missing-key draft, focuses accessible settings, and grows the composer with its content', async () => {
    server.use(
      http.get('http://localhost/api/v1/agent/providers', () => HttpResponse.json({
        providers: { deepseek: { name: 'DeepSeek', models: [{ id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash' }] } },
        limits: { max_attachment_files: 5 },
        serverKeyConfigured: false,
      })),
      http.post('http://localhost/api/v1/agent/validate-key', () => HttpResponse.json({
        type: 'https://markinote.local/problems/invalid-api-key',
        title: 'Invalid API key',
        detail: 'The API key was rejected.',
        status: 401,
      }, { status: 401 })),
    );
    const user = userEvent.setup();
    renderApp(<ChatPanel open onClose={vi.fn()} contextFile="" language="en" onFilesChanged={vi.fn()} />);

    const composer = await screen.findByRole('textbox', { name: /Message the AI assistant/i });
    let composerScrollHeight = 96;
    Object.defineProperty(composer, 'scrollHeight', { configurable: true, get: () => composerScrollHeight });
    await user.type(composer, 'Keep this draft');
    await waitFor(() => expect(composer).toHaveStyle({ height: '96px', overflowY: 'hidden' }));
    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toBeEnabled();
    await user.click(send);

    const keyInput = await screen.findByLabelText('API key');
    expect(keyInput).toHaveFocus();
    expect(composer).toHaveValue('Keep this draft');
    expect(screen.getByRole('region', { name: 'AI settings' })).toBeInTheDocument();

    await user.type(keyInput, 'invalid-key');
    await user.click(screen.getByRole('button', { name: 'Validate connection' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The API key was rejected.');
    expect(keyInput).toHaveAttribute('aria-invalid', 'true');
    expect(keyInput.getAttribute('aria-describedby')).toContain('ai-api-key-status');
    await user.type(keyInput, 'x');
    expect(keyInput).not.toHaveAttribute('aria-invalid');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    composerScrollHeight = 200;
    await user.type(composer, ' and continue');
    await waitFor(() => expect(composer).toHaveStyle({ height: '136px', overflowY: 'auto' }));
    const more = screen.getByRole('button', { name: 'More AI actions' });
    await user.click(screen.getByRole('button', { name: 'Close: AI settings' }));
    await waitFor(() => expect(more).toHaveFocus());
    expect(screen.queryByRole('region', { name: 'AI settings' })).not.toBeInTheDocument();
  });

  it('requires write-access opt-in and preserves it with the next draft while streaming', async () => {
    let releaseChat: () => void = () => undefined;
    const chatGate = new Promise<void>((resolve) => { releaseChat = resolve; });
    const requests: Array<Record<string, unknown>> = [];
    server.use(http.post('http://localhost/api/v1/agent/chat', async ({ request }) => {
      requests.push(await request.json() as Record<string, unknown>);
      await chatGate;
      return new HttpResponse(
        'event: token\ndata: {"schemaVersion":1,"runId":"guarded-run","sequence":1,"type":"token","data":{"content":"Finished"}}\n\nevent: done\ndata: {"schemaVersion":1,"runId":"guarded-run","sequence":2,"type":"done","data":{"conversation_id":"conv-guarded"}}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      );
    }));
    const user = userEvent.setup();
    renderApp(<ChatPanel open onClose={vi.fn()} contextFile="" language="en" onFilesChanged={vi.fn()} />);

    await user.click(await screen.findByRole('button', { name: 'More AI actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'AI settings' }));
    const writeAccess = screen.getByRole('checkbox', { name: /Allow this chat to modify documents/i });
    expect(writeAccess).not.toBeChecked();
    await user.click(writeAccess);
    expect(writeAccess).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Close: AI settings' }));

    const composer = screen.getByRole('textbox', { name: /Message the AI assistant/i });
    await user.type(composer, 'First request');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeEnabled();
    await user.type(composer, 'Next draft');
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    expect(composer).toHaveValue('Next draft');
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ allow_write_tools: true });

    releaseChat();
    expect(await screen.findByText('Finished')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'More AI actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'AI settings' }));
    expect(screen.getByRole('checkbox', { name: /Allow this chat to modify documents/i })).toBeChecked();
    expect(composer).toHaveValue('Next draft');
  });

  it('stops an active stream immediately while the panel remains mounted for its exit animation', async () => {
    let chatSignal: AbortSignal | undefined;
    let markStarted: () => void = () => undefined;
    let releaseRequest: () => void = () => undefined;
    const started = new Promise<void>((resolve) => { markStarted = resolve; });
    const requestGate = new Promise<void>((resolve) => { releaseRequest = resolve; });
    server.use(http.post('http://localhost/api/v1/agent/chat', async ({ request }) => {
      chatSignal = request.signal;
      markStarted();
      await requestGate;
      return new HttpResponse(
        'event: done\ndata: {"schemaVersion":1,"runId":"exit-run","sequence":1,"type":"done","data":{"conversation_id":"exit-conversation"}}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      );
    }));

    function ActiveHarness() {
      const [active, setActive] = useState(true);
      return <>
        <button type="button" onClick={() => setActive(false)}>Deactivate panel</button>
        <ChatPanel open active={active} onClose={() => setActive(false)} contextFile="" language="en" onFilesChanged={vi.fn()} />
      </>;
    }

    const user = userEvent.setup();
    renderApp(<ActiveHarness />);
    const composer = await screen.findByRole('textbox', { name: /Message the AI assistant/i });
    await user.type(composer, 'Keep the exit safe');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await started;

    await user.click(screen.getByRole('button', { name: 'Deactivate panel' }));

    await waitFor(() => expect(chatSignal?.aborted).toBe(true));
    expect(screen.getByRole('complementary', { name: 'AI assistant' })).toBeInTheDocument();
    releaseRequest();
  });

  it('keeps provider keys only in page memory and clears them on pagehide', async () => {
    server.use(http.get('http://localhost/api/v1/agent/providers', () => HttpResponse.json({
      providers: {
        deepseek: { name: 'DeepSeek', models: [{ id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash' }] },
        openai: { name: 'OpenAI', models: [{ id: 'gpt-test', name: 'GPT Test' }] },
      },
      limits: { max_attachment_files: 5 },
      serverKeyConfigured: false,
    })));
    const logged: unknown[][] = [];
    vi.spyOn(console, 'log').mockImplementation((...values: unknown[]) => { logged.push(values); });
    vi.spyOn(console, 'warn').mockImplementation((...values: unknown[]) => { logged.push(values); });
    vi.spyOn(console, 'error').mockImplementation((...values: unknown[]) => { logged.push(values); });
    const user = userEvent.setup();

    function Harness() {
      const [open, setOpen] = useState(true);
      return <><button onClick={() => setOpen(true)}>Reopen</button><ChatPanel open={open} onClose={() => setOpen(false)} contextFile="" language="en" onFilesChanged={vi.fn()} /></>;
    }

    renderApp(<Harness />);
    await user.click(await screen.findByRole('button', { name: 'More AI actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'AI settings' }));
    const keyInput = screen.getByLabelText('API key');
    expect(keyInput).toHaveAttribute('autocomplete', 'off');
    expect(keyInput).toHaveAttribute('autocapitalize', 'none');
    expect(keyInput).toHaveAttribute('spellcheck', 'false');
    expect(keyInput).toHaveAttribute('name', 'markinote-ai-api-key');
    await user.type(keyInput, 'provider-secret');
    await user.selectOptions(screen.getByLabelText('Provider'), 'openai');
    expect(keyInput).toHaveValue('');
    await user.selectOptions(screen.getByLabelText('Provider'), 'deepseek');
    expect(keyInput).toHaveValue('provider-secret');
    await user.selectOptions(screen.getByLabelText('Provider'), 'openai');

    const persisted: unknown = JSON.parse(localStorage.getItem(UI_PREFERENCES_KEY) ?? '{}');
    expect(persisted).toMatchObject({ aiProvider: 'openai', aiModel: 'gpt-test' });
    await user.type(keyInput, 'page-secret');

    await user.click(screen.getByRole('button', { name: 'Close' }));
    await user.click(screen.getByRole('button', { name: 'Reopen' }));
    await user.click(await screen.findByRole('button', { name: 'More AI actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'AI settings' }));
    expect(screen.getByLabelText('API key')).toHaveValue('page-secret');
    expect(screen.getByRole('checkbox', { name: /Allow this chat to modify documents/i })).not.toBeChecked();

    const persistedValues = Object.values(localStorage).join(' ');
    expect(persistedValues).not.toMatch(/provider-secret|page-secret/u);
    expect(window.location.href).not.toMatch(/provider-secret|page-secret/u);
    expect(JSON.stringify(logged)).not.toMatch(/provider-secret|page-secret/u);

    fireEvent(window, new Event('pagehide'));
    expect(screen.getByLabelText('API key')).toHaveValue('');
    await user.selectOptions(screen.getByLabelText('Provider'), 'deepseek');
    expect(screen.getByLabelText('API key')).toHaveValue('');

    await user.type(screen.getByLabelText('API key'), 'clearable-secret');
    await user.click(screen.getByRole('button', { name: 'Clear API key' }));
    expect(screen.getByLabelText('API key')).toHaveValue('');
  });
});
