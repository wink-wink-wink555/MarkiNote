import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ResizeHandle } from './ResizeHandle';

describe('ResizeHandle', () => {
  it('supports keyboard resizing in both directions', () => {
    const resize = vi.fn();
    const completed = vi.fn();
    render(<ResizeHandle label="Resize panel" value={300} minimum={220} maximum={480} onResize={resize} onResizeEnd={completed} />);

    const separator = screen.getByRole('separator', { name: 'Resize panel' });
    expect(separator).toHaveAttribute('aria-valuenow', '300');
    expect(separator).toHaveAttribute('aria-valuemin', '220');
    expect(separator).toHaveAttribute('aria-valuemax', '480');
    fireEvent.keyDown(separator, { key: 'ArrowRight' });
    fireEvent.keyDown(separator, { key: 'ArrowLeft' });

    expect(resize).toHaveBeenNthCalledWith(1, 12);
    expect(resize).toHaveBeenNthCalledWith(2, -12);
    expect(completed).toHaveBeenCalledTimes(2);
  });

  it('ends an active drag when pointer capture is lost', () => {
    const completed = vi.fn();
    render(<ResizeHandle label="Resize panel" value={300} minimum={220} maximum={480} onResize={vi.fn()} onResizeEnd={completed} />);
    const separator = screen.getByRole('separator', { name: 'Resize panel' });
    Object.defineProperty(separator, 'setPointerCapture', { configurable: true, value: vi.fn() });

    const pointerDown = new MouseEvent('pointerdown', { bubbles: true, button: 0, clientX: 10 });
    Object.defineProperty(pointerDown, 'pointerId', { value: 7 });
    fireEvent(separator, pointerDown);
    const lostCapture = new Event('lostpointercapture', { bubbles: true });
    Object.defineProperty(lostCapture, 'pointerId', { value: 7 });
    fireEvent(separator, lostCapture);

    expect(completed).toHaveBeenCalledOnce();
  });
});
