import { apiClient, unwrap, type ApiComponents, type PreviewDocument } from '@/shared/api';

type LivePreview = ApiComponents['schemas']['RenderMarkdownResponse'];
type DocumentContent = ApiComponents['schemas']['DocumentContent'];
type StoredDocument = ApiComponents['schemas']['StoredDocumentResponse'];
export type UpdateStamp = ApiComponents['schemas']['DocumentChangesResponse'];

export const editorApi = {
  preview: async (path: string, signal?: AbortSignal): Promise<PreviewDocument> => {
    const content = unwrap<DocumentContent>(await apiClient.GET('/api/v1/documents/content', { params: { query: { path } }, signal }));
    const preview = unwrap<LivePreview>(await apiClient.POST('/api/v1/rendering/preview', { body: { markdown: content.content }, signal }));
    return { filename: content.filename, raw_markdown: content.content, html: preview.html, version: content.version };
  },
  render: async (markdown: string, signal?: AbortSignal) => unwrap<LivePreview>(await apiClient.POST('/api/v1/rendering/preview', { body: { markdown }, signal })),
  save: async (path: string, content: string, expectedVersion: string) => unwrap<StoredDocument>(await apiClient.PUT('/api/v1/documents/content', { params: { query: { path } }, body: { content, expectedVersion } })),
  updates: async (folder: string, file: string, signal?: AbortSignal) => unwrap<UpdateStamp>(await apiClient.GET('/api/v1/documents/changes', { params: { query: { path: folder, file } }, signal })),
};
