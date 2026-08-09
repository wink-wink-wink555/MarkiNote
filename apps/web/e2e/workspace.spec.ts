import { expect, test, type Page, type Route } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { marked } from 'marked';

const guide = readFileSync(new URL('../../../tests/fixtures/editor-equivalence.md', import.meta.url), 'utf8').trimEnd();
const guideHtml = marked.parse(guide, { async: false });
const shortGuide = '# Short note\n\n*italic text*\n\n~~removed text~~';
const shortGuideHtml = marked.parse(shortGuide, { async: false });

interface StoredPreferences {
  version: number;
  theme: string;
  language: string;
  splitRatio: number;
  sidebarWidth: number;
}

const englishPreferences = {
  version: 2,
  readingGeometryVersion: 2,
  theme: 'light',
  language: 'en',
  sidebarOpen: true,
  aiOpen: false,
  sidebarWidth: 310,
  aiWidth: 390,
  splitRatio: 0.5,
  aiProvider: '',
  aiModel: '',
  readingFontSize: 15,
  editorFontSize: 14,
  readingLineHeight: 1.68,
  readingWidth: 72,
  density: 'comfortable',
  editorLineWrap: true,
} as const;

async function setEnglishPreferences(page: Page) {
  await page.evaluate((preferences) => {
    localStorage.clear();
    localStorage.setItem('markinote.preferences.v2', JSON.stringify(preferences));
  }, englishPreferences);
  await page.reload();
}

