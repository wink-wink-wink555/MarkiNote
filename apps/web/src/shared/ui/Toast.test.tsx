import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Modal } from './Modal';
import { ToastProvider, useToast } from './Toast';

function ToastHarness() {
  const notify = useToast();
  return <>
    <button type="button" onClick={() => notify('Saved successfully', 'success')}>Show success</button>
    <button type="button" onClick={() => notify('Could not save', 'error')}>Show error</button>
  </>;
}

function ModalToastHarness() {
  const notify = useToast();
  return <Modal open title="Operation" onClose={() => undefined}>
    <button type="button" onClick={() => notify('Operation failed', 'error')}>Fail operation</button>
  </Modal>;
}

describe('ToastProvider', () => {
  afterEach(() => vi.useRealTimers());

  it('keeps errors visible until the user dismisses them', () => {
    vi.useFakeTimers();
    render(<ToastProvider><ToastHarness /></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Show error' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save');

    void act(() => { vi.advanceTimersByTime(30_000); });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close: Could not save' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('announces success politely and removes it after its display window', () => {
    vi.useFakeTimers();
    render(<ToastProvider><ToastHarness /></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Show success' }));
    expect(screen.getByRole('status')).toHaveTextContent('Saved successfully');

    void act(() => { vi.advanceTimersByTime(4_500); });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('pauses timed notifications while hovered or keyboard-focused', () => {
    vi.useFakeTimers();
    render(<ToastProvider><ToastHarness /></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Show success' }));
    const status = screen.getByRole('status');

    void act(() => { vi.advanceTimersByTime(2_000); });
    fireEvent.mouseEnter(status);
    void act(() => { vi.advanceTimersByTime(10_000); });
    expect(status).toBeInTheDocument();

    fireEvent.mouseLeave(status);
    void act(() => { vi.advanceTimersByTime(2_499); });
    expect(status).toBeInTheDocument();
    status.querySelector('button')?.focus();
    void act(() => { vi.advanceTimersByTime(10_000); });
    expect(status).toBeInTheDocument();

    fireEvent.blur(status.querySelector('button') as HTMLButtonElement, { relatedTarget: document.body });
    void act(() => { vi.advanceTimersByTime(1); });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('keeps portal errors operable when a modal makes the application root inert', () => {
    render(<ToastProvider><ModalToastHarness /></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Fail operation' }));

    const alert = screen.getByRole('alert');
    const region = alert.closest('.toast-region');
    expect(region).toBe(document.body.querySelector('.toast-region'));
    expect(region).toHaveAttribute('data-modal-exempt', 'true');
    expect(region?.closest('[inert]')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Close: Operation failed' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
