import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, MessageSquare, Pencil, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { errorMessage } from '@/shared/api';
import { formatTime } from '@/shared/lib/format';
import { Modal } from '@/shared/ui/Modal';
import { useToast } from '@/shared/ui/Toast';
import { aiApi } from '../api/aiApi';

interface Props {
  onBack: () => void;
  onLoad: (id: string) => void;
  activeId: string;
  onDeletedActive: () => void;
}

interface RenameTarget {
  id: string;
  title: string;
}

export function HistoryPanel({ onBack, onLoad, activeId, onDeletedActive }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const list = useQuery({ queryKey: ['ai-conversations'], queryFn: aiApi.conversations });
  const rename = useMutation({
    mutationFn: ({ id, title }: RenameTarget) => aiApi.renameConversation(id, title),
    onSuccess: async () => {
      setRenameTarget(null);
      setRenameTitle('');
      await queryClient.invalidateQueries({ queryKey: ['ai-conversations'] });
    },
    onError: (error) => toast(errorMessage(error), 'error'),
  });
  const remove = useMutation({
    mutationFn: aiApi.deleteConversation,
    onSuccess: async (_, id) => {
      if (id === activeId) onDeletedActive();
      await queryClient.invalidateQueries({ queryKey: ['ai-conversations'] });
    },
    onError: (error) => toast(errorMessage(error), 'error'),
  });

  const closeRename = () => {
    if (rename.isPending) return;
    setRenameTarget(null);
    setRenameTitle('');
  };

  return <>
    <div id="ai-history-panel" className="history-panel">
      <header>
        <button type="button" className="icon-button" onClick={onBack} aria-label={t('back')}>
          <ArrowLeft size={18} aria-hidden="true" />
        </button>
        <h3>{t('history')}</h3>
      </header>
      <div className="history-list" role="list" aria-busy={list.isLoading}>
        {list.isLoading && <div className="sidebar-state" role="status">{t('loading')}</div>}
        {list.isError && <div className="sidebar-state error" role="alert">
          <span>{errorMessage(list.error)}</span>
          <button type="button" className="button button-small" onClick={() => void list.refetch()}>{t('retry')}</button>
        </div>}
        {list.data?.conversations.length === 0 && <div className="sidebar-state">
          <MessageSquare size={24} aria-hidden="true" />
          {t('noConversations')}
        </div>}
        {list.data?.conversations.map((conversation) => <div
          role="listitem"
          className={`history-row ${conversation.id === activeId ? 'active' : ''}`}
          key={conversation.id}
        >
          <button
            type="button"
            className="history-main"
            aria-current={conversation.id === activeId ? 'true' : undefined}
            onClick={() => onLoad(conversation.id)}
          >
            <strong>{conversation.title}</strong>
            <small>{formatTime(conversation.updated_at)} · {t('messagesCount', { count: conversation.message_count })}</small>
          </button>
          <div className="ai-header-actions ai-row-actions">
            <button
              type="button"
              className="icon-button"
              aria-label={t('renameConversation')}
              onClick={() => {
                rename.reset();
                setRenameTarget({ id: conversation.id, title: conversation.title });
                setRenameTitle(conversation.title);
              }}
            >
              <Pencil size={14} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="icon-button danger"
              aria-label={t('deleteConversation')}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(t('deleteConversationConfirm'))) remove.mutate(conversation.id);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
            </button>
          </div>
        </div>)}
      </div>
    </div>

    <Modal
      open={renameTarget !== null}
      title={t('renameConversation')}
      onClose={closeRename}
      dismissible={!rename.isPending}
      size="small"
    >
      <form
        className="modal-body form-stack"
        aria-busy={rename.isPending}
        onSubmit={(event) => {
          event.preventDefault();
          const title = renameTitle.trim();
          if (!renameTarget || !title || title === renameTarget.title || rename.isPending) return;
          rename.mutate({ id: renameTarget.id, title });
        }}
      >
        <label>
          {t('name')}
          <input
            data-modal-initial-focus
            name="conversation-title"
            autoComplete="off"
            value={renameTitle}
            maxLength={100}
            pattern=".*\S.*"
            title={t('name')}
            disabled={rename.isPending}
            onChange={(event) => setRenameTitle(event.target.value)}
            required
          />
        </label>
        <div className="modal-actions">
          <button type="button" className="button" disabled={rename.isPending} onClick={closeRename}>
            {t('cancel')}
          </button>
          <button
            type="submit"
            className="button button-primary"
            disabled={rename.isPending || !renameTitle.trim() || renameTitle.trim() === renameTarget?.title}
          >
            {t('confirm')}
          </button>
        </div>
      </form>
    </Modal>
  </>;
}
