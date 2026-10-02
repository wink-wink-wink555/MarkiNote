import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  KeyRound,
  LockKeyhole,
  Mail,
  NotebookPen,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  UserRound,
} from 'lucide-react';
import { type FormEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError, errorMessage } from '@/shared/api';
import { onAuthenticationRequired } from '@/shared/auth/authEvents';
import { authApi, type AccountSession, type AuthConfig } from '../api/authApi';
import { AuthProvider } from '../model/AuthProvider';

interface Props { children: ReactNode }
interface ResolvedAuth { config: AuthConfig; session: AccountSession }

function consumeVerificationToken(): string {
  if (typeof window === 'undefined' || !window.location.hash.startsWith('#verify=')) return '';
  const token = window.location.hash.slice('#verify='.length);
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  return token;
}

function BrandHeader() {
  const { t } = useTranslation();
  return <header className="auth-heading">
    <div className="auth-mark" aria-hidden="true"><NotebookPen size={24} strokeWidth={1.8} /></div>
    <div className="auth-brand"><strong translate="no">{t('appName')}</strong><span><ShieldCheck size={13} aria-hidden="true" />{t('secureSession')}</span></div>
  </header>;
}

function AccessTokenGate({ onAuthenticated }: { onAuthenticated: () => Promise<void> }) {
  const { t } = useTranslation();
  const [accessToken, setAccessToken] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const helpId = useId();
  const errorId = useId();
  useEffect(() => { if (error) inputRef.current?.focus(); }, [error]);

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
    } finally { setSubmitting(false); }
  };

  return <main className="auth-shell"><section className="auth-card" aria-labelledby="auth-title">
    <BrandHeader />
    <div className="auth-copy"><h1 id="auth-title">{t('authTitle')}</h1><p>{t('authBody')}</p></div>
    <form onSubmit={(event) => void submit(event)} aria-busy={submitting}>
      <label htmlFor={inputId}>{t('accessToken')}</label>
      <div className="auth-input"><KeyRound size={17} aria-hidden="true" /><input ref={inputRef} id={inputId} name="markinote-session-access-token" type="password" autoComplete="off" autoCapitalize="none" spellCheck={false} required value={accessToken} onChange={(event) => { setAccessToken(event.target.value); setError(''); }} aria-invalid={Boolean(error)} aria-describedby={error ? `${helpId} ${errorId}` : helpId} aria-errormessage={error ? errorId : undefined} /></div>
      <small id={helpId}>{t('accessTokenMemory')}</small>
      {error && <div id={errorId} className="auth-error" role="alert"><TriangleAlert size={15} aria-hidden="true" /><span>{error}</span></div>}
      <button className="button button-primary auth-submit" type="submit" disabled={submitting}>{submitting ? t('authSigningIn') : t('authSignIn')}</button>
    </form>
  </section></main>;
}

