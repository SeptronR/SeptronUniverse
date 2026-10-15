import { create } from 'zustand';

/** Unread count + recent items fed by the WebSocket channel `notifications:{user}` with polling fallback (Phase 04). */
export interface NotificationItem {
  id: string;
  title: string;
  body?: string | null;
  route?: string | null;
  created_at: string;
  read_at?: string | null;
  category?: string;
}

interface NotificationState {
  unread: number;
  items: NotificationItem[];
  connected: boolean;
  setUnread: (n: number) => void;
  setItems: (items: NotificationItem[]) => void;
  push: (item: NotificationItem) => void;
  markRead: (id: string) => void;
  setConnected: (v: boolean) => void;
  clear: () => void;
}

export const useNotificationStore = create<NotificationState>()((set) => ({
  unread: 0,
  items: [],
  connected: false,
  setUnread: (n) => set({ unread: n }),
  // the list is only the first page — the unread total comes from GET /notifications/unread-count (setUnread)
  setItems: (items) => set({ items }),
  push: (item) => set((s) => ({ items: [item, ...s.items].slice(0, 50), unread: s.unread + 1 })),
  markRead: (id) =>
    set((s) => ({
      items: s.items.map((i) => (i.id === id ? { ...i, read_at: new Date().toISOString() } : i)),
      unread: Math.max(0, s.unread - (s.items.find((i) => i.id === id && !i.read_at) ? 1 : 0)),
    })),
  setConnected: (v) => set({ connected: v }),
  clear: () => set({ unread: 0, items: [] }),
}));
