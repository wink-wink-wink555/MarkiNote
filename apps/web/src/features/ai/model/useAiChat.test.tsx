import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';
import { server } from '@/test/mocks/server';
import type { MessageEntry } from './types';
import { useAiChat } from './useAiChat';

function Harness({ onFilesChanged }: { onFilesChanged: (source: 'ai' | 'rollback') => void }) {
  const chat = useAiChat({
    contextFile: '',
    language: 'en',
    serverKeyConfigured: true,
    onFilesChanged,
  });
  const firstUser = chat.entries.find((entry): entry is MessageEntry => (
    entry.kind === 'message' && entry.role === 'user'
  ));
  return <>
    <button onClick={() => chat.setAllowWriteTools(true)}>Authorize writes</button>
    <button onClick={() => chat.setAllowWriteTools(false)}>Disable writes</button>
    <button onClick={chat.newChat}>New chat</button>
    <button onClick={() => void chat.loadConversation('conversation-failed')}>Load</button>
    <button onClick={() => void chat.loadConversation('conversation-other')}>Load other</button>
    <button disabled={!firstUser} onClick={() => { if (firstUser) void chat.truncate(firstUser, true); }}>Edit first</button>
    <output data-testid="write-authorization">{chat.allowWriteTools ? 'authorized' : 'not authorized'}</output>
    <output data-testid="rollback-pending">{chat.rollbackPending ? 'pending' : 'idle'}</output>
    <output data-testid="entries">{chat.entries.map((entry) => entry.kind === 'message' ? entry.content : entry.name).join('|')}</output>
  </>;
}

