import { useEffect } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Bell } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { wsClient } from '@/lib/ws';
import { useNotificationStore, type NotificationItem } from '@/store/notificationStore';
import { formatRelative } from '@/utils/formatters';

/** Bell + recent notifications fed by `notifications:{user}` (Phase 04 adds the inbox page, read/unread API and polling). */
export function NotificationCenter() {
  const { unread, items, push, markRead } = useNotificationStore();
  const navigate = useNavigate();

  useEffect(
    () =>
      wsClient.subscribe('notifications', (data) => {
        const n = data as NotificationItem;
        if (n?.id) push(n);
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
          <p className="mb-2 font-medium">Notifications</p>
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
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
