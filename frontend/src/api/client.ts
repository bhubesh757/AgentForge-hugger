import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';
import { API_BASE_URL, DEMO_MODE } from '@/config';
import { uuid } from '@/lib/format';
import { session } from './session';
import { parseApiError } from './errors';
import type { TokenPair } from '@/types/api';
import { mockAdapter } from './mock/adapter';

type RetryConfig = InternalAxiosRequestConfig & { _retried?: boolean };

export function authHeaders(includeOrg = true): Record<string, string> {
  const h: Record<string, string> = { 'X-Request-ID': uuid() };
  const t = session.getAccess();
  if (t) h.Authorization = `Bearer ${t}`;
  const org = session.getOrg();
  if (includeOrg && org) h['X-Organization-ID'] = org;
  return h;
}

export function createClient(opts: { baseURL?: string; demo?: boolean } = {}): AxiosInstance {
  const instance = axios.create({
    baseURL: opts.baseURL ?? API_BASE_URL,
    headers: { 'Content-Type': 'application/json' },
    timeout: 60_000,
    ...(opts.demo ?? DEMO_MODE ? { adapter: mockAdapter } : {}),
  });

  instance.interceptors.request.use((config) => {
    const url = config.url ?? '';
    const isOrgFree = url.startsWith('/auth/') || /^\/organizations\/?(\?|$)/.test(url) || url === '/health';
    for (const [k, v] of Object.entries(authHeaders(!isOrgFree))) {
      if (!config.headers.has(k)) config.headers.set(k, v);
    }
    return config;
  });

  let refreshing: Promise<string> | null = null;
  const refresh = (): Promise<string> => {
    if (!refreshing) {
      const rt = session.getRefresh();
      refreshing = (rt ? Promise.resolve(rt) : Promise.reject(new Error('No refresh token')))
        .then((refresh_token) => instance.post<TokenPair>('/auth/refresh', { refresh_token }, { headers: { Authorization: '' } }))
        .then((r) => {
          session.setTokens(r.data.access_token, r.data.refresh_token);
          return r.data.access_token;
        })
        .finally(() => {
          refreshing = null;
        });
    }
    return refreshing;
  };

  instance.interceptors.response.use(undefined, async (error: AxiosError) => {
    const cfg = error.config as RetryConfig | undefined;
    const apiErr = parseApiError(error);
    const isAuthCall = (cfg?.url ?? '').startsWith('/auth/refresh') || (cfg?.url ?? '').startsWith('/auth/login');
    if (cfg && !cfg._retried && !isAuthCall && apiErr.status === 401 && apiErr.code === 'TOKEN_EXPIRED') {
      cfg._retried = true;
      try {
        const token = await refresh();
        cfg.headers.set('Authorization', `Bearer ${token}`);
        return instance.request(cfg);
      } catch {
        session.clear();
        session.emitLogout();
        return Promise.reject(apiErr);
      }
    }
    if (apiErr.status === 401 && !isAuthCall) {
      session.clear();
      session.emitLogout();
    }
    return Promise.reject(apiErr);
  });
  return instance;
}

export const api = createClient();

/** Ensures an access token exists (used at boot when only a refresh token survived reload). */
export async function bootstrapSession(force = false): Promise<boolean> {
  if (!force && session.getAccess()) return true;
  const rt = session.getRefresh();
  if (!rt) return false;
  try {
    const r = await api.post<TokenPair>('/auth/refresh', { refresh_token: rt });
    session.setTokens(r.data.access_token, r.data.refresh_token);
    return true;
  } catch {
    session.clear();
    return false;
  }
}
