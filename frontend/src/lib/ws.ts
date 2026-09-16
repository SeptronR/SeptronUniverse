import { useAuthStore } from '@/store/authStore';
import { useNotificationStore } from '@/store/notificationStore';

/**
 * Single WebSocket client for /ws?token= (docs/Technical_Architecture.md §9). Reconnects with backoff 2 s → 30 s,
 * dispatches channel messages to subscribers and the notification store. Phase 01 wires the jobs tray on top.
 */
type Handler = (data: unknown) => void;

class WsClient {
  private socket: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private backoff = 2000;
  private timer: number | null = null;
  private stopped = false;

  connect() {
    this.stopped = false;
    const token = useAuthStore.getState().accessToken;
    if (!token || this.socket) return;
    const base = import.meta.env.VITE_WS_URL || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
    const ws = new WebSocket(`${base}?token=${encodeURIComponent(token)}`);
    this.socket = ws;
    ws.onopen = () => {
      this.backoff = 2000;
      useNotificationStore.getState().setConnected(true);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as { channel: string; data: unknown };
        if (msg.channel === 'system') return;
        const prefix = msg.channel.split(':')[0];
        this.handlers.get(prefix)?.forEach((h) => h(msg.data));
        this.handlers.get(msg.channel)?.forEach((h) => h(msg.data));
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      this.socket = null;
      useNotificationStore.getState().setConnected(false);
      if (!this.stopped) this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleReconnect() {
    if (this.timer) return;
    this.timer = window.setTimeout(() => {
      this.timer = null;
      this.backoff = Math.min(this.backoff * 2, 30000);
      this.connect();
    }, this.backoff);
  }

  subscribe(channel: string, handler: Handler): () => void {
    if (!this.handlers.has(channel)) this.handlers.set(channel, new Set());
    this.handlers.get(channel)!.add(handler);
    return () => {
      this.handlers.get(channel)?.delete(handler);
    };
  }

  disconnect() {
    this.stopped = true;
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = null;
    this.socket?.close();
    this.socket = null;
  }
}

export const wsClient = new WsClient();
