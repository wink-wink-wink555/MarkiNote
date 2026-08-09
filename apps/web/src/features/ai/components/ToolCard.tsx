import { Check, ChevronDown, RotateCcw, ShieldAlert, Wrench, X } from 'lucide-react';
import { memo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolEntry } from '../model/types';
import { ToolApprovalPanel, type ToolApprovalDecision } from './ToolApprovalPanel';

function description(entry: ToolEntry): string {
  const path = typeof entry.args.path === 'string' ? entry.args.path : '';
  const query = typeof entry.args.query === 'string' ? entry.args.query : '';
  const source = typeof entry.args.source === 'string' ? entry.args.source : '';
  const target = typeof entry.args.target === 'string' ? entry.args.target : '';
  const details = path || query || [source, target].filter(Boolean).join(' → ');
  return `${entry.name.replaceAll('_', ' ')}${details ? ` · ${details}` : ''}`;
}

interface Props {
  entry: ToolEntry;
  onRollback: (entry: ToolEntry) => Promise<boolean>;
  rollbackDisabled?: boolean;
  onResolveApproval?: (entry: ToolEntry, decision: ToolApprovalDecision) => Promise<boolean>;
  approvalDisabled?: boolean;
}

export const ToolCard = memo(function ToolCard({
  entry,
  onRollback,
  rollbackDisabled = false,
  onResolveApproval,
  approvalDisabled = false,
}: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [rollingBack, setRollingBack] = useState(false);
  const [rollbackSucceeded, setRollbackSucceeded] = useState(false);
  const rollbackPending = useRef(false);
  const rolledBack = entry.status === 'rolled-back' || rollbackSucceeded;
  const approvalStatus = entry.approval?.status;
  const approvalNeedsDecision = approvalStatus === 'pending' || approvalStatus === 'failed';
  const isBusy = entry.status === 'running' || rollingBack || approvalStatus === 'submitting';
  const operationIndex = entry.backupInfo?.operation_index;
  const hasAtomicRollback = Boolean(entry.backupGroupId)
    && typeof operationIndex === 'number'
    && Number.isSafeInteger(operationIndex)
    && operationIndex >= 0;
  const status = rolledBack
    ? 'rolled-back'
    : approvalStatus ? `approval-${approvalStatus}` : entry.status;
  const statusLabel = rollingBack
    ? t('toolRunning')
    : rolledBack
      ? t('rolledBack')
      : approvalStatus === 'pending'
        ? t('toolApprovalNeeded')
        : approvalStatus === 'submitting'
          ? t('toolApprovalSubmitting')
          : approvalStatus === 'approved'
            ? t('toolApprovalApproved')
            : approvalStatus === 'denied'
              ? t('toolApprovalDenied')
              : approvalStatus === 'failed'
                ? t('toolApprovalFailed')
                : entry.status === 'running' ? t('toolRunning') : t('toolDone');

  const handleRollback = async () => {
    if (rollbackPending.current || rollbackDisabled || rolledBack) return;
    if (!window.confirm(`${t('toolRollback')}?\n\n${description(entry)}`)) return;
    rollbackPending.current = true;
    setRollingBack(true);
    try {
      setRollbackSucceeded(await onRollback(entry));
    } catch {
      setRollbackSucceeded(false);
    } finally {
      rollbackPending.current = false;
      setRollingBack(false);
    }
  };

  return (
    <div className={`tool-card status-${status}`}>
      <button
        type="button"
        className="tool-card-header"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <span className="tool-status" role="status" aria-label={statusLabel}>
          {isBusy
            ? <span className="spinner" aria-hidden="true" />
            : rolledBack
              ? <RotateCcw size={14} aria-hidden="true" />
              : approvalStatus === 'denied'
                ? <X size={14} aria-hidden="true" />
                : approvalNeedsDecision
                  ? <ShieldAlert size={14} aria-hidden="true" />
                  : <Check size={14} aria-hidden="true" />}
        </span>
        <Wrench size={14} aria-hidden="true" />
        <span>{description(entry)}</span>
        <ChevronDown className={expanded ? 'expanded' : ''} size={15} aria-hidden="true" />
      </button>

      {entry.approval && (
        <ToolApprovalPanel
          entry={entry}
          disabled={approvalDisabled}
          onResolve={onResolveApproval}
        />
      )}

      {expanded && (
        <div className="tool-card-body">
          <div className="tool-arguments">
            <strong>{t('toolArguments')}</strong>
            <pre>{JSON.stringify(entry.args, null, 2)}</pre>
          </div>
          {entry.result && (
            <div>
              <strong>{t('toolResult')}</strong>
              <pre>{entry.result}</pre>
            </div>
          )}
          {hasAtomicRollback && entry.status === 'done' && !rolledBack && (
            <button
              type="button"
              className="button button-small button-rollback"
              disabled={rollingBack || rollbackDisabled}
              aria-busy={rollingBack || rollbackDisabled || undefined}
              onClick={() => void handleRollback()}
            >
              {rollingBack
                ? <span className="spinner" aria-hidden="true" />
                : <RotateCcw size={13} aria-hidden="true" />}
              {t('toolRollback')}
            </button>
          )}
          {rolledBack && <span className="rolled-back-label">{t('rolledBack')}</span>}
        </div>
      )}
    </div>
  );
});
