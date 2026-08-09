import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, History, KeyRound, MessageSquarePlus, MoreHorizontal, Paperclip, Send, Settings2, ShieldCheck, Square, X } from 'lucide-react';
import { type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { errorMessage, type DocumentMutation } from '@/shared/api';
import { basename } from '@/shared/lib/format';
import { DropdownMenu } from '@/shared/ui/DropdownMenu';
import { aiApi } from '../api/aiApi';
import { useAiChat } from '../model/useAiChat';
import type { MessageEntry } from '../model/types';
import { AttachmentPicker } from './AttachmentPicker';
import { ChatMessage } from './ChatMessage';
import { HistoryPanel } from './HistoryPanel';
import { ToolCard } from './ToolCard';

interface Props {
  open: boolean;
  active?: boolean;
  onClose: () => void;
  contextFile: string;
  language: string;
  onFilesChanged: (source: 'ai' | 'rollback', mutations?: DocumentMutation[]) => void;
  beforeSend?: () => Promise<boolean>;
}

const BOTTOM_FOLLOW_THRESHOLD = 96;
const COMPOSER_FALLBACK_MAX_HEIGHT = 136;

type KeyStatus = {
  kind: 'success' | 'error';
  message: string;
} | null;

function focusSoon(ref: RefObject<HTMLElement | null>): void {
  window.setTimeout(() => ref.current?.focus(), 0);
}

export function ChatPanel({ open, active = open, onClose, contextFile, language, onFilesChanged, beforeSend }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const providers = useQuery({
    queryKey: ['ai-providers'],
    queryFn: aiApi.providers,
    enabled: active,
    staleTime: 60 * 60_000,
  });
  const serverKeyConfigured = providers.data?.serverKeyConfigured ?? false;
  const [dismissedContextFile, setDismissedContextFile] = useState('');
  const requestContextFile = contextFile && dismissedContextFile !== contextFile ? contextFile : '';
  const chat = useAiChat({ contextFile: requestContextFile, language, serverKeyConfigured, onFilesChanged, beforeSend });
  const {
    allowWriteTools,
    clearApiKey,
    loadConversation,
    model: selectedModel,
    provider: selectedProviderId,
    rollbackPending,
    rollbackTool,
    setAllowWriteTools,
    setModel,
    setProvider,
    stop,
    truncate,
  } = chat;
  const [input, setInput] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [keyStatus, setKeyStatus] = useState<KeyStatus>(null);
  const [validating, setValidating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const messages = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const moreTrigger = useRef<HTMLButtonElement>(null);
  const pickerTrigger = useRef<HTMLButtonElement | null>(null);
  const composing = useRef(false);
  const followLatest = useRef(true);

  const maxAttachments = providers.data?.limits.max_attachment_files ?? 5;
  const providerEntries = Object.entries(providers.data?.providers ?? {});
  const selectedProvider = providers.data?.providers[chat.provider];
  const keyAvailable = Boolean(chat.apiKey || serverKeyConfigured);
  const canSubmit = Boolean(active && input.trim() && chat.provider && chat.model && !providers.isPending && !providers.isError && !rollbackPending && !submitting);

  useEffect(() => {
    if (!providers.data) return;
    const first = Object.keys(providers.data.providers)[0];
    if (!first) return;
    const provider = providers.data.providers[selectedProviderId] ? selectedProviderId : first;
    const models = providers.data.providers[provider]?.models ?? [];
    const model = models.some((candidate) => candidate.id === selectedModel) ? selectedModel : models[0]?.id ?? '';
    if (provider !== selectedProviderId) setProvider(provider);
    if (model !== selectedModel) setModel(model);
  }, [providers.data, selectedModel, selectedProviderId, setModel, setProvider]);

  useEffect(() => {
    if (active) {
      followLatest.current = true;
      return;
    }
    stop();
    setKeyStatus(null);
    setValidating(false);
    setSettingsOpen(false);
    setHistoryOpen(false);
    setPickerOpen(false);
  }, [active, stop]);

  useLayoutEffect(() => {
    const field = composer.current;
    if (!field) return;
    field.style.height = 'auto';
    const configuredMaxHeight = Number.parseFloat(window.getComputedStyle(field).maxHeight);
    const maxHeight = Number.isFinite(configuredMaxHeight) && configuredMaxHeight > 0
      ? configuredMaxHeight
      : COMPOSER_FALLBACK_MAX_HEIGHT;
    if (field.scrollHeight <= 0) return;
    field.style.height = `${Math.min(field.scrollHeight, maxHeight)}px`;
    field.style.overflowY = field.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, [active, historyOpen, input]);

  useEffect(() => {
    if (!active || !followLatest.current) return undefined;
    const frame = window.requestAnimationFrame(() => {
      const container = messages.current;
      if (container) container.scrollTop = container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [active, chat.entries, chat.streaming]);

  const focusComposer = useCallback(() => focusSoon(composer), []);
  const openPicker = useCallback((trigger: HTMLButtonElement) => {
    pickerTrigger.current = trigger;
    setPickerOpen(true);
  }, []);
  const closePicker = useCallback(() => {
    setPickerOpen(false);
    focusSoon(pickerTrigger);
  }, []);
  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    focusSoon(moreTrigger);
  }, []);
  const closePanel = useCallback(() => {
    stop();
    setKeyStatus(null);
    setSettingsOpen(false);
    onClose();
    window.setTimeout(() => document.querySelector<HTMLElement>('[aria-controls="ai-panel"]')?.focus(), 0);
  }, [onClose, stop]);
  const showSettings = useCallback(() => {
    setHistoryOpen(false);
    setSettingsOpen(true);
  }, []);
  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    focusSoon(moreTrigger);
  }, []);
  const editMessage = useCallback(async (entry: MessageEntry) => {
    if (!window.confirm(t('editConfirm'))) return;
    const text = await truncate(entry, true);
    if (text !== undefined) {
      setInput(text);
      focusComposer();
    }
  }, [focusComposer, t, truncate]);
  const rollbackMessage = useCallback((entry: MessageEntry) => {
    void truncate(entry, false);
  }, [truncate]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!active || chat.streaming || submitting) return;
    if (!keyAvailable) {
      showSettings();
      window.setTimeout(() => document.querySelector<HTMLInputElement>('#ai-api-key')?.focus(), 0);
      return;
    }
    if (!canSubmit) return;
    const text = input.trim();
    followLatest.current = true;
    // Release the composer as soon as this request is accepted locally so the
    // user can prepare their next message while the stream is still active.
    setInput('');
    setSubmitting(true);
    try {
      const outcome = await chat.send(text);
      if (!outcome.started) {
        setInput((current) => current || text);
      } else if (outcome.completed) {
        await queryClient.invalidateQueries({ queryKey: ['ai-conversations'] });
      }
    } finally {
      setSubmitting(false);
    }
  };
  const handleComposerKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return;
    if (composing.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
    if (chat.streaming) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };
  const validate = async () => {
    if (!chat.apiKey || !chat.provider) return;
    setValidating(true);
    setKeyStatus(null);
    try {
      const result = await aiApi.validateKey(chat.provider, chat.apiKey);
      setKeyStatus({ kind: result.success ? 'success' : 'error', message: result.message });
    } catch (error) {
      setKeyStatus({ kind: 'error', message: errorMessage(error) });
    } finally {
      setValidating(false);
    }
  };

  if (!open) return null;
  return <aside id="ai-panel" className="ai-panel" aria-label={t('ai')} aria-busy={providers.isPending}>
    <header className="ai-header">
      <div className="ai-title">
        <span className="ai-logo" aria-hidden="true"><Bot size={18} /></span>
        <div>
          <h2>{t('ai')}</h2>
          {(chat.streaming || chat.conversationTitle) && <small
            role={chat.streaming ? 'status' : undefined}
            aria-live={chat.streaming ? 'polite' : undefined}
            aria-atomic={chat.streaming || undefined}
          >{chat.streaming ? t('thinking') : chat.conversationTitle}</small>}
        </div>
      </div>
      <div className="ai-header-actions">
        <button className="icon-button" onClick={() => {
          chat.newChat();
          setDismissedContextFile('');
          setHistoryOpen(false);
          followLatest.current = true;
          focusComposer();
        }} aria-label={t('newChat')} title={t('newChat')}><MessageSquarePlus size={17} aria-hidden="true" /></button>
        <DropdownMenu
          align="end"
          label={t('aiMoreActions')}
          buttonRef={moreTrigger}
          trigger={<MoreHorizontal size={18} aria-hidden="true" />}
          triggerClassName={`icon-button ${historyOpen || settingsOpen ? 'active' : ''}`}
          items={[
            {
              id: 'history',
              label: t('history'),
              icon: <History size={16} />,
              onSelect: () => {
                setSettingsOpen(false);
                setHistoryOpen(true);
              },
            },
            {
              id: 'settings',
              label: t('aiSettings'),
              icon: <Settings2 size={16} />,
              onSelect: showSettings,
            },
          ]}
        />
        <button className="icon-button" onClick={closePanel} aria-label={t('close')}><X size={18} aria-hidden="true" /></button>
      </div>
    </header>
    {providers.isPending && <div className="ai-panel-loading" role="status">{t('loading')}</div>}
    {providers.isError && <div className="ai-panel-loading error" role="alert">
      <span>{errorMessage(providers.error)}</span>
      <button type="button" className="button button-small" onClick={() => void providers.refetch()}>{t('retry')}</button>
    </div>}

    {historyOpen ? <HistoryPanel
      onBack={closeHistory}
      onLoad={(id) => {
        void loadConversation(id);
        setHistoryOpen(false);
        followLatest.current = true;
        focusComposer();
      }}
      activeId={chat.conversationId}
      onDeletedActive={chat.newChat}
    /> : <>
      {settingsOpen && <section id="ai-settings-panel" className="ai-settings-panel" aria-label={t('aiSettings')}>
        <div className="settings-grid">
          <label>{t('provider')}<select name="markinote-ai-provider" value={chat.provider} onChange={(event) => {
            const id = event.target.value;
            chat.setProvider(id);
            chat.setModel(providers.data?.providers[id]?.models[0]?.id ?? '');
            setKeyStatus(null);
          }}>{providerEntries.map(([id, provider]) => <option value={id} key={id}>{provider.name}</option>)}</select></label>
          <label>{t('model')}<select name="markinote-ai-model" value={chat.model} onChange={(event) => chat.setModel(event.target.value)}>
            {selectedProvider?.models.map((model) => <option value={model.id} key={model.id}>{model.name}</option>)}
          </select></label>
        </div>
        <div className="api-key-setting">
          <label htmlFor="ai-api-key">{t('apiKey')}</label>
          <div className="key-input">
            <KeyRound size={15} aria-hidden="true" />
            <input id="ai-api-key" name="markinote-ai-api-key" type="password" autoComplete="off" autoCapitalize="none" spellCheck={false} value={chat.apiKey} aria-invalid={keyStatus?.kind === 'error' || undefined} aria-describedby={`ai-api-key-help${keyStatus ? ' ai-api-key-status' : ''}`} onChange={(event) => {
              chat.setApiKey(event.target.value);
              setKeyStatus(null);
            }} placeholder="sk-…" />
            <button type="button" className="icon-button" disabled={!chat.apiKey} aria-label={t('clearApiKey')} title={t('clearApiKey')} onClick={() => {
              clearApiKey();
              setKeyStatus(null);
            }}><X size={15} aria-hidden="true" /></button>
            <button type="button" className="button button-small" disabled={!chat.apiKey || validating} onClick={() => void validate()}>
              {validating ? t('validating') : t('validate')}
            </button>
          </div>
          <small id="ai-api-key-help">{chat.apiKey ? t('apiKeyMemory') : serverKeyConfigured ? t('serverApiKey') : t('apiKeyMemory')}</small>
        </div>
        {keyStatus && <div id="ai-api-key-status" className={`key-status ${keyStatus.kind === 'error' ? 'danger' : ''}`} role={keyStatus.kind === 'error' ? 'alert' : 'status'} aria-live={keyStatus.kind === 'error' ? 'assertive' : 'polite'} aria-atomic="true">{keyStatus.message}</div>}
        <label className="toggle-row"><input name="markinote-ai-write-tools" type="checkbox" checked={allowWriteTools} onChange={(event) => setAllowWriteTools(event.target.checked)} /><span><strong>{t('writeTools')}</strong><small>{t('writeToolsHint')}</small></span></label>
        <div className="modal-actions"><button type="button" className="button button-small" onClick={closeSettings} aria-label={`${t('close')}: ${t('aiSettings')}`}>{t('close')}</button></div>
      </section>}

      <div
        id="ai-message-log"
        ref={messages}
        className="ai-messages"
        role="log"
        aria-label={t('ai')}
        aria-live="polite"
        aria-relevant="additions text"
        aria-busy={chat.streaming}
        onScroll={(event) => {
          const container = event.currentTarget;
          followLatest.current = container.scrollHeight - container.scrollTop - container.clientHeight <= BOTTOM_FOLLOW_THRESHOLD;
        }}
      >
        {chat.entries.length === 0 && <div className="ai-welcome ai-welcome-compact">
          <div className="ai-welcome-copy">
            <span className="ai-logo" aria-hidden="true"><Bot size={18} /></span>
            <div><h3>{t('aiWelcomeTitle')}</h3><p>{t('aiWelcomeBody')}</p></div>
          </div>
          <div className="ai-welcome-actions">
            <button type="button" className="button" onClick={(event) => openPicker(event.currentTarget)} aria-haspopup="dialog" aria-expanded={pickerOpen}><Paperclip size={15} />{t('attach')}</button>
          </div>
        </div>}
        {chat.entries.map((entry) => entry.kind === 'tool'
          ? <ToolCard
              key={entry.id}
              entry={entry}
              onRollback={rollbackTool}
              rollbackDisabled={rollbackPending}
              onResolveApproval={chat.resolveApproval}
              approvalDisabled={rollbackPending || chat.streaming}
            />
          : <ChatMessage
              key={entry.id}
              entry={entry}
              showTyping={chat.streaming && entry.role === 'assistant' && !entry.content}
              rollbackDisabled={rollbackPending}
              onEdit={editMessage}
              onRollback={rollbackMessage}
            />)}
      </div>

      <div className="ai-composer">
        {requestContextFile || chat.attachments.length ? <div className="attachment-chips">
          {requestContextFile && <span className="attachment-chip context">
            {t('currentContext', { name: basename(requestContextFile) })}
            <button type="button" aria-label={`${t('remove')}: ${basename(requestContextFile)}`} onClick={() => setDismissedContextFile(requestContextFile)}><X size={13} aria-hidden="true" /></button>
          </span>}
          {chat.attachments.map((file) => <span className="attachment-chip" key={file}>{basename(file)}<button type="button" aria-label={`${t('remove')}: ${basename(file)}`} onClick={() => chat.setAttachments(chat.attachments.filter((item) => item !== file))}><X size={13} aria-hidden="true" /></button></span>)}
        </div> : null}
        <form onSubmit={submit} aria-label={t('messageLabel')}>
          <button
            type="button"
            className="icon-button"
            onClick={(event) => openPicker(event.currentTarget)}
            aria-label={t('attach')}
            aria-haspopup="dialog"
            aria-expanded={pickerOpen}
          ><Paperclip size={18} aria-hidden="true" /></button>
          <textarea
            ref={composer}
            id="ai-composer-input"
            className="ai-composer-field"
            name="markinote-ai-message"
            rows={1}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={() => { composing.current = false; }}
            onKeyDown={handleComposerKeyDown}
            placeholder={t('messagePlaceholder')}
            aria-label={t('messageLabel')}
            aria-describedby="ai-composer-meta"
          />
          <button
            type={chat.streaming ? 'button' : 'submit'}
            onClick={chat.streaming ? chat.stop : undefined}
            className="send-button"
            disabled={!chat.streaming && !canSubmit}
            aria-busy={submitting || undefined}
            aria-label={chat.streaming ? t('stop') : t('send')}
            aria-controls="ai-message-log"
          >{chat.streaming ? <Square size={15} fill="currentColor" aria-hidden="true" /> : <Send size={17} aria-hidden="true" />}</button>
        </form>
        <div id="ai-composer-meta" className="composer-meta">
          <span><ShieldCheck size={12} aria-hidden="true" />{chat.apiKey ? t('apiKeyMemory') : serverKeyConfigured ? t('serverApiKey') : t('apiKeyMemory')}</span>
        </div>
      </div>
      {pickerOpen && <AttachmentPicker
        open
        selected={chat.attachments}
        reserved={requestContextFile ? [requestContextFile] : []}
        limit={maxAttachments}
        onChange={chat.setAttachments}
        onClose={closePicker}
      />}
    </>}
  </aside>;
}