async function mockApi(page: Page) {
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => route.fulfill({ status, contentType: 'application/json', headers, body: JSON.stringify(body) });
    if (url.pathname === '/api/v1') return json({ name: 'MarkiNote API', version: '1.0.0', contract: 1 });
    if (url.pathname === '/api/v1/documents') return json({ current_path: '', items: [
      { name: 'Guide.md', path: 'Guide.md', type: 'file', size: guide.length, modified: '2026-01-01T00:00:00' },
      { name: 'Short.md', path: 'Short.md', type: 'file', size: shortGuide.length, modified: '2026-01-02T00:00:00' },
    ] });
    if (url.pathname === '/api/v1/documents/search') return json({
      query: url.searchParams.get('q') ?? '',
      items: [{ name: 'Nested Guide.md', path: 'archive/Nested Guide.md', type: 'file', size: 25, modified: '2026-01-01T00:00:00' }],
      total: 1,
      truncated: false,
    });
    if (url.pathname === '/api/v1/documents/changes') return json({ dir_mtime: 1, file_mtime: 1 });
    if (url.pathname === '/api/v1/documents/content' && request.method() === 'GET') {
      const path = url.searchParams.get('path') ?? 'Guide.md';
      const content = path === 'Short.md' ? shortGuide : guide;
      return json({ path, filename: path.split('/').at(-1), content, size: content.length, version: 'v1' });
    }
    if (url.pathname === '/api/v1/rendering/preview') {
      const body = request.postDataJSON() as { markdown?: string };
      return json({ html: body.markdown === shortGuide ? shortGuideHtml : guideHtml });
    }
    if (url.pathname === '/api/v1/documents/content' && request.method() === 'PUT') return json({ success: true, version: 'v2' });
    if (url.pathname === '/api/v1/agent/providers') return json({ providers: { deepseek: { name: 'DeepSeek', models: [{ id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash' }] } }, limits: { max_attachment_files: 5 }, serverKeyConfigured: true });
    if (url.pathname === '/api/v1/conversations') return json({ items: [] });
    if (url.pathname === '/api/v1/agent/chat') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: conversation_id\ndata: {"schemaVersion":1,"runId":"e2e-run","sequence":1,"type":"conversation_id","data":{"id":"e2e-conv"}}\n\nevent: token\ndata: {"schemaVersion":1,"runId":"e2e-run","sequence":2,"type":"token","data":{"content":"Hello from AI"}}\n\nevent: done\ndata: {"schemaVersion":1,"runId":"e2e-run","sequence":3,"type":"done","data":{"conversation_id":"e2e-conv"}}\n\n' });
    return json({
      type: 'about:blank',
      title: 'Unhandled test route',
      status: 500,
      detail: `Unhandled ${url.pathname}`,
      code: 'unhandled_test_route',
    }, 500);
  });
}

test.beforeEach(async ({ page }) => { await mockApi(page); await page.goto('/'); });

test('searches across nested folders and opens the selected result', async ({ page }) => {
  const search = page.getByRole('searchbox', { name: /Search all files and folders|搜索全部文件与文件夹/ });
  await search.fill('nested');

  const nestedResult = page.getByRole('button', { name: /Nested Guide\.md archive\// });
  await expect(nestedResult).toBeVisible();
  await expect(nestedResult).toContainText('archive/Nested Guide.md');
  await nestedResult.click();

  await expect(page.getByRole('heading', { name: 'Nested Guide.md', level: 1 })).toBeVisible();
  // Selecting a result intentionally closes the library drawer on compact
  // layouts; reopen it before checking that the completed query was cleared.
  if (!await search.isVisible()) {
    await page.getByRole('button', { name: /Library|文档库/ }).click();
  }
  await expect(search).toHaveValue('');
});

test('opens, edits, previews, and saves a document', async ({ page }) => {
  await page.getByText('Guide.md').click();
  await expect(page.getByRole('heading', { name: 'Guide 指南', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: /Source|源码|ソース/ }).click();
  const editor = page.locator('.cm-content');
  await expect(editor).toBeVisible();
  const saveRequest = page.waitForRequest((request) => request.url().includes('/api/v1/documents/content') && request.method() === 'PUT');
  await editor.click();
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText('# Guide\n\nChanged content.');
  await expect(editor).toContainText('Changed content.');
  await expect(page.getByText(/Unsaved|未保存/)).toBeVisible();
  expect((await saveRequest).postDataJSON()).toMatchObject({ content: '# Guide\n\nChanged content.', expectedVersion: 'v1' });
  await expect(page.getByText(/Saved|已保存/)).toBeVisible();

  const downloadEvent = page.waitForEvent('download');
  await page.locator('.document-action-menu').getByRole('button', { name: /More actions|更多操作/ }).click();
  await page.getByRole('menuitem', { name: /Download Markdown|下载 Markdown/ }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('Guide.md');
  const downloadedPath = await download.path();
  expect(downloadedPath).not.toBeNull();
  if (downloadedPath === null) throw new Error('The browser did not expose the downloaded Markdown file.');
  expect(readFileSync(downloadedPath, 'utf8')).toBe('# Guide\n\nChanged content.');
});

test('fills the viewport for a short document and keeps both docked panels usable', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile-chrome', 'Docked side panels are a desktop layout.');
  await page.setViewportSize({ width: 1440, height: 900 });
  await setEnglishPreferences(page);

  await page.getByText('Short.md').click();
  await expect(page.getByRole('heading', { name: 'Short note', level: 1 })).toBeVisible();
  await expect(page.locator('.markdown-body em')).toHaveCSS('font-style', 'italic');
  await expect(page.locator('.markdown-body del')).toHaveCSS('text-decoration-line', /line-through/);

  await page.getByRole('button', { name: 'AI assistant' }).click();
  await expect(page.getByRole('complementary', { name: 'Library' })).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'AI assistant' })).toBeVisible();

  const libraryToggle = page.getByRole('button', { name: 'Library' });
  const librarySlot = page.locator('.library-panel-slot');
  const openLibraryWidth = await librarySlot.evaluate((element) => element.getBoundingClientRect().width);
  await libraryToggle.click();
  await page.waitForTimeout(70);
  const closingLibraryWidth = await librarySlot.evaluate((element) => element.getBoundingClientRect().width);
  expect(closingLibraryWidth).toBeGreaterThan(0);
  expect(closingLibraryWidth).toBeLessThan(openLibraryWidth);
  await expect.poll(() => librarySlot.evaluate((element) => element.getBoundingClientRect().width)).toBeLessThan(1);
  await libraryToggle.click();
  await expect.poll(() => librarySlot.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(openLibraryWidth - 2);

  const aiToggle = page.getByRole('button', { name: 'AI assistant' });
  const aiSlot = page.locator('.ai-panel-slot');
  const openAiWidth = await aiSlot.evaluate((element) => element.getBoundingClientRect().width);
  await aiToggle.click();
  await page.waitForTimeout(70);
  const closingAiWidth = await aiSlot.evaluate((element) => element.getBoundingClientRect().width);
  expect(closingAiWidth).toBeGreaterThan(0);
  expect(closingAiWidth).toBeLessThan(openAiWidth);
  await expect.poll(() => aiSlot.evaluate((element) => element.getBoundingClientRect().width)).toBeLessThan(1);
  await aiToggle.click();
  await expect.poll(() => aiSlot.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(openAiWidth - 2);

  const geometry = await page.evaluate(() => {
    const workspace = document.querySelector('.document-workspace')!.getBoundingClientRect();
    const panes = document.querySelector('.workspace-panes')!.getBoundingClientRect();
    const footer = document.querySelector('.document-status')!.getBoundingClientRect();
    return {
      paneToFooterGap: Math.abs(panes.bottom - footer.top),
      footerToWorkspaceGap: Math.abs(footer.bottom - workspace.bottom),
      paneHeight: panes.height,
      workspaceHeight: workspace.height,
    };
  });
  expect(geometry.paneToFooterGap).toBeLessThanOrEqual(1.5);
  expect(geometry.footerToWorkspaceGap).toBeLessThanOrEqual(1.5);
  expect(geometry.paneHeight).toBeGreaterThan(geometry.workspaceHeight * 0.65);
});

test('streams an AI answer without persisting the provider key', async ({ page }, testInfo) => {
  await page.evaluate(() => {
    localStorage.setItem('markinote.ai.credentials.v1', JSON.stringify({
      version: 1,
      keys: { deepseek: 'legacy-versioned-e2e-key' },
    }));
    localStorage.setItem('markinote.apiKey', 'legacy-e2e-key');
  });
  await page.getByRole('button', { name: /AI assistant|AI 助手/ }).click();
  await page.getByRole('button', { name: /More AI actions|更多 AI 操作/ }).click();
  await page.getByRole('menuitem', { name: /AI settings|AI 设置/ }).click();
  await expect(page.getByRole('checkbox', { name: /Allow this chat to modify documents|允许本次对话修改文档/ })).not.toBeChecked();
  await expect(page.locator('.composer-meta')).not.toContainText('/5');
  await page.getByPlaceholder('sk-…').fill('page-memory-e2e-key');
  await page.getByPlaceholder(/Ask about docs|询问文档/).fill('Say hello');
  await page.getByRole('button', { name: /^Send$|^发送$/ }).click();
  await expect(page.getByText('Hello from AI')).toBeVisible();
  const persisted = await page.evaluate(() => {
    let values = '';
    for (let index = 0; index < localStorage.length; index += 1) values += ` ${localStorage.getItem(localStorage.key(index) ?? '') ?? ''}`;
    return {
      values,
      versioned: localStorage.getItem('markinote.ai.credentials.v1'),
      legacy: localStorage.getItem('markinote.apiKey'),
    };
  });
  expect(persisted.versioned).toBeNull();
  expect(persisted.legacy).toBeNull();
  expect(persisted.values).not.toMatch(/page-memory-e2e-key|legacy-versioned-e2e-key|legacy-e2e-key/u);

  await page.reload();
  const restoredAiToggle = page.getByRole('button', { name: /AI assistant|AI 助手/ });
  if (await restoredAiToggle.getAttribute('aria-expanded') !== 'true') await restoredAiToggle.click();
  const restoredAiPanel = testInfo.project.name === 'mobile-chrome'
    ? page.getByRole('dialog', { name: /AI assistant|AI 助手/ })
    : page.getByRole('complementary', { name: /AI assistant|AI 助手/ });
  await expect(restoredAiPanel).toBeVisible();
  await page.getByRole('button', { name: /More AI actions|更多 AI 操作/ }).click();
  await page.getByRole('menuitem', { name: /AI settings|AI 设置/ }).click();
  await expect(page.getByPlaceholder('sk-…')).toHaveValue('');
});

test('restores versioned layout preferences and exposes keyboard resize controls', async ({ page }, testInfo) => {
  await page.evaluate(() => {
    localStorage.clear();
    localStorage.setItem('markinote.preferences.v1', JSON.stringify({
      version: 1,
      theme: 'pink',
      language: 'en',
      sidebarOpen: true,
      aiOpen: false,
      sidebarWidth: 340,
      aiWidth: 390,
      splitRatio: 0.65,
      aiProvider: '',
      aiModel: '',
    }));
  });
  await page.reload();

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'pink');
  const stored = await page.evaluate<StoredPreferences>(() => {
    const parsed: unknown = JSON.parse(localStorage.getItem('markinote.preferences.v2') ?? '{}');
    return parsed as StoredPreferences;
  });
  expect(stored).toMatchObject({ version: 2, theme: 'pink', language: 'en', splitRatio: 0.65, sidebarWidth: 340 });
  expect(await page.evaluate(() => localStorage.getItem('markinote.preferences.v1'))).toBeNull();
  await expect(page.getByRole('main')).toBeVisible();

  if (testInfo.project.name !== 'mobile-chrome') {
    const librarySeparator = page.getByRole('separator', { name: 'Resize library panel' });
    await expect(librarySeparator).toBeVisible();
    await expect(librarySeparator).toHaveAttribute('aria-valuenow', '340');
    await librarySeparator.focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(() => page.evaluate<number>(() => {
      const parsed: unknown = JSON.parse(localStorage.getItem('markinote.preferences.v2') ?? '{}');
      if (!parsed || typeof parsed !== 'object' || !('sidebarWidth' in parsed) || typeof parsed.sidebarWidth !== 'number') return Number.NaN;
      return parsed.sidebarWidth;
    })).toBe(352);

    await page.getByText('Guide.md').click();
    await page.getByRole('button', { name: 'Split' }).click();
    await expect(page.getByRole('separator', { name: 'Resize editor and preview panes' })).toBeVisible();
    await expect(page.getByRole('toolbar', { name: 'Markdown formatting toolbar' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Guide 指南', level: 1 })).toBeVisible();
    await expect(page.locator('.markdown-body strong')).toContainText('企业级等价性');
    await expect(page.locator('.markdown-body em')).toHaveCSS('font-style', 'italic');
    await expect(page.locator('.markdown-body del')).toHaveCSS('text-decoration-line', 'line-through');
    await expect(page.locator('.markdown-body table')).toBeVisible();
    await expect(page.locator('.markdown-body pre code.language-typescript')).toContainText('const message');
    await expect(page.locator('.markdown-body .mermaid svg')).toBeVisible();
    await expect(page.locator('.markdown-body .katex').first()).toBeVisible();
    const formulaHosts = page.locator('.markdown-body [data-math-source]');
    await expect(formulaHosts).toHaveCount(2);
    await expect(formulaHosts.nth(0)).toHaveAttribute('data-math-source', '$E = mc^2$');
    await expect(formulaHosts.nth(1)).toHaveAttribute('data-math-source', /^\$\$\s*\\sum_\{i=1\}\^\{n\} i = \\frac/);
    await expect(page.getByRole('button', { name: 'Copy LaTeX formula' })).toHaveCount(2);
    await page.evaluate(() => {
      const clipboard = {
        writeText: (value: string) => {
          sessionStorage.setItem('e2e.formulaClipboard', value);
          return Promise.resolve();
        },
      };
      Object.defineProperty(Object.getPrototypeOf(navigator), 'clipboard', {
        configurable: true,
        get: () => clipboard,
      });
    });
    expect(await page.evaluate(async () => {
      await navigator.clipboard.writeText('e2e-probe');
      const value = sessionStorage.getItem('e2e.formulaClipboard');
      sessionStorage.removeItem('e2e.formulaClipboard');
      return value;
    })).toBe('e2e-probe');
    const copyFormula = formulaHosts.nth(0).getByRole('button', { name: 'Copy LaTeX formula' });
    await copyFormula.focus();
    await expect(copyFormula).toBeFocused();
    await page.keyboard.press('Enter');
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('e2e.formulaClipboard'))).toBe('$E = mc^2$');
    const previewText = page.locator('.markdown-body').getByText('source-locator-alpha', { exact: true });
    await previewText.evaluate((element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    });
    await previewText.click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Find in source' }).click();
    await expect(page.locator('.cm-content')).toBeFocused();
    await testInfo.attach('workspace-desktop', { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  } else {
    const aiToggle = page.getByRole('button', { name: 'AI assistant' });
    await aiToggle.click();
    await expect(aiToggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByRole('complementary', { name: 'Library' })).toHaveCount(0);

    const libraryToggle = page.getByRole('button', { name: 'Library' });
    await libraryToggle.click();
    await expect(libraryToggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByRole('complementary', { name: 'AI assistant' })).toHaveCount(0);
    await testInfo.attach('workspace-mobile', { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  }
});

test('keeps the workspace usable across phone, tablet, laptop, and desktop widths', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'One Chromium pass covers the responsive CSS breakpoints.');
  test.setTimeout(60_000);
  const viewports = [
    { name: 'phone', width: 320, height: 720, splitOrientation: null },
    { name: 'tablet', width: 768, height: 1024, splitOrientation: 'horizontal' },
    { name: 'laptop', width: 1024, height: 768, splitOrientation: 'horizontal' },
    { name: 'desktop', width: 1440, height: 900, splitOrientation: 'vertical' },
  ] as const;

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    // Let the previous viewport's debounced persistence settle, then restore a
    // deterministic panel state before checking the next breakpoint.
    await page.waitForTimeout(180);
    await setEnglishPreferences(page);

    const dimensions = await page.evaluate(() => ({
      viewport: window.innerWidth,
      html: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
    }));
    expect(dimensions.html).toBeLessThanOrEqual(dimensions.viewport + 1);
    expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport + 1);

    if (viewport.splitOrientation === null) {
      const libraryDrawer = page.getByRole('dialog', { name: /Library|文档库/ });
      await expect(libraryDrawer).toBeVisible();
      const libraryHeading = libraryDrawer.getByRole('heading', { name: /Library|文档库/ });
      const closeLibrary = libraryDrawer.getByRole('button', { name: /Close|关闭/ });
      expect(await libraryHeading.evaluate((heading) => {
        const range = document.createRange();
        range.selectNodeContents(heading);
        return range.getClientRects().length;
      })).toBe(1);
      const drawerBounds = await libraryDrawer.boundingBox();
      const closeBounds = await closeLibrary.boundingBox();
      expect(drawerBounds).not.toBeNull();
      expect(closeBounds).not.toBeNull();
      expect((closeBounds?.x ?? 0) + (closeBounds?.width ?? 0))
        // Fractional device pixels can make flush edges differ slightly even
        // when neither the control nor its drawer overflows the viewport.
        .toBeLessThanOrEqual((drawerBounds?.x ?? 0) + (drawerBounds?.width ?? 0) + 2);
      const aiToggle = page.getByRole('button', { name: /AI assistant|AI 助手/ });
      await aiToggle.click();
      await expect(page.getByRole('dialog', { name: /AI assistant|AI 助手/ })).toBeVisible();
      await page.keyboard.press('Escape');
    } else {
      await page.getByText('Guide.md').click();
      await page.getByRole('button', { name: /Split|分屏/ }).click();
      await expect(page.getByRole('separator', { name: /Resize editor and preview panes|调整编辑与预览比例/ }))
        .toHaveAttribute('aria-orientation', viewport.splitOrientation);
      await expect(page.locator('.cm-content')).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Guide 指南', level: 1 })).toBeVisible();
    }

    await testInfo.attach(`responsive-${viewport.name}`, {
      body: await page.screenshot({ animations: 'disabled' }),
      contentType: 'image/png',
    });
  }
});

test('applies and persists responsive reading and editor preferences', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'One Chromium pass covers the settings layout and persisted CSS tokens.');
  await setEnglishPreferences(page);

  const settingsTrigger = page.getByRole('button', { name: 'Settings' });
  await settingsTrigger.click();
  const dialog = page.getByRole('dialog', { name: 'Settings' });
  await expect(dialog).toBeVisible();

  await dialog.getByRole('slider', { name: 'Body font size' }).fill('18');
  await dialog.getByRole('slider', { name: 'Editor font size' }).fill('16');
  const densityGroup = dialog.getByRole('group', { name: 'Interface density' });
  await densityGroup.getByText('Compact', { exact: true }).click();
  await expect(densityGroup.getByRole('radio', { name: 'Compact' })).toBeChecked();
  const lineHeightGroup = dialog.getByRole('group', { name: 'Body line height' });
  await lineHeightGroup.getByText('Relaxed', { exact: true }).click();
  await expect(lineHeightGroup.getByRole('radio', { name: 'Relaxed' })).toBeChecked();
  const widthGroup = dialog.getByRole('group', { name: 'Content width' });
  await widthGroup.getByText('Wide', { exact: true }).click();
  await expect(widthGroup.getByRole('radio', { name: 'Wide' })).toBeChecked();
  await dialog.getByText('Wrap long lines', { exact: true }).click();
  await expect(dialog.getByRole('checkbox', { name: /Wrap long lines/ })).not.toBeChecked();

  await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');
  await expect.poll(() => page.locator('html').evaluate((element) => ({
    readingFontSize: element.style.getPropertyValue('--reading-font-size'),
    editorFontSize: element.style.getPropertyValue('--editor-font-size'),
    readingLineHeight: element.style.getPropertyValue('--line-height-reading'),
    readingWidth: element.style.getPropertyValue('--reading-width'),
  }))).toEqual({
    readingFontSize: '18px',
    editorFontSize: '16px',
    readingLineHeight: '1.78',
    readingWidth: '86ch',
  });

  await dialog.getByRole('button', { name: 'Confirm' }).click();
  await expect(dialog).toBeHidden();
  await expect(settingsTrigger).toBeFocused();
  await page.reload();

  const persisted = await page.evaluate(() => JSON.parse(localStorage.getItem('markinote.preferences.v2') ?? '{}') as Record<string, unknown>);
  expect(persisted).toMatchObject({
    version: 2,
    readingFontSize: 18,
    editorFontSize: 16,
    readingLineHeight: 1.78,
    readingWidth: 86,
    density: 'compact',
    editorLineWrap: false,
  });
  await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');

  await page.setViewportSize({ width: 320, height: 720 });
  await page.reload();
  const libraryToggle = page.getByRole('button', { name: 'Library' });
  if (await libraryToggle.getAttribute('aria-expanded') === 'true') await libraryToggle.click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    html: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(dimensions.html).toBeLessThanOrEqual(dimensions.viewport + 1);
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport + 1);
  await testInfo.attach('settings-phone', {
    body: await page.screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  });
});

test('honors reduced motion and keeps keyboard editing history usable', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'One Chromium pass covers motion preferences and editor shortcuts.');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await setEnglishPreferences(page);
  await expect.poll(() => page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);

  const transitionDuration = await page.locator('.app-topbar').evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(transitionDuration.split(',').every((duration) => Number.parseFloat(duration) <= 0.01)).toBe(true);
  const panelTransitionDuration = await page.locator('.library-panel-slot').evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(panelTransitionDuration.split(',').every((duration) => Number.parseFloat(duration) <= 0.01)).toBe(true);

  await page.getByText('Guide.md').click();
  await page.getByRole('button', { name: 'Source' }).click();
  const editor = page.locator('.cm-content');
  await expect(editor).toBeVisible();
  await editor.click();
  await page.keyboard.press('ControlOrMeta+F');
  const findPanel = page.getByRole('search', { name: 'Find in document' });
  await expect(findPanel).toBeVisible();
  await findPanel.getByRole('searchbox', { name: 'Find' }).fill('Heading');
  await expect(findPanel.getByRole('status')).toContainText(/match/i);
  await findPanel.getByRole('button', { name: 'Close find' }).click();
  await editor.click();
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.insertText('keyboard history');

  const undo = page.getByRole('button', { name: 'Undo' });
  const redo = page.getByRole('button', { name: 'Redo' });
  await expect(undo).toBeEnabled();
  await undo.click();
  await expect(editor).not.toContainText('keyboard history');
  await expect(redo).toBeEnabled();
  await redo.click();
  await expect(editor).toContainText('keyboard history');

  await editor.click();
  await page.keyboard.press('ControlOrMeta+A');
  const bold = page.getByRole('button', { name: 'Bold' });
  await bold.click();
  await expect(editor).toContainText('**keyboard history**');
  await bold.click();
  await expect(editor).toContainText('keyboard history');
  await expect(editor).not.toContainText('**keyboard history**');

  const saveRequest = page.waitForRequest((request) => request.url().includes('/api/v1/documents/content') && request.method() === 'PUT');
  await editor.click();
  await page.keyboard.press('End');
  await page.keyboard.insertText(' save-now');
  await page.keyboard.press('ControlOrMeta+S');
  await saveRequest;

  await editor.click();
  await page.keyboard.press('Escape');
  await page.keyboard.press('Tab');
  await expect(editor).not.toBeFocused();
  await testInfo.attach('reduced-motion-editor', {
    body: await page.screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  });
});
