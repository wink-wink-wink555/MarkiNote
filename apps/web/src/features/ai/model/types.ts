import type { ToolMeta } from '@/shared/api';

export interface MessageEntry {
  kind: 'message';
  id: string;
  role: 'user' | 'assistant';
  content: string;
  ordinal?: number;
  attachments?: string[];
  reasoning?: string;
  error?: boolean;
  errorMessage?: string;
  stopped?: boolean;
}

export interface ToolEntry {
  kind: 'tool';
  id: string;
  callId: string;
  name: string;
  args: Record<string, unknown>;
  result: string;
  status: 'running' | 'done' | 'rolled-back';
  backupInfo?: ToolMeta['backup_info'];
  backupGroupId?: string | null;
  approval?: {
    id: string;
    target: string;
    reason: 'unselected_resource' | 'external_content';
    status: 'pending' | 'submitting' | 'approved' | 'denied' | 'failed';
  };
}

export type ChatEntry = MessageEntry | ToolEntry;
