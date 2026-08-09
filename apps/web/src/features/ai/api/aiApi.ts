import { ApiError, apiClient, apiErrorFromProblem, apiUrl, parseEventStream, unwrap, type ApiComponents, type ChatRequest, type ChatSseEvent, type Conversation, type ProvidersResponse, type ToolApprovalReason } from '@/shared/api';

type ConversationList = ApiComponents['schemas']['ConversationList'];
interface ConversationResponse { conversation: Conversation }
type ValidateResponse = ApiComponents['schemas']['ValidateKeyResponse'];
type RenameConversationResponse = ApiComponents['schemas']['RenameConversationResponse'];
type DeleteConversationResponse = ApiComponents['schemas']['DeleteConversationResponse'];
type TruncateConversationResponse = ApiComponents['schemas']['TruncateConversationResponse'];
type RollbackResponse = ApiComponents['schemas']['RollbackResponse'];

const knownEvents = new Set<string>(['conversation_id', 'token', 'tool_call', 'tool_result', 'title_generated', 'error', 'done']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isToolApprovalReason(value: unknown): value is ToolApprovalReason {
  return value === 'unselected_resource' || value === 'external_content';
}

function contractError(): ApiError {
  return new ApiError('Agent stream contract violation', 0, 'stream_contract_error');
}

function incompleteStreamError(): ApiError {
  return new ApiError('Agent stream ended before a terminal event', 0, 'stream_incomplete_error');
}

function decodeAgentEvent(sseType: string, value: unknown): ChatSseEvent | undefined {
  if (!knownEvents.has(sseType)) return undefined;
  if (!isRecord(value) || value.schemaVersion !== 1 || typeof value.runId !== 'string'
    || !value.runId.trim() || value.runId.length > 128 || typeof value.sequence !== 'number'
    || !Number.isSafeInteger(value.sequence) || value.sequence < 1 || value.type !== sseType || !isRecord(value.data)) throw contractError();
  const envelope = { schemaVersion: 1, runId: value.runId, sequence: value.sequence } as const;
  const data = value.data;
  switch (sseType) {
    case 'conversation_id':
      if (typeof data.id !== 'string') throw contractError();
      return { ...envelope, type: 'conversation_id', data: { id: data.id } };
    case 'token':
      if (typeof data.content !== 'string') throw contractError();
      return { ...envelope, type: 'token', data: { content: data.content } };
    case 'tool_call':
      if (typeof data.call_id !== 'string' || typeof data.name !== 'string' || !isRecord(data.args)) throw contractError();
      return { ...envelope, type: 'tool_call', data: { call_id: data.call_id, name: data.name, args: data.args } };
    case 'tool_result': {
      if (typeof data.call_id !== 'string' || typeof data.name !== 'string' || !isRecord(data.args) || typeof data.result !== 'string') throw contractError();
      const backupInfo = data.backup_info;
      const backupGroupId = data.backup_group_id;
      const approval = data.approval;
      const resolvedApprovalId = data.resolved_approval_id;
      if (backupInfo !== undefined && backupInfo !== null && !isRecord(backupInfo)) throw contractError();
      if (backupGroupId !== undefined && backupGroupId !== null && typeof backupGroupId !== 'string') throw contractError();
      if (approval !== undefined && approval !== null && (
        !isRecord(approval)
        || typeof approval.id !== 'string'
        || !['pending', 'approved', 'denied'].includes(String(approval.status))
        || typeof approval.target !== 'string'
        || !isToolApprovalReason(approval.reason)
      )) throw contractError();
      if (resolvedApprovalId !== undefined && resolvedApprovalId !== null && typeof resolvedApprovalId !== 'string') throw contractError();
      const decodedApproval = approval === undefined || approval === null ? approval : {
        id: approval.id as string,
        status: approval.status as 'pending' | 'approved' | 'denied',
        target: approval.target as string,
        reason: approval.reason as ToolApprovalReason,
      };
      return {
        ...envelope,
        type: 'tool_result',
        data: {
          call_id: data.call_id,
          name: data.name,
          args: data.args,
          result: data.result,
          ...(backupInfo !== undefined ? { backup_info: backupInfo } : {}),
          ...(backupGroupId !== undefined ? { backup_group_id: backupGroupId } : {}),
          ...(decodedApproval !== undefined ? { approval: decodedApproval } : {}),
          ...(resolvedApprovalId !== undefined ? { resolved_approval_id: resolvedApprovalId } : {}),
        },
      };
    }
    case 'title_generated':
      if (typeof data.title !== 'string') throw contractError();
      return { ...envelope, type: 'title_generated', data: { title: data.title } };
    case 'error':
      if (typeof data.code !== 'string' || !/^[a-z][a-z0-9_]{0,63}$/.test(data.code)
        || typeof data.message !== 'string') throw contractError();
      return { ...envelope, type: 'error', data: { code: data.code, message: data.message } };
    case 'done':
      if (typeof data.conversation_id !== 'string') throw contractError();
      return { ...envelope, type: 'done', data: { conversation_id: data.conversation_id } };
    default:
      return undefined;
  }
}

export const aiApi = {
  providers: async () => unwrap<ProvidersResponse>(await apiClient.GET('/api/v1/agent/providers')),
  validateKey: async (provider: string, apiKey: string) => unwrap<ValidateResponse>(await apiClient.POST('/api/v1/agent/validate-key', { body: { provider, api_key: apiKey } })),
  conversations: async () => {
    const result = unwrap<ConversationList>(await apiClient.GET('/api/v1/conversations'));
    return { conversations: result.items };
  },
  conversation: async (id: string) => unwrap<ConversationResponse>(await apiClient.GET('/api/v1/conversations/{conversation_id}', { params: { path: { conversation_id: id } } })),
  renameConversation: async (id: string, title: string) => unwrap<RenameConversationResponse>(await apiClient.PATCH('/api/v1/conversations/{conversation_id}', { params: { path: { conversation_id: id } }, body: { title } })),
  deleteConversation: async (id: string) => unwrap<DeleteConversationResponse>(await apiClient.DELETE('/api/v1/conversations/{conversation_id}', { params: { path: { conversation_id: id } } })),
  truncate: async (id: string, userNumber: number, includeUser: boolean) => unwrap<TruncateConversationResponse>(await apiClient.POST('/api/v1/conversations/{conversation_id}/truncate', { params: { path: { conversation_id: id } }, body: { user_message_number: userNumber, include_user_message: includeUser } })),
  rollback: async (backupGroupId: string, operationIndex: number) => unwrap<RollbackResponse>(await apiClient.POST('/api/v1/operations/rollback', { body: { backupGroupId, operationIndex } })),
  async *chat(payload: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatSseEvent> {
    let response: Response;
    try {
      response = await fetch(apiUrl('/api/v1/agent/chat'), {
        method: 'POST', credentials: 'same-origin', headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), signal,
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
      throw new ApiError('Unable to reach the server', 0, 'network_error');
    }
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => undefined);
      throw apiErrorFromProblem(body, response.status, response.statusText);
    }
    if (!response.body) throw new ApiError('Streaming is not supported by this browser', 0, 'stream_unavailable');
    let streamRunId = '';
    let lastSequence = 0;
    let terminalSeen = false;
    for await (const message of parseEventStream(response.body, signal)) {
      if (!knownEvents.has(message.event)) continue;
      if (terminalSeen) throw contractError();
      let decoded: unknown;
      try {
        decoded = JSON.parse(message.data) as unknown;
      } catch { throw contractError(); }
      const event = decodeAgentEvent(message.event, decoded);
      if (!event) continue;
      if ((streamRunId && event.runId !== streamRunId) || event.sequence <= lastSequence) throw contractError();
      streamRunId = event.runId;
      lastSequence = event.sequence;
      if (event.type === 'done' || event.type === 'error') terminalSeen = true;
      yield event;
    }
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    if (!terminalSeen) throw incompleteStreamError();
  },
};
