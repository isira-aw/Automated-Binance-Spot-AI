import { type AppEvent, type EventType } from '@/types/events';

export type ConnectionStatus = 'connecting' | 'open' | 'closed';

type EventHandler = (event: AppEvent) => void;
type StatusHandler = (status: ConnectionStatus) => void;

const INITIAL_RETRY_MS = 500;
const MAX_RETRY_MS = 15_000;

/**
 * WebSocket client with exponential-backoff reconnect (§13, §53, §91).
 *
 * The browser is a monitoring surface only: losing this connection never stops
 * the backend's trading engine, and reconnecting re-syncs from REST state.
 */
export class EventStream {
  private socket: WebSocket | null = null;
  private retryMs = INITIAL_RETRY_MS;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByCaller = false;
  private readonly eventHandlers = new Set<EventHandler>();
  private readonly statusHandlers = new Set<StatusHandler>();

  constructor(private readonly url: string = defaultUrl()) {}

  connect(): void {
    this.closedByCaller = false;
    this.emitStatus('connecting');

    const socket = new WebSocket(this.url);
    this.socket = socket;

    socket.onopen = () => {
      this.retryMs = INITIAL_RETRY_MS;
      this.emitStatus('open');
    };

    socket.onmessage = (message) => {
      let parsed: AppEvent;
      try {
        parsed = JSON.parse(message.data as string) as AppEvent;
      } catch {
        return;
      }
      // Answer heartbeats so the server does not classify us as stale.
      if (parsed.event === 'heartbeat') {
        this.send({ action: 'pong' });
      }
      this.eventHandlers.forEach((handler) => handler(parsed));
    };

    socket.onclose = () => {
      this.socket = null;
      this.emitStatus('closed');
      if (!this.closedByCaller) this.scheduleReconnect();
    };

    socket.onerror = () => socket.close();
  }

  disconnect(): void {
    this.closedByCaller = true;
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  subscribe(events: EventType[]): void {
    this.send({ action: 'subscribe', events });
  }

  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  private send(payload: unknown): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  }

  private scheduleReconnect(): void {
    const delay = this.retryMs;
    this.retryMs = Math.min(this.retryMs * 2, MAX_RETRY_MS);
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private emitStatus(status: ConnectionStatus): void {
    this.statusHandlers.forEach((handler) => handler(status));
  }
}

function defaultUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/api/v1/ws`;
}
