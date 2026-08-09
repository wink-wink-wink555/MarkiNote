import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '@/test/render';
import { Modal } from './Modal';
import { useToast } from './Toast';

function ModalHarness() {
  const [open, setOpen] = useState(false);
  return <>
    <div data-testid="background"><button type="button" onClick={() => setOpen(true)}>Open modal</button></div>
    <Modal open={open} title="Keyboard test" onClose={() => setOpen(false)}>
      <div className="modal-body">
        <button type="button">First action</button>
        <button type="button">Last action</button>
      </div>
    </Modal>
  </>;
}

function ExemptFocusHarness() {
  const toast = useToast();
  useEffect(() => {
    toast('Persistent problem', 'error');
  }, [toast]);
  return <Modal open title="Exempt focus" onClose={vi.fn()}>
    <div className="modal-body"><button type="button">Dialog action</button></div>
  </Modal>;
}

describe('Modal', () => {
  it('traps focus, makes the background inert, and restores focus after Escape', async () => {
    const user = userEvent.setup();
    renderApp(<ModalHarness />);
    const trigger = screen.getByRole('button', { name: 'Open modal' });
    await user.click(trigger);

    const dialog = screen.getByRole('dialog', { name: 'Keyboard test' });
    const close = within(dialog).getByRole('button', { name: 'Close' });
    const first = within(dialog).getByRole('button', { name: 'First action' });
    const last = within(dialog).getByRole('button', { name: 'Last action' });
    await waitFor(() => expect(close).toHaveFocus());
    expect(screen.getByTestId('background').closest('[inert]')).not.toBeNull();

    await user.tab();
    expect(first).toHaveFocus();
    await user.tab();
    expect(last).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Keyboard test' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(screen.getByTestId('background').closest('[inert]')).toBeNull();
  });

  it('blocks Escape, backdrop, and close-button dismissal while non-dismissible', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderApp(<Modal open title="Saving" onClose={onClose} dismissible={false}>
      <div className="modal-body"><button type="button">Pending action</button></div>
    </Modal>);

    const dialog = screen.getByRole('dialog', { name: 'Saving' });
    expect(within(dialog).getByRole('button', { name: 'Close' })).toBeDisabled();
    await user.keyboard('{Escape}');
    fireEvent.mouseDown(document.querySelector('.modal-backdrop')!);

    expect(onClose).not.toHaveBeenCalled();
    expect(dialog).toBeInTheDocument();
  });

  it('includes modal-exempt portal controls in the keyboard focus loop', async () => {
    const user = userEvent.setup();
    renderApp(<ExemptFocusHarness />);
    const dialog = screen.getByRole('dialog', { name: 'Exempt focus' });
    const close = within(dialog).getByRole('button', { name: 'Close' });
    const action = within(dialog).getByRole('button', { name: 'Dialog action' });
    const dismissToast = await screen.findByRole('button', { name: 'Close: Persistent problem' });

    await waitFor(() => expect(close).toHaveFocus());
    await user.tab();
    expect(action).toHaveFocus();
    await user.tab();
    expect(dismissToast).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
  });

  it('moves automatic focus to preferred content that arrives asynchronously', async () => {
    const media = vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
      matches: query.includes('pointer: fine'),
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }));

    function AsyncContent() {
      const [ready, setReady] = useState(false);
      useEffect(() => {
        const timer = window.setTimeout(() => setReady(true), 30);
        return () => window.clearTimeout(timer);
      }, []);
      return <Modal open title="Async picker" onClose={vi.fn()}>
        <div className="modal-body">
          {ready ? <button type="button" data-modal-initial-focus>First tree item</button> : <div role="status">Loading…</div>}
        </div>
      </Modal>;
    }

    renderApp(<AsyncContent />);
    const dialog = screen.getByRole('dialog', { name: 'Async picker' });
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'First tree item' })).toHaveFocus());
    media.mockRestore();
  });
});
