import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { renderApp } from '@/test/render';

function mockViewport(width: number) {
  return vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
    matches: (() => {
      const maximum = /max-width:\s*(\d+)px/.exec(query)?.[1];
      return maximum ? width <= Number(maximum) : false;
    })(),
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }));
}

describe('App', () => {
  it('loads, filters, and previews a document through the v1 API', async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    const search = screen.getByRole('searchbox', { name: 'Search all files and folders' });
    await user.type(search, 'missing');
    expect(await screen.findByText('No matching files or folders')).toBeInTheDocument();
    await user.clear(search);
    await user.click(screen.getByText('Guide.md'));
    expect(await screen.findByRole('heading', { name: 'Guide', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Guide.md', level: 1 })).toBeInTheDocument();
  });

  it('provides a workspace skip link and native theme radio controls', async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Skip to document workspace' })).toHaveAttribute('href', '#workspace-main');

    await user.click(screen.getByRole('button', { name: 'Settings' }));
    const light = screen.getByRole('radio', { name: 'Light' });
    const dark = screen.getByRole('radio', { name: 'Dark' });
    expect(light).toBeChecked();
    await user.click(dark);
    expect(dark).toBeChecked();
  });

  it('keeps both side panels available together on docked layouts', async () => {
    const media = mockViewport(1_100);
    const user = userEvent.setup();
    renderApp(<App />);
    expect(await screen.findByText('Guide.md')).toBeInTheDocument();
    const libraryToggle = screen.getByRole('button', { name: 'Library' });
    const aiToggle = screen.getByRole('button', { name: 'AI assistant' });

    await user.click(aiToggle);
    expect(aiToggle).toHaveAttribute('aria-expanded', 'true');
    expect(libraryToggle).toHaveAttribute('aria-expanded', 'true');
    const library = screen.getByRole('complementary', { name: 'Library' });
    expect(library).toBeInTheDocument();
    expect(await screen.findByRole('complementary', { name: 'AI assistant' })).toBeInTheDocument();
    expect(within(library).queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();

    await user.click(libraryToggle);
    expect(libraryToggle).toHaveAttribute('aria-expanded', 'false');
    expect(aiToggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByRole('complementary', { name: 'Library' })).not.toBeInTheDocument();
    media.mockRestore();
  });

  it('treats mobile panels as modal drawers and restores focus when they close', async () => {
    const media = mockViewport(320);
    const user = userEvent.setup();
    renderApp(<App />);
    const drawer = await screen.findByRole('dialog', { name: 'Library' });
    const libraryToggle = document.querySelector<HTMLButtonElement>('[aria-controls="library-panel"]')!;
    expect(drawer).toHaveAttribute('aria-modal', 'true');
    expect(document.querySelector('.workspace-main')).toHaveAttribute('inert');
    const closeLibrary = within(drawer).getByRole('button', { name: 'Close' });
    await waitFor(() => expect(closeLibrary).toHaveFocus());
    expect(document.querySelector('.app-drawer-scrim')?.tagName).toBe('DIV');

    await user.click(await within(drawer).findByRole('button', { name: 'Guide.md — More actions' }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Library' })).toBeInTheDocument();

    await user.click(closeLibrary);
    await waitFor(() => expect(libraryToggle).toHaveFocus());

    const aiToggle = screen.getByRole('button', { name: 'AI assistant' });
    await user.click(aiToggle);
    expect(await screen.findByRole('dialog', { name: 'AI assistant' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'New chat' })).toBeInTheDocument();
    await waitFor(() => expect(document.getElementById('ai-panel')).toHaveAttribute('role', 'dialog'));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(aiToggle).toHaveFocus());
    media.mockRestore();
  });
});
