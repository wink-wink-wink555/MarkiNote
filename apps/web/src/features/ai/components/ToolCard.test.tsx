import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';
import type { ToolEntry } from '../model/types';
import { ToolCard } from './ToolCard';

const baseEntry: ToolEntry = {
  kind: 'tool', id: 'tool-1', callId: 'call-1', name: 'write_file', args: { path: 'Guide.md' }, result: 'done', status: 'done', backupGroupId: 'group-1',
};

function approvalEntry(
  status: NonNullable<ToolEntry['approval']>['status'],
  reason: NonNullable<ToolEntry['approval']>['reason'] = 'unselected_resource',
): ToolEntry {
  return {
    ...baseEntry,
    approval: {
      id: 'approval-1',
      target: 'Archive/设计资料/Guide.md',
      reason,
      status,
    },
  };
}

describe('ToolCard', () => {
  it('only exposes rollback for a tool result with concrete backup metadata', async () => {
    const user = userEvent.setup();
    const onRollback = vi.fn(() => Promise.resolve(true));
    const { rerender } = renderApp(<ToolCard entry={baseEntry} onRollback={onRollback} />);
    await user.click(screen.getByRole('button', { expanded: false }));
    expect(screen.queryByRole('button', { name: /roll back operation/i })).not.toBeInTheDocument();

    rerender(<ToolCard key="missing-index" entry={{ ...baseEntry, backupInfo: { type: 'file', path: 'Guide.md' } }} onRollback={onRollback} />);
    await user.click(screen.getByRole('button', { expanded: false }));
    expect(screen.queryByRole('button', { name: /roll back operation/i })).not.toBeInTheDocument();

    rerender(<ToolCard key="with-backup" entry={{ ...baseEntry, backupInfo: { type: 'file', path: 'Guide.md', operation_index: 3 } }} onRollback={onRollback} />);
    await user.click(screen.getByRole('button', { expanded: false }));
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    await user.click(screen.getByRole('button', { name: /roll back operation/i }));
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(onRollback).not.toHaveBeenCalled();
  });

  it('explains the one-time safety confirmation after external web content', () => {
    renderApp(
      <ToolCard
        entry={approvalEntry('pending', 'external_content')}
        onRollback={vi.fn(() => Promise.resolve(false))}
        onResolveApproval={vi.fn(() => Promise.resolve(true))}
      />,
    );

    const approval = screen.getByRole('region', { name: 'Confirm editing scope' });
    expect(approval).toHaveTextContent('The AI used external web content');
    expect(approval).toHaveTextContent('confirm this write operation');
    expect(approval).not.toHaveTextContent('not the current document or an attachment');
  });

  it('prevents duplicate rollback requests and permanently locks a successful rollback', async () => {
    let finishRollback: (success: boolean) => void = () => undefined;
    const onRollback = vi.fn(() => new Promise<boolean>((resolve) => { finishRollback = resolve; }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    renderApp(<ToolCard entry={{ ...baseEntry, backupInfo: { type: 'file', path: 'Guide.md', operation_index: 3 } }} onRollback={onRollback} />);

    await user.click(screen.getByRole('button', { expanded: false }));
    const rollback = screen.getByRole('button', { name: /roll back operation/i });
    await user.click(rollback);
    expect(rollback).toBeDisabled();
    expect(rollback).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(rollback);
    expect(onRollback).toHaveBeenCalledOnce();

    finishRollback(true);
    await waitFor(() => expect(screen.queryByRole('button', { name: /roll back operation/i })).not.toBeInTheDocument());
    expect(screen.getByText('Rolled back')).toBeInTheDocument();
    expect(screen.getByLabelText('Rolled back')).toBeInTheDocument();
  });

  it('shows the complete unselected target and resolves approval without duplicate requests', async () => {
    let finishApproval: (success: boolean) => void = () => undefined;
    const onResolveApproval = vi.fn(() => new Promise<boolean>((resolve) => {
      finishApproval = resolve;
    }));
    const user = userEvent.setup();
    const entry = approvalEntry('pending');
    renderApp(
      <ToolCard
        entry={entry}
        onRollback={vi.fn(() => Promise.resolve(false))}
        onResolveApproval={onResolveApproval}
      />,
    );

    const approval = screen.getByRole('region', { name: 'Confirm editing scope' });
    expect(approval).toHaveTextContent('This file is not the current document or an attachment');
    expect(screen.getByText('Archive/设计资料/Guide.md')).toBeVisible();

    const allow = screen.getByRole('button', { name: 'Allow and edit' });
    await user.click(allow);
    expect(approval).toHaveAttribute('aria-busy', 'true');
    expect(allow).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Deny' })).toBeDisabled();
    fireEvent.click(allow);
    expect(onResolveApproval).toHaveBeenCalledOnce();
    expect(onResolveApproval).toHaveBeenCalledWith(entry, 'approve');

    finishApproval(true);
    await waitFor(() => expect(screen.getByText('The AI is allowed to edit this file')).toBeVisible());
    expect(screen.queryByRole('button', { name: 'Allow and edit' })).not.toBeInTheDocument();
  });

  it('shows a final denied state after the user refuses access', async () => {
    const onResolveApproval = vi.fn(() => Promise.resolve(true));
    const user = userEvent.setup();
    const entry = approvalEntry('pending');
    renderApp(
      <ToolCard
        entry={entry}
        onRollback={vi.fn(() => Promise.resolve(false))}
        onResolveApproval={onResolveApproval}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Deny' }));
    await waitFor(() => expect(screen.getByText('Denied; the AI did not edit this file')).toBeVisible());
    expect(onResolveApproval).toHaveBeenCalledWith(entry, 'deny');
    expect(screen.queryByRole('button', { name: 'Deny' })).not.toBeInTheDocument();
  });

  it('keeps the approval actions available when submission fails', async () => {
    const onResolveApproval = vi.fn(() => Promise.resolve(false));
    const user = userEvent.setup();
    renderApp(
      <ToolCard
        entry={approvalEntry('failed')}
        onRollback={vi.fn(() => Promise.resolve(false))}
        onResolveApproval={onResolveApproval}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Your decision could not be submitted');
    const allow = screen.getByRole('button', { name: 'Allow and edit' });
    await user.click(allow);
    await waitFor(() => expect(screen.getByRole('alert')).toBeVisible());
    expect(screen.getByRole('button', { name: 'Allow and edit' })).toBeEnabled();
  });
});
