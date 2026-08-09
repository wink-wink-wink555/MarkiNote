import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '@/app/App';
import '@/shared/i18n';
import { loadUiPreferences, readingWidthCssValue } from '@/shared/lib/preferences';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';
import { ToastProvider } from '@/shared/ui/Toast';
import '@/shared/styles/tokens.css';
import '@/shared/styles/global.css';
import '@/shared/styles/app.css';

const initialPreferences = loadUiPreferences();
const root = document.documentElement;
root.dataset.theme = initialPreferences.theme;
root.dataset.density = initialPreferences.density;
root.style.setProperty('--reading-font-size', `${initialPreferences.readingFontSize}px`);
root.style.setProperty('--editor-font-size', `${initialPreferences.editorFontSize}px`);
root.style.setProperty('--line-height-reading', String(initialPreferences.readingLineHeight));
root.style.setProperty('--reading-width', readingWidthCssValue(initialPreferences.readingWidth));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: (failures, error) => failures < 2 && !(error instanceof DOMException && error.name === 'AbortError'), refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode><ErrorBoundary><QueryClientProvider client={queryClient}><ToastProvider><App /></ToastProvider></QueryClientProvider></ErrorBoundary></StrictMode>,
);
