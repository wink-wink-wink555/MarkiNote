import { describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from './ErrorBoundary';

describe('ErrorBoundary diagnostics', () => {
  it('logs a fixed code without error messages, stacks, props, or document content', () => {
    const secret = 'private-document-body';
    const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    ErrorBoundary.prototype.componentDidCatch(
      new Error(secret),
      { componentStack: `at Secret(${secret})` },
    );

    expect(log).toHaveBeenCalledWith('Unhandled application error [UI_UNHANDLED]');
    expect(JSON.stringify(log.mock.calls)).not.toContain(secret);
  });
});
