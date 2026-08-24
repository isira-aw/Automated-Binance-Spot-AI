import type { ApiErrorBody } from '@/types/api';

const BASE = '/api/v1';

/** A backend error carrying the documented `code` so the UI can explain it (§101). */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly metadata?: Record<string, unknown> | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.error.code;
    this.metadata = body.error.metadata;
  }
}

async function parseOrThrow<T>(response: Response, path: string): Promise<T> {
  // /system/health answers 503 with a full body when a component is unhealthy;
  // that is a valid payload, not a transport failure.
  if (!response.ok && !(response.status === 503 && path.startsWith('/system/health'))) {
    let body: ApiErrorBody;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = { error: { code: 'NETWORK_ERROR', message: response.statusText } };
    }
    throw new ApiError(response.status, body);
  }

  return (await response.json()) as T;
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    signal,
    headers: { Accept: 'application/json' },
  });
  return parseOrThrow<T>(response, path);
}

export async function apiPost<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    signal,
    headers: { Accept: 'application/json' },
  });
  return parseOrThrow<T>(response, path);
}
