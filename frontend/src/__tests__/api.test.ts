import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiGet, apiPost } from '@/lib/api';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'error',
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe('apiGet', () => {
  it('returns the parsed body on success', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(200, { overall: 'ONLINE' })));
    await expect(apiGet<{ overall: string }>('/system/health')).resolves.toEqual({
      overall: 'ONLINE',
    });
  });

  it('surfaces the documented error code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(501, {
          error: { code: 'NOT_IMPLEMENTED', message: 'The signals API is not implemented yet.' },
        }),
      ),
    );

    await expect(apiGet('/signals')).rejects.toMatchObject({
      code: 'NOT_IMPLEMENTED',
      status: 501,
    });
  });

  it('treats an unhealthy /system/health 503 as a valid payload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(503, { overall: 'DEGRADED', components: {} })),
    );
    await expect(apiGet<{ overall: string }>('/system/health')).resolves.toMatchObject({
      overall: 'DEGRADED',
    });
  });

  it('falls back to a network error when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          ({
            ok: false,
            status: 502,
            statusText: 'Bad Gateway',
            json: async () => {
              throw new Error('not json');
            },
          }) as unknown as Response,
      ),
    );

    await expect(apiGet('/settings')).rejects.toBeInstanceOf(ApiError);
  });
});

describe('apiPost', () => {
  it('sends a POST request and returns the parsed body', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(202, { running: true }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiPost<{ running: boolean }>('/market/backfill')).resolves.toEqual({
      running: true,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/market/backfill',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('surfaces the documented error code on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(422, {
          error: { code: 'VALIDATION_ERROR', message: 'A backfill is already running.' },
        }),
      ),
    );

    await expect(apiPost('/market/backfill')).rejects.toMatchObject({
      code: 'VALIDATION_ERROR',
      status: 422,
    });
  });
});