function AccountGate({ registrationEnabled, onAuthenticated }: { registrationEnabled: boolean; onAuthenticated: () => Promise<void> }) {
  const { t } = useTranslation();
  const [view, setView] = useState<'login' | 'register'>('login');
  const [identity, setIdentity] = useState('');
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setError(''); setNotice(''); setSubmitting(true);
    try {
      if (view === 'register') {
        await authApi.register(email, username, password);
        setNotice(t('verificationSent'));
        setIdentity(username || email);
        setPassword('');
        setView('login');
      } else {
        await authApi.login(identity, password);
        setPassword('');
        await onAuthenticated();
      }
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setSubmitting(false); }
  };

  return <main className="auth-shell"><section className="auth-card" aria-labelledby="account-auth-title">
    <BrandHeader />
    <div className="auth-copy"><h1 id="account-auth-title">{view === 'login' ? t('accountSignIn') : t('createAccount')}</h1><p>{t('accountAuthBody')}</p></div>
    {registrationEnabled && <div className="auth-tabs" role="tablist" aria-label={t('accountAccess')}>
      <button type="button" role="tab" aria-selected={view === 'login'} className={view === 'login' ? 'active' : ''} onClick={() => { setView('login'); setError(''); }}>{t('authSignIn')}</button>
      <button type="button" role="tab" aria-selected={view === 'register'} className={view === 'register' ? 'active' : ''} onClick={() => { setView('register'); setError(''); }}>{t('register')}</button>
    </div>}
    <form onSubmit={(event) => void submit(event)} aria-busy={submitting}>
      {view === 'register' ? <>
        <label htmlFor="register-email">{t('email')}</label>
        <div className="auth-input"><Mail size={17} aria-hidden="true" /><input id="register-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></div>
        <label htmlFor="register-username">{t('username')}</label>
        <div className="auth-input"><UserRound size={17} aria-hidden="true" /><input id="register-username" autoComplete="username" pattern="[A-Za-z][A-Za-z0-9_-]{2,31}" required value={username} onChange={(event) => setUsername(event.target.value)} /></div>
      </> : <>
        <label htmlFor="login-identity">{t('emailOrUsername')}</label>
        <div className="auth-input"><UserRound size={17} aria-hidden="true" /><input id="login-identity" autoComplete="username" required value={identity} onChange={(event) => setIdentity(event.target.value)} /></div>
      </>}
      <label htmlFor="account-password">{t('password')}</label>
      <div className="auth-input"><LockKeyhole size={17} aria-hidden="true" /><input id="account-password" type="password" minLength={10} maxLength={128} autoComplete={view === 'login' ? 'current-password' : 'new-password'} required value={password} onChange={(event) => setPassword(event.target.value)} /></div>
      <small>{t('workspaceQuotaNotice')}</small>
      {notice && <div className="auth-notice" role="status">{notice}</div>}
      {error && <div className="auth-error" role="alert"><TriangleAlert size={15} aria-hidden="true" /><span>{error}</span></div>}
      <button className="button button-primary auth-submit" type="submit" disabled={submitting}>{submitting ? t('authSigningIn') : view === 'login' ? t('authSignIn') : t('createAccount')}</button>
    </form>
  </section></main>;
}

export function AuthenticationBoundary({ children }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [authenticationRequired, setAuthenticationRequired] = useState(false);
  const auth = useQuery<ResolvedAuth>({
    queryKey: ['auth-session'],
    queryFn: async () => {
      const config = await authApi.config();
      if (config.mode === 'accounts') {
        const token = consumeVerificationToken();
        const session = token ? await authApi.verifyEmail(token) : await authApi.session();
        return { config, session };
      }
      await authApi.probe();
      return { config, session: { authenticated: true, email: null, username: null } };
    },
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });

  useEffect(() => onAuthenticationRequired(() => setAuthenticationRequired(true)), []);

  const sessionRequiresAuthentication = auth.error instanceof ApiError && auth.error.code === 'authentication_required';
  const authenticated = async () => {
    const checked = await auth.refetch();
    if (checked.error) throw checked.error;
    setAuthenticationRequired(false);
    await queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'auth-session' });
  };

  if (auth.isPending) return <main className="auth-shell"><section className="auth-card auth-loading" role="status"><div className="auth-mark" aria-hidden="true"><NotebookPen size={24} /></div><div className="skeleton auth-loading-title" /><div className="skeleton auth-loading-line" /><span>{t('authChecking')}</span></section></main>;
  if (auth.isError && !sessionRequiresAuthentication) return <main className="auth-shell"><section className="auth-card auth-startup-error" aria-labelledby="startup-error"><div className="auth-mark danger" aria-hidden="true"><TriangleAlert size={23} /></div><h1 id="startup-error">{t('errorTitle')}</h1><p role="alert">{errorMessage(auth.error)}</p><button className="button button-primary" onClick={() => void auth.refetch()}><RefreshCw size={15} />{t('retry')}</button></section></main>;
  if (sessionRequiresAuthentication) return <AccessTokenGate onAuthenticated={authenticated} />;

  const resolved = auth.data;
  if (!resolved) return null;
  if (resolved.config.mode === 'accounts' && (authenticationRequired || !resolved.session.authenticated)) {
    return <AccountGate registrationEnabled={resolved.config.registrationEnabled} onAuthenticated={authenticated} />;
  }
  if (resolved.config.mode === 'access_token' && (authenticationRequired || sessionRequiresAuthentication)) {
    return <AccessTokenGate onAuthenticated={authenticated} />;
  }

  const logout = async () => {
    if (resolved.config.mode === 'accounts') await authApi.logout();
    setAuthenticationRequired(true);
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'auth-session' });
    await auth.refetch();
  };
  return <AuthProvider value={{ mode: resolved.config.mode, email: resolved.session.email, username: resolved.session.username, logout }}>{children}</AuthProvider>;
}
