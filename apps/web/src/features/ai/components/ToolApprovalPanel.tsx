import { CheckCircle2, ShieldAlert, XCircle } from 'lucide-react';
import { memo, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolEntry } from '../model/types';

export type ToolApprovalDecision = 'approve' | 'deny';

type ApprovalStatus = NonNullable<ToolEntry['approval']>['status'];

interface Props {
  entry: ToolEntry;
  disabled: boolean;
  onResolve?: (entry: ToolEntry, decision: ToolApprovalDecision) => Promise<boolean>;
}

interface LocalStatus {
  approvalId: string;
  baseStatus: ApprovalStatus;
  status: ApprovalStatus;
}

export const ToolApprovalPanel = memo(function ToolApprovalPanel({
  entry,
  disabled,
  onResolve,
}: Props) {
  const { t } = useTranslation();
  const headingId = useId();
  const submitting = useRef(false);
  const [localStatus, setLocalStatus] = useState<LocalStatus | null>(null);
  const approval = entry.approval;

  if (!approval) return null;

  const localStatusApplies = localStatus?.approvalId === approval.id
    && localStatus.baseStatus === approval.status;
  const status = localStatusApplies ? localStatus.status : approval.status;
  const awaitingDecision = status === 'pending' || status === 'failed';
  const isSubmitting = status === 'submitting';
  const controlsDisabled = disabled || !onResolve || isSubmitting;
  const reason = approval.reason === 'external_content'
    ? t('toolApprovalExternalContentReason')
    : t('toolApprovalUnselectedReason');

  const resolve = async (decision: ToolApprovalDecision) => {
    if (submitting.current || controlsDisabled || !onResolve) return;
    submitting.current = true;
    setLocalStatus({
      approvalId: approval.id,
      baseStatus: approval.status,
      status: 'submitting',
    });
    try {
      const succeeded = await onResolve(entry, decision);
      setLocalStatus({
        approvalId: approval.id,
        baseStatus: approval.status,
        status: succeeded ? (decision === 'approve' ? 'approved' : 'denied') : 'failed',
      });
    } catch {
      setLocalStatus({
        approvalId: approval.id,
        baseStatus: approval.status,
        status: 'failed',
      });
    } finally {
      submitting.current = false;
    }
  };

  return (
    <section
      className={`tool-approval-panel approval-${status}`}
      aria-labelledby={headingId}
      aria-busy={isSubmitting || undefined}
    >
      <div className="tool-approval-heading">
        <span className="tool-approval-heading-icon" aria-hidden="true">
          <ShieldAlert size={17} />
        </span>
        <div>
          <strong id={headingId}>{t('toolApprovalNeeded')}</strong>
          {awaitingDecision && <p>{reason}</p>}
        </div>
      </div>

      <div className="tool-approval-target">
        <span>{t('toolApprovalTarget')}</span>
        <code dir="auto" title={approval.target}>{approval.target}</code>
      </div>

      {status === 'failed' && (
        <p className="tool-approval-feedback is-error" role="alert">
          {t('toolApprovalFailed')}
        </p>
      )}

      {(awaitingDecision || isSubmitting) && (
        <div className="tool-approval-actions">
          <button
            type="button"
            className="button tool-approval-deny"
            disabled={controlsDisabled}
            onClick={() => void resolve('deny')}
          >
            {t('toolApprovalDeny')}
          </button>
          <button
            type="button"
            className="button button-primary tool-approval-approve"
            disabled={controlsDisabled}
            onClick={() => void resolve('approve')}
          >
            {t('toolApprovalApprove')}
          </button>
        </div>
      )}

      {isSubmitting && (
        <div className="tool-approval-feedback" role="status">
          <span className="spinner" aria-hidden="true" />
          {t('toolApprovalSubmitting')}
        </div>
      )}

      {status === 'approved' && (
        <div className="tool-approval-feedback is-approved" role="status">
          <CheckCircle2 size={16} aria-hidden="true" />
          {t('toolApprovalApproved')}
        </div>
      )}

      {status === 'denied' && (
        <div className="tool-approval-feedback is-denied" role="status">
          <XCircle size={16} aria-hidden="true" />
          {t('toolApprovalDenied')}
        </div>
      )}
    </section>
  );
});
