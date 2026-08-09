import type { components } from '@markinote/api-client';

export type ItemKind = 'file' | 'folder';
export type GeneratedDocumentItem = components['schemas']['DocumentItem'];

export interface LibraryItem {
  name: string;
  path: string;
  type: ItemKind;
  size?: number;
  modified?: string;
}

export type FolderOption = components['schemas']['FolderItem'];

export interface PreviewDocument {
  html: string;
  raw_markdown: string;
  filename: string;
  version: string;
}

export type ProviderModel = components['schemas']['ProviderModel'];

export type ProviderDescriptor = components['schemas']['ProviderInfo'];

export type ProvidersResponse = components['schemas']['ProvidersResponse'];

export interface ConversationSummary {
  id: string;
  title: string;
  created_at?: string | null;
  updated_at?: string | null;
  message_count: number;
}

export interface ToolCall {
  id: string;
  type: 'function';
  function: { name: string; arguments: string };
}

export type ToolApprovalReason = 'unselected_resource' | 'external_content';

export interface ToolMeta {
  call_id: string;
  name: string;
  args: Record<string, unknown>;
  backup_info?: { type?: string; path?: string; target?: string; operation_index?: number } | null;
  backup_group_id?: string | null;
  approval?: {
    id: string;
    status: 'pending' | 'approved' | 'denied';
    target: string;
    reason: ToolApprovalReason;
  } | null;
  resolved_approval_id?: string | null;
}

export interface StoredMessage {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  tool_meta?: ToolMeta;
  reasoning?: string;
  attachments?: string[];
  context_file?: string | null;
}

export interface DocumentMutation {
  type: string;
  path: string;
  target?: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: StoredMessage[];
}

export type ChatSseEvent = components['schemas']['AgentEvent'];

export type ChatRequest = components['schemas']['ChatRequest'];

export interface OperationResult {
  success: true;
  message?: string;
  new_path?: string;
  new_name?: string;
  filename?: string;
  path?: string;
}
