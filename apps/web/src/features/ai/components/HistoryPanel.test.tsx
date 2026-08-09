import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';
import { server } from '@/test/mocks/server';
import { HistoryPanel } from './HistoryPanel';

describe('HistoryPanel', () => {
  it('exposes the current conversation and keeps row actions available', async () => {
    server.use(http.get('http://localhost/api/v1/conversations', () => HttpResponse.json({
      items: [{
        id: 'active-conversation',
        title: 'Current draft',
        updated_at: '2026-01-02T12:00:00Z',
        message_count: 4,
      }],
    })));
    renderApp(<HistoryPanel
      onBack={vi.fn()}
      onLoad={vi.fn()}
      activeId="active-conversation"
      onDeletedActive={vi.fn()}
    />);

    const current = await screen.findByRole('button', { name: /Current draft/ });
    expect(current).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', { name: 'Rename conversation' }).closest('.ai-row-actions')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete conversation' }).closest('.ai-row-actions')).toBeInTheDocument();
  });

  it('renames from an accessible controlled modal and locks the form while saving', async () => {
    const user = userEvent.setup();
    let finishRequest: (() => void) | undefined;
    let requestBody: unknown;
    const pendingRequest = new Promise<void>((resolve) => { finishRequest = resolve; });
    server.use(
      http.get('http://localhost/api/v1/conversations', () => HttpResponse.json({
        items: [{
          id: 'draft-conversation',
          title: 'Initial title',
          updated_at: '2026-01-02T12:00:00Z',
          message_count: 2,
        }],
      })),
      http.patch('http://localhost/api/v1/conversations/draft-conversation', async ({ request }) => {
        requestBody = await request.json();
        await pendingRequest;
        return HttpResponse.json({ success: true, title: 'Architecture notes' });
      }),
    );
    const prompt = vi.spyOn(window, 'prompt');
    renderApp(<HistoryPanel
      onBack={vi.fn()}
      onLoad={vi.fn()}
      activeId=""
      onDeletedActive={vi.fn()}
    />);

    const renameButton = await screen.findByRole('button', { name: 'Rename conversation' });
    await user.click(renameButton);

    expect(prompt).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog', { name: 'Rename conversation' });
    const input = within(dialog).getByRole('textbox', { name: 'Name' });
    expect(input).toHaveAttribute('data-modal-initial-focus');
    expect(input).toHaveValue('Initial title');
    expect(within(dialog).getByRole('button', { name: 'Confirm' })).toBeDisabled();

    await user.clear(input);
    await user.type(input, '  Architecture notes  ');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));

    await waitFor(() => {
      expect(input).toBeDisabled();
      expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
      expect(within(dialog).getByRole('button', { name: 'Confirm' })).toBeDisabled();
      expect(within(dialog).getByRole('button', { name: 'Close' })).toBeDisabled();
    });
    expect(requestBody).toEqual({ title: 'Architecture notes' });

    finishRequest?.();
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Rename conversation' })).not.toBeInTheDocument());
    expect(renameButton).toHaveFocus();
    prompt.mockRestore();
  });
});
