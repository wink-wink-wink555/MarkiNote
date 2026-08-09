import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions } from '@testing-library/react';
import type { ReactElement } from 'react';
import { ToastProvider } from '@/shared/ui/Toast';

export function renderApp(element: ReactElement, options?: Omit<RenderOptions, 'wrapper'>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><ToastProvider>{element}</ToastProvider></QueryClientProvider>, options);
}
