import { Bot, Pencil, RotateCcw } from 'lucide-react';
import { memo, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { basename } from '@/shared/lib/format';
import type { MessageEntry } from '../model/types';
import { ChatMarkdown } from './ChatMarkdown';

const offscreenMessageStyle: CSSProperties = {
  contentVisibility: 'auto',
  containIntrinsicSize: 'auto 160px',
};

interface Props {
  entry: MessageEntry;
  showTyping: boolean;
  rollbackDisabled?: boolean;
  onEdit: (entry: MessageEntry) => void;
  onRollback: (entry: MessageEntry) => void;
}

export const ChatMessage = memo(function ChatMessage({ entry, showTyping, rollbackDisabled = false, onEdit, onRollback }: Props) {
  const { t } = useTranslation();
  return <article
    className={`chat-message ai-message-item ${entry.role} ${entry.error ? 'error' : ''}`}
    style={offscreenMessageStyle}
    aria-busy={showTyping || undefined}
  >
    {entry.role === 'assistant' && <span className="message-avatar" aria-hidden="true"><Bot size={14} /></span>}
    <div className="message-content">
      {entry.content ? <ChatMarkdown content={entry.content} /> : showTyping && <div className="typing" aria-hidden="true">
        <span /><span /><span />
      </div>}
      {entry.errorMessage && <small className="message-error" role="alert">{entry.errorMessage}</small>}
      {entry.attachments?.length ? <div className="message-attachments">
        {entry.attachments.map((file) => <span key={file}>{basename(file)}</span>)}
      </div> : null}
      {entry.reasoning && <details><summary>{t('details')}</summary><pre>{entry.reasoning}</pre></details>}
      {entry.stopped && <small className="stopped-label">{t('stopped')}</small>}
      {entry.role === 'user' && <div className="modal-actions ai-message-actions">
        <button type="button" className="icon-button ai-message-action-button" disabled={rollbackDisabled} aria-busy={rollbackDisabled || undefined} aria-label={t('editMessage')} title={t('editMessage')} onClick={() => onEdit(entry)}><Pencil size={14} aria-hidden="true" /></button>
        <button type="button" className="icon-button ai-message-action-button ai-message-rollback-button" disabled={rollbackDisabled} aria-busy={rollbackDisabled || undefined} aria-label={t('rollbackMessage')} title={t('rollbackMessage')} onClick={() => {
          if (window.confirm(t('rollbackConfirm'))) onRollback(entry);
        }}><RotateCcw size={14} aria-hidden="true" /></button>
      </div>}
    </div>
  </article>;
});
