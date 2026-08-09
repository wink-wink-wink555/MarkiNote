import { useCallback, useEffect, useRef, useState } from 'react';
import type { Conversation, DocumentMutation } from '@/shared/api';
import { ApiError, errorMessage } from '@/shared/api';
import i18n from '@/shared/i18n';
import { uid } from '@/shared/lib/format';
import { loadUiPreferences, updateUiPreferences } from '@/shared/lib/preferences';
import { useToast } from '@/shared/ui/Toast';
import { aiApi } from '../api/aiApi';
import { clearApiKeys, loadApiKey, removeApiKey, saveApiKey } from './apiKeyStorage';
import type { ChatEntry, MessageEntry, ToolEntry } from './types';

const MUTATING_TOOL_NAMES = new Set(['write_file', 'edit_file', 'create_file', 'create_folder', 'delete_item', 'move_item']);
const DEFAULT_ALLOW_WRITE_TOOLS = false;

function safeArgs(value: string): Record<string, unknown> {
  try { const parsed = JSON.parse(value) as unknown; return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}; }
  catch { return {}; }
}

function displayUserContent(value: string, attachments?: string[] | null): string {
  if (!attachments?.length) return value;
  const suffix = `\n\n[Attachments: ${attachments.join(', ')}]`;
  return value.endsWith(suffix) ? value.slice(0, -suffix.length) : value;
}

function documentMutation(value: unknown): DocumentMutation | undefined {
  if (typeof value !== 'object' || value === null) return undefined;
  const info = value as { type?: unknown; path?: unknown; target?: unknown };
  if (typeof info.type !== 'string' || typeof info.path !== 'string') return undefined;
  return {
    type: info.type,
    path: info.path,
    ...(typeof info.target === 'string' ? { target: info.target } : {}),
  };
}

function conversationEntries(conversation: Conversation): ChatEntry[] {
  const entries: ChatEntry[] = [];
  const calls = new Map<string, string>();
  let ordinal = 0;
  for (const message of conversation.messages) {
    if (message.role === 'user') {
      entries.push({ kind: 'message', id: uid('user'), role: 'user', content: displayUserContent(message.content, message.attachments), ordinal, attachments: message.attachments }); ordinal += 1;
    } else if (message.role === 'assistant') {
      if (message.content) entries.push({ kind: 'message', id: uid('assistant'), role: 'assistant', content: message.content, reasoning: message.reasoning });
      for (const call of message.tool_calls ?? []) {
        const id = uid('tool'); calls.set(call.id, id);
        entries.push({ kind: 'tool', id, callId: call.id, name: call.function.name, args: safeArgs(call.function.arguments), result: '', status: 'running' });
      }
    } else if (message.role === 'tool' && message.tool_meta) {
      const meta = message.tool_meta;
      const existingId = calls.get(meta.call_id);
      if (existingId) {
        const index = entries.findIndex((entry) => entry.id === existingId);
        const existing = entries[index] as ToolEntry | undefined;
        if (existing) entries[index] = {
          ...existing,
          args: meta.args ?? existing.args,
          result: message.content,
          status: 'done',
          backupInfo: meta.backup_info,
          backupGroupId: meta.backup_group_id,
          approval: meta.approval ? { ...meta.approval, status: meta.approval.status } : undefined,
        };
      } else entries.push({
        kind: 'tool',
        id: uid('tool'),
        callId: meta.call_id,
        name: meta.name,
        args: meta.args ?? {},
        result: message.content,
        status: 'done',
        backupInfo: meta.backup_info,
        backupGroupId: meta.backup_group_id,
        approval: meta.approval ? { ...meta.approval, status: meta.approval.status } : undefined,
      });
    }
  }
  return entries;
}

function rollbackErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)
    || !['conversation_truncate_not_committed', 'rollback_failed'].includes(error.code)) {
    return errorMessage(error);
  }
  const results = error.payload?.rollbackResults;
  const resultMessages = Array.isArray(results)
    ? results.flatMap((item) => (
      typeof item === 'object' && item !== null && typeof (item as { message?: unknown }).message === 'string'
        ? [(item as { message: string }).message]
        : []
    ))
    : [];
  const reason = [error.message, ...resultMessages].join(' ').toLowerCase();
  if (reason.includes('changed after the ai operation') || reason.includes('live state')) {
    return i18n.t('rollbackConflict');
  }
  if (reason.includes('snapshot is unavailable') || reason.includes('older backup cannot verify')
    || reason.includes('backup does not exist') || reason.includes('备份不存在')) {
    return i18n.t('rollbackUnavailable');
  }
  return i18n.t('rollbackNotCompleted');
}

interface Options {
  contextFile: string;
  language: string;
  serverKeyConfigured: boolean;
  onFilesChanged: (source: 'ai' | 'rollback', mutations?: DocumentMutation[]) => void;
  beforeSend?: () => Promise<boolean>;
}

export function useAiChat({ contextFile, language, serverKeyConfigured, onFilesChanged, beforeSend }: Options) {
  const toast = useToast();
  const [initialPreferences] = useState(loadUiPreferences);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [conversationId, setConversationId] = useState('');
  const [conversationTitle, setConversationTitle] = useState('');
  const [provider, setProviderState] = useState(initialPreferences.aiProvider);
  const [model, setModelState] = useState(initialPreferences.aiModel);
  const [apiKey, setApiKeyState] = useState(() => loadApiKey(initialPreferences.aiProvider));
  const [allowWriteTools, setAllowWriteTools] = useState(DEFAULT_ALLOW_WRITE_TOOLS);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [rollbackPending, setRollbackPending] = useState(false);
  const abortController = useRef<AbortController | null>(null);
  const conversationLoadSequence = useRef(0);
  const conversationViewEpoch = useRef(0);
  const rollbackInFlight = useRef(false);
  const approvalInFlight = useRef<Set<string>>(new Set());
  const streamInFlight = useRef(false);
  const apiKeyRef = useRef(apiKey);
  const pendingTokens = useRef<Map<string, string>>(new Map());
  const scheduledTokenFlush = useRef<number | null>(null);
  const tokenFlushUsesAnimationFrame = useRef(false);
  const cancelScheduledTokenFlush = useCallback(() => {
    const scheduled = scheduledTokenFlush.current;
    if (scheduled === null) return;
    if (tokenFlushUsesAnimationFrame.current) window.cancelAnimationFrame(scheduled);
    else window.clearTimeout(scheduled);
    scheduledTokenFlush.current = null;
  }, []);
  const commitTokenBuffer = useCallback(() => {
    if (!pendingTokens.current.size) return;
    const buffered = pendingTokens.current;
    pendingTokens.current = new Map();
    setEntries((current) => current.map((entry) => {
      if (entry.kind !== 'message') return entry;
      const content = buffered.get(entry.id);
      return content ? { ...entry, content: entry.content + content } : entry;
    }));
  }, []);
  const flushTokenBuffer = useCallback(() => {
    cancelScheduledTokenFlush();
    commitTokenBuffer();
  }, [cancelScheduledTokenFlush, commitTokenBuffer]);
  const clearTokenBuffer = useCallback(() => {
    cancelScheduledTokenFlush();
    pendingTokens.current.clear();
  }, [cancelScheduledTokenFlush]);
  const queueToken = useCallback((assistantId: string, content: string) => {
    pendingTokens.current.set(assistantId, `${pendingTokens.current.get(assistantId) ?? ''}${content}`);
    if (scheduledTokenFlush.current !== null) return;
    const commit = () => {
      scheduledTokenFlush.current = null;
      commitTokenBuffer();
    };
    if (typeof window.requestAnimationFrame === 'function') {
      tokenFlushUsesAnimationFrame.current = true;
      scheduledTokenFlush.current = window.requestAnimationFrame(commit);
    } else {
      tokenFlushUsesAnimationFrame.current = false;
      scheduledTokenFlush.current = window.setTimeout(commit, 16);
    }
  }, [commitTokenBuffer]);
  const clearApiKey = useCallback(() => {
    apiKeyRef.current = '';
    setApiKeyState('');
    removeApiKey(provider);
  }, [provider]);
  const setApiKey = useCallback((value: string) => {
    apiKeyRef.current = value;
    setApiKeyState(value);
    saveApiKey(provider, value);
  }, [provider]);
  const setProvider = useCallback((value: string) => {
    const storedKey = loadApiKey(value);
    apiKeyRef.current = storedKey;
    setApiKeyState(storedKey);
    setProviderState(value);
    updateUiPreferences({ aiProvider: value });
  }, []);
  const setModel = useCallback((value: string) => {
    setModelState(value);
    updateUiPreferences({ aiModel: value });
  }, []);
  useEffect(() => {
    const pageHide = () => {
      clearApiKeys();
      apiKeyRef.current = '';
      setApiKeyState('');
      abortController.current?.abort();
    };
    window.addEventListener('pagehide', pageHide);
    return () => {
      window.removeEventListener('pagehide', pageHide);
      apiKeyRef.current = '';
      abortController.current?.abort();
      clearTokenBuffer();
    };
  }, [clearTokenBuffer]);
  const newChat = useCallback(() => {
    conversationLoadSequence.current += 1;
    conversationViewEpoch.current += 1;
    abortController.current?.abort(); clearTokenBuffer(); setEntries([]); setConversationId(''); setConversationTitle(''); setAttachments([]); setAllowWriteTools(DEFAULT_ALLOW_WRITE_TOOLS); setStreaming(false);
  }, [clearTokenBuffer]);

  const loadConversation = useCallback(async (id: string) => {
    if (streaming) return;
    const sequence = ++conversationLoadSequence.current;
    try {
      const { conversation } = await aiApi.conversation(id);
      if (sequence !== conversationLoadSequence.current) return;
      conversationViewEpoch.current += 1;
      clearTokenBuffer();
      setConversationId(id); setConversationTitle(conversation.title); setEntries(conversationEntries(conversation)); setAttachments([]); setAllowWriteTools(DEFAULT_ALLOW_WRITE_TOOLS);
    } catch (caught) {
      if (sequence === conversationLoadSequence.current) toast(errorMessage(caught), 'error');
    }
  }, [clearTokenBuffer, streaming, toast]);

  const runRequest = useCallback(async ({
    message,
    files,
    approval,
  }: {
    message: string;
    files: string[];
    approval?: { id: string; decision: 'approve' | 'deny'; target: string };
  }): Promise<{ started: boolean; completed: boolean; approvalResolved: boolean }> => {
    const requestApiKey = apiKeyRef.current;
    if (!message || streamInFlight.current || rollbackInFlight.current
      || (!requestApiKey && !serverKeyConfigured) || !provider || !model) {
      return { started: false, completed: false, approvalResolved: false };
    }
    streamInFlight.current = true;
    if (approval?.decision !== 'deny' && beforeSend && !(await beforeSend())) {
      streamInFlight.current = false;
      return { started: false, completed: false, approvalResolved: false };
    }
    conversationLoadSequence.current += 1;
    const userOrdinal = entries.filter((entry) => entry.kind === 'message' && entry.role === 'user').length;
    const user: MessageEntry = {
      kind: 'message',
      id: uid('user'),
      role: 'user',
      content: message,
      ordinal: userOrdinal,
      attachments: files,
    };
    let assistantId = uid('assistant');
    setEntries((current) => [...current, user, { kind: 'message', id: assistantId, role: 'assistant', content: '' }]);
    setStreaming(true);
    const controller = new AbortController();
    abortController.current = controller;
    let completed = false;
    let approvalResolved = false;
    const mutations: DocumentMutation[] = [];
    try {
      for await (const event of aiApi.chat({
        message,
        conversation_id: conversationId,
        run_id: crypto.randomUUID(),
        provider,
        model,
        api_key: requestApiKey,
        context_file: contextFile,
        attached_files: files,
        language: language as 'zh-CN' | 'en' | 'fr' | 'ja',
        allow_write_tools: allowWriteTools,
        ...(approval ? { approval_id: approval.id, approval_decision: approval.decision } : {}),
      }, controller.signal)) {
        if (event.type === 'conversation_id') setConversationId(event.data.id);
        else if (event.type === 'token') {
          queueToken(assistantId, event.data.content);
        } else if (event.type === 'tool_call') {
          flushTokenBuffer();
          setEntries((current) => {
            const withoutEmpty = current.filter((entry) => !(entry.id === assistantId && entry.kind === 'message' && !entry.content));
            return [...withoutEmpty, { kind: 'tool', id: uid('tool'), callId: event.data.call_id, name: event.data.name, args: event.data.args ?? {}, result: '', status: 'running' }];
          });
          assistantId = uid('assistant');
          setEntries((current) => [...current, { kind: 'message', id: assistantId, role: 'assistant', content: '' }]);
        } else if (event.type === 'tool_result') {
          const mutation = MUTATING_TOOL_NAMES.has(event.data.name)
            ? documentMutation(event.data.backup_info)
            : undefined;
          if (mutation) mutations.push(mutation);
          if (approval && event.data.resolved_approval_id === approval.id) approvalResolved = true;
          setEntries((current) => current.map((entry) => {
            if (event.data.resolved_approval_id && entry.kind === 'tool' && entry.approval?.id === event.data.resolved_approval_id) {
              return {
                ...entry,
                approval: {
                  ...entry.approval,
                  status: event.data.approval?.status === 'denied' ? 'denied' : 'approved',
                },
              };
            }
            if (entry.kind !== 'tool' || entry.callId !== event.data.call_id) return entry;
            return {
              ...entry,
              args: event.data.args ?? entry.args,
              result: event.data.result,
              status: 'done',
              backupInfo: event.data.backup_info,
              backupGroupId: event.data.backup_group_id,
              ...(event.data.approval ? {
                approval: {
                  id: event.data.approval.id,
                  target: event.data.approval.target,
                  reason: event.data.approval.reason,
                  status: event.data.approval.status,
                },
              } : {}),
            };
          }));
        } else if (event.type === 'title_generated') setConversationTitle(event.data.title);
        else if (event.type === 'error') {
          flushTokenBuffer();
          setEntries((current) => current.map((entry) => entry.id === assistantId && entry.kind === 'message' ? {
            ...entry,
            content: entry.content || event.data.message,
            error: true,
            ...(entry.content ? { errorMessage: event.data.message } : {}),
          } : entry));
        } else if (event.type === 'done') {
          flushTokenBuffer();
          completed = true;
        }
      }
      flushTokenBuffer();
      if (completed) setEntries((current) => current.filter((entry) => !(entry.kind === 'message' && entry.role === 'assistant' && !entry.content)));
    } catch (caught) {
      completed = false;
      flushTokenBuffer();
      if (caught instanceof DOMException && caught.name === 'AbortError') {
        setEntries((current) => current.map((entry) => entry.id === assistantId && entry.kind === 'message' ? { ...entry, stopped: true } : entry));
      } else {
        const messageText = errorMessage(caught);
        setEntries((current) => current.map((entry) => entry.id === assistantId && entry.kind === 'message' ? {
          ...entry,
          content: entry.content || messageText,
          error: true,
          ...(entry.content ? { errorMessage: messageText } : {}),
        } : entry));
      }
    } finally {
      flushTokenBuffer();
      setStreaming(false);
      streamInFlight.current = false;
      abortController.current = null;
      if (mutations.length) onFilesChanged('ai', mutations);
    }
    return { started: true, completed, approvalResolved };
  }, [allowWriteTools, beforeSend, contextFile, conversationId, entries, flushTokenBuffer, language, model, onFilesChanged, provider, queueToken, serverKeyConfigured]);

  const send = useCallback(async (
    text: string,
  ): Promise<{ started: boolean; completed: boolean }> => {
    const message = text.trim();
    const files = [...attachments];
    const outcome = await runRequest({ message, files });
    if (outcome.started) setAttachments([]);
    return { started: outcome.started, completed: outcome.completed };
  }, [attachments, runRequest]);

  const resolveApproval = useCallback(async (
    entry: ToolEntry,
    decision: 'approve' | 'deny',
  ): Promise<boolean> => {
    const approval = entry.approval;
    if (!approval || !['pending', 'failed'].includes(approval.status)
      || approvalInFlight.current.has(approval.id)) return false;
    approvalInFlight.current.add(approval.id);
    setEntries((current) => current.map((candidate) => candidate.kind === 'tool' && candidate.approval?.id === approval.id
      ? { ...candidate, approval: { ...candidate.approval, status: 'submitting' } }
      : candidate));
    const message = decision === 'approve'
      ? i18n.t('toolApprovalUserApproved', { path: approval.target })
      : i18n.t('toolApprovalUserDenied', { path: approval.target });
    try {
      const outcome = await runRequest({
        message,
        files: [],
        approval: { id: approval.id, decision, target: approval.target },
      });
      if (!outcome.started || !outcome.completed || !outcome.approvalResolved) {
        setEntries((current) => current.map((candidate) => candidate.kind === 'tool' && candidate.approval?.id === approval.id
          ? { ...candidate, approval: { ...candidate.approval, status: 'failed' } }
          : candidate));
        return false;
      }
      return true;
    } finally {
      approvalInFlight.current.delete(approval.id);
    }
  }, [runRequest]);

  const truncate = useCallback(async (entry: MessageEntry, edit: boolean): Promise<string | undefined> => {
    if (streaming || rollbackInFlight.current || entry.ordinal === undefined) return undefined;
    rollbackInFlight.current = true;
    setRollbackPending(true);
    const viewEpoch = conversationViewEpoch.current;
    try {
      if (conversationId) {
        const outcome = await aiApi.truncate(conversationId, entry.ordinal, edit);
        if (!outcome.committed) {
          toast(outcome.message, 'error');
          return undefined;
        }
      }
      const sameConversationView = conversationViewEpoch.current === viewEpoch;
      if (sameConversationView) {
        setEntries((current) => {
          const index = current.findIndex((candidate) => candidate.id === entry.id);
          if (index < 0) return current;
          return current.slice(0, edit ? index : index + 1);
        });
      }
      onFilesChanged('rollback');
      return sameConversationView && edit ? entry.content : undefined;
    } catch (caught) {
      toast(rollbackErrorMessage(caught), 'error');
      return undefined;
    } finally {
      rollbackInFlight.current = false;
      setRollbackPending(false);
    }
  }, [conversationId, onFilesChanged, streaming, toast]);

  const rollbackTool = useCallback(async (entry: ToolEntry): Promise<boolean> => {
    const operationIndex = entry.backupInfo?.operation_index;
    if (rollbackInFlight.current || !entry.backupGroupId || typeof operationIndex !== 'number'
      || !Number.isSafeInteger(operationIndex) || operationIndex < 0) return false;
    rollbackInFlight.current = true;
    setRollbackPending(true);
    const viewEpoch = conversationViewEpoch.current;
    try {
      await aiApi.rollback(entry.backupGroupId, operationIndex);
      if (conversationViewEpoch.current === viewEpoch) {
        setEntries((current) => current.map((candidate) => candidate.id === entry.id && candidate.kind === 'tool' ? { ...candidate, status: 'rolled-back' } : candidate));
      }
      onFilesChanged('rollback');
      return true;
    } catch (caught) {
      toast(rollbackErrorMessage(caught), 'error');
      return false;
    } finally {
      rollbackInFlight.current = false;
      setRollbackPending(false);
    }
  }, [onFilesChanged, toast]);
  const stop = useCallback(() => abortController.current?.abort(), []);

  return {
    entries, conversationId, conversationTitle, provider, setProvider, model, setModel, apiKey, setApiKey, clearApiKey,
    allowWriteTools, setAllowWriteTools, attachments, setAttachments, streaming, rollbackPending, send, stop,
    newChat, loadConversation, truncate, rollbackTool, resolveApproval,
  };
}
