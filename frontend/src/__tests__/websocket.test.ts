import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EventStream } from '@/lib/websocket';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly OPEN = 1;

  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  receive(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('EventStream', () => {
  it('reports connection status transitions', () => {
    const stream = new EventStream('ws://test/api/v1/ws');
    const statuses: string[] = [];
    stream.onStatus((status) => statuses.push(status));

    stream.connect();
    expect(statuses).toEqual(['connecting']);

    FakeWebSocket.instances[0]!.open();
    expect(statuses).toEqual(['connecting', 'open']);
  });

  it('answers heartbeats so the server does not mark it stale', () => {
    const stream = new EventStream('ws://test/api/v1/ws');
    stream.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.open();

    socket.receive({ event: 'heartbeat', timestamp: '2026-01-01T00:00:00+00:00', data: {} });
    expect(JSON.parse(socket.sent[0]!)).toEqual({ action: 'pong' });
  });

  it('forwards business events to handlers', () => {
    const stream = new EventStream('ws://test/api/v1/ws');
    const received: string[] = [];
    stream.onEvent((event) => received.push(event.event));
    stream.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.open();

    socket.receive({ event: 'risk_event', timestamp: 't', data: { rule: 'max_daily_loss' } });
    expect(received).toEqual(['risk_event']);
  });

  it('ignores malformed frames instead of throwing', () => {
    const stream = new EventStream('ws://test/api/v1/ws');
    const received: string[] = [];
    stream.onEvent((event) => received.push(event.event));
    stream.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.open();

    expect(() => socket.onmessage?.({ data: '{not json' })).not.toThrow();
    expect(received).toEqual([]);
  });

  it('reconnects with exponential backoff after an unexpected close', () => {
    const stream = new EventStream('ws://test/api/v1/ws');
    stream.connect();
    FakeWebSocket.instances[0]!.open();

    FakeWebSocket.instances[0]!.close();
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(2);

    FakeWebSocket.instances[1]!.close();
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(2); // not yet — backoff doubled
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it('does not reconnect after an explicit disconnect', () => {
    const stream = new EventStream('ws://test/api/v1/ws');
    stream.connect();
    FakeWebSocket.instances[0]!.open();

    stream.disconnect();
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
