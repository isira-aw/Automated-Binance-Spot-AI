import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { EventStream, type ConnectionStatus } from '@/lib/websocket';
import type { AppEvent } from '@/types/events';

const MAX_BUFFERED_EVENTS = 300;

interface EventStreamValue {
  status: ConnectionStatus;
  events: AppEvent[];
  lastHeartbeat: string | null;
}

const EventStreamContext = createContext<EventStreamValue>({
  status: 'connecting',
  events: [],
  lastHeartbeat: null,
});

/**
 * Holds a single WebSocket for the whole app and buffers a bounded window of
 * recent events for the log viewer (§48) — never an unbounded array.
 */
export function EventStreamProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [lastHeartbeat, setLastHeartbeat] = useState<string | null>(null);
  const streamRef = useRef<EventStream | null>(null);

  useEffect(() => {
    const stream = new EventStream();
    streamRef.current = stream;

    const offStatus = stream.onStatus(setStatus);
    const offEvent = stream.onEvent((event) => {
      if (event.event === 'heartbeat') {
        setLastHeartbeat(event.timestamp);
        return;
      }
      setEvents((current) => [event, ...current].slice(0, MAX_BUFFERED_EVENTS));
    });

    stream.connect();
    return () => {
      offStatus();
      offEvent();
      stream.disconnect();
      streamRef.current = null;
    };
  }, []);

  const value = useMemo(
    () => ({ status, events, lastHeartbeat }),
    [status, events, lastHeartbeat],
  );

  return <EventStreamContext.Provider value={value}>{children}</EventStreamContext.Provider>;
}

export function useEventStream(): EventStreamValue {
  return useContext(EventStreamContext);
}
