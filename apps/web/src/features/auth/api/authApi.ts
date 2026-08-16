import { ApiError, apiClient, apiErrorFromProblem, unwrap, type ApiComponents } from '@/shared/api';

type ApiRootResponse = ApiComponents['schemas']['ApiRootResponse'];
export interface AuthConfig { mode: 'access_token' | 'accounts'; registrationEnabled: boolean }
export interface AccountSession { authenticated: boolean; email: string | null; username: string | null }
export interface CredentialStatus { deepseekApiKey: boolean; tushareToken: boolean; qverisApiKey: boolean }
interface AccessTokenResponse { authenticated: true }

async function responseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try { return JSON.parse(text) as unknown; } catch { return text; }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(new URL(path, window.location.origin), {
      credentials: 'same-origin',
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError('Unable to reach the server', 0, 'network_error');
  }
  const body = await responseBody(response);
  if (!response.ok) throw apiErrorFromProblem(body, response.status, response.statusText);
  return body as T;
}

export const authApi = {
  config: () => request<AuthConfig>('/auth/config'),
  session: () => request<AccountSession>('/auth/session'),
  probe: async () => unwrap<ApiRootResponse>(await apiClient.GET('/api/v1')),
  exchange: (accessToken: string) => request<AccessTokenResponse>('/auth/access-token', {
    method: 'POST', body: JSON.stringify({ accessToken }),
  }),
  register: (email: string, username: string, password: string) => request<AccountSession>('/auth/register', {
    method: 'POST', body: JSON.stringify({ email, username, password }),
  }),
  login: (identity: string, password: string) => request<AccountSession>('/auth/login', {
    method: 'POST', body: JSON.stringify({ identity, password }),
  }),
  verifyEmail: (token: string) => request<AccountSession>('/auth/verify-email', {
    method: 'POST', body: JSON.stringify({ token }),
  }),
  resendVerification: (email: string) => request<{ accepted: true }>('/auth/resend-verification', {
    method: 'POST', body: JSON.stringify({ email }),
  }),
  logout: () => request<AccountSession>('/auth/logout', { method: 'POST' }),
  credentialStatus: () => request<CredentialStatus>('/api/v1/account/credentials'),
  updateCredentials: (values: Record<string, string | null>) => request<CredentialStatus>('/api/v1/account/credentials', {
    method: 'PUT', body: JSON.stringify(values),
  }),
};
