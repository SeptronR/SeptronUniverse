import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCheck } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/Button';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Switch } from '@/components/ui/Switch';
import { useNotificationStore } from '@/store/notificationStore';
import { cn } from '@/utils/cn';
import { formatRelative } from '@/utils/formatters';
import { commsApi } from '../api';
import { useCommsMutation, useMyNotifications } from '../hooks';

/** /notifications — full inbox with unread filter, mark read / read all and deep links. */
export default function NotificationsPage() {
  const [unread, setUnread] = useState(false);
  const [page, setPage] = useState(1);
  const list = useMyNotifications({ unread, page, page_size: 25 });
  const readAll = useCommsMutation(() => commsApi.readAll(), ['notifications']);
  const markRead = useCommsMutation((id: string) => commsApi.markRead(id), ['notifications']);
  const store = useNotificationStore();
  if (list.isLoading) return <PageSkeleton />;
  const rows = list.data?.data ?? [];
  const pagination = list.data?.meta.pagination;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Notifications"
        actions={
          <Button variant="outline" onClick={() => readAll.mutate(undefined, { onSuccess: () => store.setUnread(0) })}>
            <CheckCheck className="h-4 w-4" /> Mark all read
          </Button>
        }
      />
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={unread} onCheckedChange={(v) => { setUnread(v); setPage(1); }} /> Unread only
      </label>
      <ul className="divide-y rounded-md border">
        {rows.map((n) => (
          <li key={n.id} className={cn('p-3 text-sm', !n.is_read && 'bg-accent/40')}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                {n.route ? (
                  <Link to={n.route} className="font-medium hover:underline" onClick={() => !n.is_read && markRead.mutate(n.id)}>
                    {n.title}
                  </Link>
                ) : (
                  <p className="font-medium">{n.title}</p>
                )}
                {n.body && <p className="text-muted-foreground">{n.body}</p>}
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">{formatRelative(n.created_at)}</span>
            </div>
            {!n.is_read && (
              <Button size="sm" variant="link" className="px-0" onClick={() => markRead.mutate(n.id)}>
                Mark read
              </Button>
            )}
          </li>
        ))}
        {rows.length === 0 && <li className="p-3 text-sm text-muted-foreground">Nothing here.</li>}
      </ul>
      {pagination && pagination.total_pages > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          {page} / {pagination.total_pages}
          <Button size="sm" variant="outline" disabled={page >= pagination.total_pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}
