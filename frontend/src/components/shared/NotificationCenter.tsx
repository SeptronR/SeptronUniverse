import { useEffect } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Bell } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { commsApi } from '@/features/communication/api';
import { useMyNotifications, useUnreadCount } from '@/features/communication/hooks';
import { wsClient } from '@/lib/ws';
import { useNotificationStore, type NotificationItem } from '@/store/notificationStore';
import { formatRelative } from '@/utils/formatters';

/**
 * Bell + recent notifications (Prompts/04 §04.9): the first page and the unread count come from `/notifications`
 * (polled every 60 s as the fallback), new items arrive live on `notifications:{user}`; clicking marks the item read
 * server-side and follows its deep link. Control frames on the channel (`{type: "approvals.changed"}`) are ignored here.
 */
export function NotificationCenter() {
  const { unread, items, push, markRead, setItems, setUnread } = useNotificationStore();
  const navigate = useNavigate();
  const recent = useMyNotifications({ page_size: 15 });
  const count = useUnreadCount();

  useEffect(() => {
    if (recent.data) {
      setItems(
        recent.data.data.map((n) => ({
          id: n.id,
          title: n.title,
          body: n.body,
          route: n.route,
          created_at: n.created_at,
          read_at: n.read_at,
          category: n.category ?? undefined,
        })),
      );
    }
  }, [recent.data, setItems]);
  useEffect(() => {
    if (count.data) setUnread(count.data.data.unread);
  }, [count.data, setUnread]);
  useEffect(
    () =>
      wsClient.subscribe('notifications', (data) => {
        const n = data as NotificationItem & { type?: string };
        if (n?.id && n.title && !n.type) push(n);
      }),
    [push],
  );

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`} className="relative">
          <Bell className="h-5 w-5" />
          {unread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground">
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-50 w-80 rounded-md border bg-popover p-3 text-sm shadow-md">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-medium">Notifications</p>
            {unread > 0 && (
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={async () => {
                  await commsApi.readAll();
                  setItems(items.map((i) => ({ ...i, read_at: i.read_at ?? new Date().toISOString() })));
                  setUnread(0);
                }}
              >
                Mark all read
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="text-muted-foreground">You are all caught up.</p>
          ) : (
            <ul className="max-h-80 space-y-1 overflow-y-auto">
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    className="w-full rounded-md p-2 text-left hover:bg-accent"
                    onClick={() => {
                      if (!n.read_at) void commsApi.markRead(n.id).catch(() => undefined);
                      markRead(n.id);
                      if (n.route) navigate(n.route);
                    }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className={n.read_at ? 'text-muted-foreground' : 'font-medium'}>{n.title}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{formatRelative(n.created_at)}</span>
                    </div>
                    {n.body && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{n.body}</p>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Link to="/notifications" className="mt-2 block text-center text-xs text-primary hover:underline">
            View all
          </Link>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
