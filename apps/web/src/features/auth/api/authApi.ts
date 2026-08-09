import { ApiError, apiClient, apiErrorFromProblem, unwrap, type ApiComponents } from '@/shared/api';

type ApiRootResponse = ApiComponents['schemas']['ApiRootResponse'];
interface AccessTokenResponse { authenticated: true }

async function responseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try { return JSON.parse(text) as unknown; } catch { return text; }
}

export const authApi = {
  probe: async () => unwrap<ApiRootResponse>(await apiClient.GET('/api/v1')),
  exchange: async (accessToken: string): Promise<AccessTokenResponse> => {
    let response: Response;
    try {
      const endpoint = new URL('/auth/access-token', window.location.origin);
      response = await fetch(endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ accessToken }),
      });
    } catch {
      throw new ApiError('Unable to reach the server', 0, 'network_error');
    }
    const body = await responseBody(response);
    if (!response.ok) throw apiErrorFromProblem(body, response.status, response.statusText);
    return body as AccessTokenResponse;
  },
};
