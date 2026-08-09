import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';
import i18n from '@/shared/i18n';
import { server } from './mocks/server';

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
beforeEach(async () => { localStorage.clear(); await i18n.changeLanguage('en'); });

Object.defineProperty(window, 'matchMedia', { writable: true, value: (query: string) => ({ matches: false, media: query, onchange: null, addListener: () => undefined, removeListener: () => undefined, addEventListener: () => undefined, removeEventListener: () => undefined, dispatchEvent: () => false }) });
Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: () => undefined });
class TestResizeObserver { observe() { /* test shim */ } unobserve() { /* test shim */ } disconnect() { /* test shim */ } }
globalThis.ResizeObserver = TestResizeObserver;
