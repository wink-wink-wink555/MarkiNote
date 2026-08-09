import { apiClient, http, unwrap, type ApiComponents, type GeneratedDocumentItem, type LibraryItem, type OperationResult } from '@/shared/api';

type DocumentList = ApiComponents['schemas']['DocumentList'];
type DocumentSearch = ApiComponents['schemas']['DocumentSearchResponse'];
type FolderList = ApiComponents['schemas']['FolderListResponse'];
type CreatedFile = ApiComponents['schemas']['CreatedFileResponse'];
type CreatedFolder = ApiComponents['schemas']['CreatedFolderResponse'];
type RenamedDocument = ApiComponents['schemas']['RenamedDocumentResponse'];
type MovedDocument = ApiComponents['schemas']['MovedDocumentResponse'];
type DeletedDocument = ApiComponents['schemas']['DeletedDocumentResponse'];

export const libraryApi = {
  list: async (path: string, signal?: AbortSignal) => {
    const result = unwrap<DocumentList>(await apiClient.GET('/api/v1/documents', { params: { query: { path } }, signal }));
    return { ...result, items: result.items.map((item: GeneratedDocumentItem): LibraryItem => ({ name: item.name, path: item.path, type: item.type === 'folder' ? 'folder' : 'file', size: item.size ?? undefined, modified: item.modified ?? undefined })) };
  },
  search: async (query: string, signal?: AbortSignal) => {
    const result = unwrap<DocumentSearch>(await apiClient.GET('/api/v1/documents/search', { params: { query: { q: query, limit: 80 } }, signal }));
    return { ...result, items: result.items.map((item: GeneratedDocumentItem): LibraryItem => ({ name: item.name, path: item.path, type: item.type === 'folder' ? 'folder' : 'file', size: item.size ?? undefined, modified: item.modified ?? undefined })) };
  },
  folders: async () => unwrap<FolderList>(await apiClient.GET('/api/v1/documents/folders')),
  createFile: async (path: string, name: string) => unwrap<CreatedFile>(await apiClient.POST('/api/v1/documents/files', { body: { path, name } })),
  createFolder: async (path: string, name: string) => unwrap<CreatedFolder>(await apiClient.POST('/api/v1/documents/folders', { body: { path, name } })),
  rename: async (oldPath: string, newName: string) => unwrap<RenamedDocument>(await apiClient.POST('/api/v1/documents/rename', { body: { oldPath, newName } })),
  move: async (source: string, target: string) => unwrap<MovedDocument>(await apiClient.POST('/api/v1/documents/move', { body: { source, target } })),
  delete: async (path: string) => unwrap<DeletedDocument>(await apiClient.DELETE('/api/v1/documents', { params: { query: { path } } })),
  upload: (path: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    form.append('path', path);
    return http.post<OperationResult>('/api/v1/documents/upload', form);
  },
};