describe('useAiChat truncation commit boundary', () => {
  it('keeps the current UI and reports the Problem when rollback was not committed', async () => {
    server.use(
      http.get('http://localhost/api/v1/conversations/conversation-failed', () => HttpResponse.json({
        conversation: {
          id: 'conversation-failed',
          title: 'Failure-safe conversation',
          messages: [
            { role: 'user', content: 'first user\n\n[Attachments: Guide.md]', attachments: ['Guide.md'] },
            { role: 'assistant', content: 'first answer' },
            { role: 'user', content: 'second user' },
            { role: 'assistant', content: 'second answer' },
          ],
        },
      })),
      http.post(
        'http://localhost/api/v1/conversations/conversation-failed/truncate',
        () => HttpResponse.json({
          type: 'https://markinote.local/problems/conversation-truncate-not-committed',
          title: 'Conversation rollback was not committed',
          status: 409,
          code: 'conversation_truncate_not_committed',
          detail: 'Rollback was stopped because a related document changed after the AI operation.',
          requestId: 'req-truncate-failed',
          rollbackResults: [{
            group_id: 'group',
            success: false,
            message: 'rollback refused: a document changed after the AI operation',
          }],
        }, { status: 409 }),
      ),
    );
    const onFilesChanged = vi.fn();
    const user = userEvent.setup();
    renderApp(<Harness onFilesChanged={onFilesChanged} />);

    await user.click(screen.getByRole('button', { name: 'Load' }));
    const before = 'first user|first answer|second user|second answer';
    expect(await screen.findByTestId('entries')).toHaveTextContent(before);
    await user.click(screen.getByRole('button', { name: 'Edit first' }));

    expect(await screen.findByText(/newer edits, conversation, and documents were left unchanged/i)).toBeInTheDocument();
    expect(screen.queryByText(/req-truncate-failed/)).not.toBeInTheDocument();
    expect(screen.getByTestId('entries')).toHaveTextContent(before);
    expect(onFilesChanged).not.toHaveBeenCalled();
  });

  it('explains an unavailable old backup without exposing the raw request id', async () => {
    server.use(
      http.get('http://localhost/api/v1/conversations/conversation-failed', () => HttpResponse.json({
        conversation: {
          id: 'conversation-failed',
          title: 'Old conversation',
          messages: [{ role: 'user', content: 'first user' }, { role: 'assistant', content: 'answer' }],
        },
      })),
      http.post(
        'http://localhost/api/v1/conversations/conversation-failed/truncate',
        () => HttpResponse.json({
          type: 'https://markinote.local/problems/conversation-truncate-not-committed',
          title: 'Conversation rollback was not committed',
          status: 409,
          code: 'conversation_truncate_not_committed',
          detail: 'Rollback could not be completed safely.',
          requestId: 'req-old-backup',
          rollbackResults: [{ group_id: 'expired', success: false, message: '备份不存在' }],
        }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    renderApp(<Harness onFilesChanged={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Load' }));
    await user.click(await screen.findByRole('button', { name: 'Edit first' }));

    expect(await screen.findByText(/required backup is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/req-old-backup/)).not.toBeInTheDocument();
    expect(screen.getByTestId('entries')).toHaveTextContent('first user|answer');
  });

  it('defaults each new or loaded chat to read-only without carrying write authorization across chats', async () => {
    server.use(http.get('http://localhost/api/v1/conversations/conversation-failed', () => HttpResponse.json({
      conversation: {
        id: 'conversation-failed',
        title: 'Loaded conversation',
        messages: [{ role: 'user', content: 'loaded user' }],
      },
    })));
    const user = userEvent.setup();
    renderApp(<Harness onFilesChanged={vi.fn()} />);

    expect(screen.getByTestId('write-authorization')).toHaveTextContent(/^not authorized$/);
    await user.click(screen.getByRole('button', { name: 'Authorize writes' }));
    expect(screen.getByTestId('write-authorization')).toHaveTextContent(/^authorized$/);
    await user.click(screen.getByRole('button', { name: 'New chat' }));
    expect(screen.getByTestId('write-authorization')).toHaveTextContent(/^not authorized$/);

    await user.click(screen.getByRole('button', { name: 'Authorize writes' }));
    await user.click(screen.getByRole('button', { name: 'Load' }));
    expect(await screen.findByTestId('entries')).toHaveTextContent('loaded user');
    expect(screen.getByTestId('write-authorization')).toHaveTextContent(/^not authorized$/);
  });

  it('does not let a late rollback response replace a newly loaded conversation', async () => {
    let releaseRollback: () => void = () => undefined;
    let markRollbackStarted: () => void = () => undefined;
    const rollbackStarted = new Promise<void>((resolve) => { markRollbackStarted = resolve; });
    const rollbackGate = new Promise<void>((resolve) => { releaseRollback = resolve; });
    server.use(
      http.get('http://localhost/api/v1/conversations/conversation-failed', () => HttpResponse.json({
        conversation: {
          id: 'conversation-failed',
          title: 'First conversation',
          messages: [{ role: 'user', content: 'first user' }, { role: 'assistant', content: 'first answer' }],
        },
      })),
      http.get('http://localhost/api/v1/conversations/conversation-other', () => HttpResponse.json({
        conversation: {
          id: 'conversation-other',
          title: 'Other conversation',
          messages: [{ role: 'user', content: 'other user' }, { role: 'assistant', content: 'other answer' }],
        },
      })),
      http.post('http://localhost/api/v1/conversations/conversation-failed/truncate', async () => {
        markRollbackStarted();
        await rollbackGate;
        return HttpResponse.json({
          success: true,
          committed: true,
          message: 'Conversation truncated',
          rollback_results: [],
        });
      }),
    );
    const onFilesChanged = vi.fn();
    const user = userEvent.setup();
    renderApp(<Harness onFilesChanged={onFilesChanged} />);

    await user.click(screen.getByRole('button', { name: 'Load' }));
    expect(await screen.findByTestId('entries')).toHaveTextContent('first user|first answer');
    await user.click(screen.getByRole('button', { name: 'Edit first' }));
    await rollbackStarted;
    expect(screen.getByTestId('rollback-pending')).toHaveTextContent('pending');

    await user.click(screen.getByRole('button', { name: 'Load other' }));
    expect(await screen.findByTestId('entries')).toHaveTextContent('other user|other answer');

    releaseRollback();
    await waitFor(() => expect(screen.getByTestId('rollback-pending')).toHaveTextContent('idle'));
    expect(screen.getByTestId('entries')).toHaveTextContent('other user|other answer');
    expect(onFilesChanged).toHaveBeenCalledWith('rollback');
  });
});
