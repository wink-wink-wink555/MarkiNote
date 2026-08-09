import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DropdownMenu } from './DropdownMenu';

function MenuHarness() {
  return <div>
    <button type="button">Before</button>
    <DropdownMenu
      label="Document actions"
      trigger="Actions"
      items={[
        { id: 'first', label: 'First action', onSelect: vi.fn() },
        { id: 'disabled', label: 'Unavailable action', disabled: true, onSelect: vi.fn() },
        { id: 'last', label: 'Last action', onSelect: vi.fn() },
      ]}
    />
    <button type="button">After</button>
  </div>;
}

describe('DropdownMenu keyboard behavior', () => {
  it('opens upward on the last enabled item and uses one roving tab stop', async () => {
    const user = userEvent.setup();
    render(<MenuHarness />);
    const trigger = screen.getByRole('button', { name: 'Document actions' });

    trigger.focus();
    await user.keyboard('{ArrowUp}');

    const first = screen.getByRole('menuitem', { name: 'First action' });
    const disabled = screen.getByRole('menuitem', { name: 'Unavailable action' });
    const last = screen.getByRole('menuitem', { name: 'Last action' });
    expect(last).toHaveFocus();
    expect(last).toHaveAttribute('tabindex', '0');
    expect(first).toHaveAttribute('tabindex', '-1');
    expect(disabled).toHaveAttribute('tabindex', '-1');
  });

  it('closes on Tab and continues from the trigger instead of traversing menu items', async () => {
    const user = userEvent.setup();
    render(<MenuHarness />);
    const trigger = screen.getByRole('button', { name: 'Document actions' });
    trigger.focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'First action' })).toHaveFocus();

    await user.tab();

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus();
  });

  it('lets an outside pointer target receive focus after closing', async () => {
    const user = userEvent.setup();
    render(<MenuHarness />);
    const trigger = screen.getByRole('button', { name: 'Document actions' });
    await user.click(trigger);
    expect(screen.getByRole('menu')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'After' }));

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus();
  });
});
