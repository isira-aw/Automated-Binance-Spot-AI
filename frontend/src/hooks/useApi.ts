import { useCallback, useEffect, useState } from 'react';

import { ApiError, apiGet } from '@/lib/api';

interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/** Fetch a REST resource, optionally re-polling on an interval. */
export function useApi<T>(path: string, pollMs?: number): ApiState<T> & { refresh: () => void } {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: true });
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      try {
        const data = await apiGet<T>(path, controller.signal);
        if (!cancelled) setState({ data, error: null, loading: false });
      } catch (error) {
        if (cancelled || controller.signal.aborted) return;
        setState({
          data: null,
          error:
            error instanceof ApiError
              ? error
              : new ApiError(0, {
                  error: { code: 'NETWORK_ERROR', message: 'Backend unreachable.' },
                }),
          loading: false,
        });
      }
    };

    void load();
    const timer = pollMs ? setInterval(() => void load(), pollMs) : undefined;

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [path, pollMs, nonce]);

  return { ...state, refresh };
}
