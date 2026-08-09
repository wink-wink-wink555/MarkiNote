import { delay, http, HttpResponse } from 'msw';

const markdown = '# Guide\n\nWelcome to **MarkiNote**.';
const rendered = '<h1>Guide</h1><p>Welcome to <strong>MarkiNote</strong>.</p>';
const api = (path: string) => `http://localhost${path}`;

export const handlers = [
  http.get(api('/api/v1'), () => HttpResponse.json({ name: 'MarkiNote API', version: '1.0.0', contract: 1 })),
  http.get(api('/api/v1/documents'), ({ request }) => {
    const path = new URL(request.url).searchParams.get('path') ?? '';
    return HttpResponse.json({ success: true, current_path: path, items: path ? [] : [
      { name: 'docs', path: 'docs', type: 'folder', modified: '2026-01-01T12:00:00' },
      { name: 'Guide.md', path: 'Guide.md', type: 'file', size: 42, modified: '2026-01-02T12:00:00' },
      { name: 'Other.md', path: 'Other.md', type: 'file', size: 16, modified: '2026-01-03T12:00:00' },
    ] });
  }),
  http.get(api('/api/v1/documents/search'), ({ request }) => {
    const query = (new URL(request.url).searchParams.get('q') ?? '').toLocaleLowerCase();
    const allItems = [
      { name: 'Guide.md', path: 'Guide.md', type: 'file', size: 42, modified: '2026-01-02T12:00:00' },
      { name: 'Nested Guide.md', path: 'archive/Nested Guide.md', type: 'file', size: 28, modified: '2026-01-04T12:00:00' },
      { name: 'archive', path: 'archive', type: 'folder', modified: '2026-01-04T12:00:00' },
    ];
    const items = allItems.filter((item) => item.path.toLocaleLowerCase().includes(query));
    return HttpResponse.json({ query, items, total: items.length, truncated: false });
  }),
  http.get(api('/api/v1/documents/folders'), () => HttpResponse.json({ success: true, folders: [{ path: '', name: 'Root', level: 0 }, { path: 'docs', name: 'docs', level: 1 }] })),
  http.get(api('/api/v1/documents/changes'), () => HttpResponse.json({ dir_mtime: 1, file_mtime: 1 })),
  http.get(api('/api/v1/documents/content'), ({ request }) => {
    const path = new URL(request.url).searchParams.get('path') ?? '';
    return HttpResponse.json({ path, filename: path.split('/').at(-1), content: markdown, size: markdown.length, modified: '2026-01-02T12:00:00', version: 'v1' });
  }),
  http.post(api('/api/v1/rendering/preview'), () => HttpResponse.json({ html: rendered })),
  http.put(api('/api/v1/documents/content'), () => HttpResponse.json({ success: true, version: 'v2' })),
  http.get(api('/api/v1/agent/providers'), () => HttpResponse.json({ providers: { deepseek: { name: 'DeepSeek', models: [{ id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash' }] } }, limits: { max_attachment_files: 5 }, serverKeyConfigured: true })),
  http.post(api('/api/v1/agent/validate-key'), () => HttpResponse.json({ success: true, message: 'Connected' })),
  http.get(api('/api/v1/conversations'), () => HttpResponse.json({ items: [] })),
  http.post(api('/api/v1/agent/chat'), async () => {
    await delay(5);
    return new HttpResponse('event: conversation_id\ndata: {"schemaVersion":1,"runId":"mock-run","sequence":1,"type":"conversation_id","data":{"id":"conv-1"}}\n\nevent: token\ndata: {"schemaVersion":1,"runId":"mock-run","sequence":2,"type":"token","data":{"content":"Hello"}}\n\nevent: done\ndata: {"schemaVersion":1,"runId":"mock-run","sequence":3,"type":"done","data":{"conversation_id":"conv-1"}}\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
  }),
];
