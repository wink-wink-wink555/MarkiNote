import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, KeyRound, Trash2, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { errorMessage } from '@/shared/api';
import { authApi } from '../api/authApi';

const fields = [
  { key: 'deepseekApiKey', label: 'DeepSeek API key' },
  { key: 'tushareToken', label: 'Tushare token' },
  { key: 'qverisApiKey', label: 'Qveris API key' },
] as const;

export function AccountCredentialsForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['account-credentials'], queryFn: authApi.credentialStatus });
  const [values, setValues] = useState<Record<string, string>>({});
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const update = useMutation({
    mutationFn: authApi.updateCredentials,
    onSuccess: async () => {
      setValues({}); setCleared(new Set());
      await queryClient.invalidateQueries({ queryKey: ['account-credentials'] });
    },
  });

  const save = () => {
    const payload: Record<string, string | null> = {};
    for (const { key } of fields) {
      if (cleared.has(key)) payload[key] = null;
      else if (values[key]?.trim()) payload[key] = values[key].trim();
    }
    if (Object.keys(payload).length) update.mutate(payload);
  };

  return <div className="credential-settings">
    {fields.map(({ key, label }) => {
      const configured = Boolean(status.data?.[key]) && !cleared.has(key);
      return <div className="credential-row" key={key}>
        <label htmlFor={`credential-${key}`}>{label}</label>
        <div className="credential-control">
          <div className="auth-input"><KeyRound size={16} aria-hidden="true" /><input id={`credential-${key}`} type="password" autoComplete="off" spellCheck={false} placeholder={configured ? t('credentialConfigured') : t('credentialNotConfigured')} value={values[key] ?? ''} onChange={(event) => { setValues((current) => ({ ...current, [key]: event.target.value })); setCleared((current) => { const next = new Set(current); next.delete(key); return next; }); }} /></div>
          <button type="button" className="icon-button" aria-label={`${t('clearCredential')}: ${label}`} title={t('clearCredential')} disabled={!configured} onClick={() => { setValues((current) => ({ ...current, [key]: '' })); setCleared((current) => new Set(current).add(key)); }}><Trash2 size={16} /></button>
        </div>
        <small>{configured ? <><CheckCircle2 size={13} aria-hidden="true" />{t('credentialEncrypted')}</> : cleared.has(key) ? t('credentialWillBeRemoved') : t('credentialOptional')}</small>
      </div>;
    })}
    {update.error && <div className="auth-error" role="alert"><TriangleAlert size={15} /><span>{errorMessage(update.error)}</span></div>}
    {update.isSuccess && <div className="auth-notice" role="status">{t('credentialsSaved')}</div>}
    <button type="button" className="button button-small" disabled={update.isPending || (!Object.values(values).some((value) => value.trim()) && !cleared.size)} onClick={save}>{update.isPending ? t('saving') : t('saveCredentials')}</button>
  </div>;
}
