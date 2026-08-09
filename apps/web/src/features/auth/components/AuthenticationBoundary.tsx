import { useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, NotebookPen, RefreshCw, ShieldCheck, TriangleAlert } from 'lucide-react';
import { type FormEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError, errorMessage } from '@/shared/api';
import { onAuthenticationRequired } from '@/shared/auth/authEvents';
import { authApi } from '../api/authApi';

interface Props { children: ReactNode }

function AccessTokenGate({ onAuthenticated }: { onAuthenticated: () => Promise<void> }) {
  const { t } = useTranslation();
  const [accessToken, setAccessToken] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const helpId = useId();
  const errorId = useId();
  const shouldAutoFocus = typeof window !== 'undefined'
    && window.matchMedia('(pointer: fine) and (min-width: 761px)').matches;
  useEffect(() => {
    if (error) inputRef.current?.focus();
  }, [error]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const submittedToken = accessToken;
    if (!submittedToken || submitting) return;
    setAccessToken('');
    setError('');
    setSubmitting(true);
    try {
      await authApi.exchange(submittedToken);
      await onAuthenticated();
    } catch (caught) {
      setError(caught instanceof ApiError && caught.code === 'authentication_rate_limited' ? t('authRateLimited') : errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="auth-shell">
    <section className="auth-card" aria-labelledby="auth-title">
      <header className="auth-heading">
        <div className="auth-mark" aria-hidden="true"><NotebookPen size={24} strokeWidth={1.8} /></div>
        <div className="auth-brand"><strong translate="no">{t('appName')}</strong><span><ShieldCheck size={13} aria-hidden="true" />{t('secureSession')}</span></div>
      </header>
      <div className="auth-copy">
        <h1 id="auth-title">{t('authTitle')}</h1>
        <p>{t('authBody')}</p>
      </div>
      <form onSubmit={(event) => void submit(event)} aria-busy={submitting}>
        <label htmlFor={inputId}>{t('accessToken')}</label>
        <div className="auth-input"><KeyRound size={17} aria-hidden="true" /><input ref={inputRef} id={inputId} name="markinote-session-access-token" type="password" autoComplete="off" autoCapitalize="none" spellCheck={false} autoFocus={shouldAutoFocus} required value={accessToken} onChange={(event) => { setAccessToken(event.target.value); setError(''); }} aria-invalid={Boolean(error)} aria-describedby={error ? `${helpId} ${errorId}` : helpId} aria-errormessage={error ? errorId : undefined} /></div>
        <small id={helpId}>{t('accessTokenMemory')}</small>
        {error && <div id={errorId} className="auth-error" role="alert"><TriangleAlert size={15} aria-hidden="true" /><span>{error}</span></div>}
        <button className="button button-primary auth-submit" type="submit" disabled={submitting}>{submitting ? t('authSigningIn') : t('authSignIn')}</button>
      </form>
    </section>
  </main>;
}

export function AuthenticationBoundary({ children }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [authenticationRequired, setAuthenticationRequired] = useState(false);
  const session = useQuery({ queryKey: ['auth-session'], queryFn: authApi.probe, retry: false, staleTime: Number.POSITIVE_INFINITY });

  useEffect(() => onAuthenticationRequired(() => setAuthenticationRequired(true)), []);

  const sessionRequiresAuthentication = session.error instanceof ApiError && session.error.code === 'authentication_required';
  const authenticated = async () => {
    const checked = await session.refetch();
    if (checked.error) throw checked.error;
    setAuthenticationRequired(false);
    await queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'auth-session' });
  };

  if (authenticationRequired || sessionRequiresAuthentication) return <AccessTokenGate onAuthenticated={authenticated} />;
  if (session.isPending) return <main className="auth-shell"><section className="auth-card auth-loading" role="status"><div className="auth-mark" aria-hidden="true"><NotebookPen size={24} /></div><div className="skeleton auth-loading-title" /><div className="skeleton auth-loading-line" /><span>{t('authChecking')}</span></section></main>;
  if (session.isError) return <main className="auth-shell"><section className="auth-card auth-startup-error" aria-labelledby="startup-error"><div className="auth-mark danger" aria-hidden="true"><TriangleAlert size={23} /></div><h1 id="startup-error">{t('errorTitle')}</h1><p role="alert">{errorMessage(session.error)}</p><button className="button button-primary" onClick={() => void session.refetch()}><RefreshCw size={15} />{t('retry')}</button></section></main>;
  return children;
}
