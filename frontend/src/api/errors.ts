import { AxiosError } from 'axios';

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details: Record<string, unknown> = {},
    public requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface Envelope { error?: { code?: unknown; message?: unknown; details?: unknown; request_id?: unknown } }

/** Normalises anything thrown by axios/fetch into an ApiError using the contract error envelope. */
export function parseApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (err instanceof AxiosError) {
    const status = err.response?.status ?? 0;
    const env = (err.response?.data ?? {}) as Envelope;
    if (env && typeof env === 'object' && env.error && typeof env.error === 'object') {
      return new ApiError(
        String(env.error.code ?? 'INTERNAL_ERROR'),
        String(env.error.message ?? err.message),
        status,
        (env.error.details as Record<string, unknown>) ?? {},
        env.error.request_id ? String(env.error.request_id) : undefined,
      );
    }
    if (!err.response) return new ApiError('NETWORK_ERROR', 'Network error — is the API reachable?', 0);
    return new ApiError(status >= 500 ? 'INTERNAL_ERROR' : 'HTTP_ERROR', err.message, status);
  }
  if (err instanceof Error) return new ApiError('CLIENT_ERROR', err.message, 0);
  return new ApiError('CLIENT_ERROR', String(err), 0);
}

export function errorMessage(err: unknown): string {
  const e = parseApiError(err);
  return e.requestId ? `${e.message} (${e.code}, request ${e.requestId})` : `${e.message} (${e.code})`;
}
