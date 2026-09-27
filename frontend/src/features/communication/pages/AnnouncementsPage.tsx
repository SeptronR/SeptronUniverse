import { Link, useParams } from 'react-router-dom';
import { CheckCircle2, Pin } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { formatRelative } from '@/utils/formatters';
import { commsApi } from '../api';
import { RichTextView } from '../components/RichTextEditor';
import { useAnnouncement, useAnnouncements, useCommsMutation } from '../hooks';

/** /announcements — what the signed-in user's audience rules include (pinned first); /announcements/:id — detail + ack. */
export default function AnnouncementsPage() {
  const { id } = useParams();
  return id ? <AnnouncementDetail id={id} /> : <AnnouncementList />;
}

function AnnouncementList() {
  const list = useAnnouncements({ scope: 'self', page_size: 50 });
  if (list.isLoading) return <PageSkeleton />;
  return (
    <div className="space-y-4">
      <PageHeader title="Announcements" />
      <div className="space-y-2">
        {(list.data?.data ?? []).map((a) => (
          <Card key={a.id}>
            <CardContent className="flex items-start justify-between gap-3 p-3">
              <div className="min-w-0">
                <Link to={`/announcements/${a.id}`} className="flex items-center gap-2 font-medium hover:underline">
                  {a.is_pinned && <Pin className="h-4 w-4" />} {a.title}
                </Link>
                <p className="text-xs text-muted-foreground">{a.publish_at ? formatRelative(a.publish_at) : ''}</p>
              </div>
              {a.requires_ack && (a.my_acknowledged_at ? <Badge variant="success">acknowledged</Badge> : <Badge variant="warning">needs acknowledgement</Badge>)}
            </CardContent>
          </Card>
        ))}
        {(list.data?.data ?? []).length === 0 && <p className="text-sm text-muted-foreground">No announcements.</p>}
      </div>
    </div>
  );
}

function AnnouncementDetail({ id }: { id: string }) {
  const a = useAnnouncement(id);
  const ackOn = useFeature('comms.announcement_ack');
  const ack = useCommsMutation(() => commsApi.acknowledge(id), ['announcements', 'notifications']);
  const d = a.data?.data;
  if (a.isLoading || !d) return <PageSkeleton />;
  return (
    <div className="space-y-4">
      <PageHeader title={d.title} breadcrumbs={[{ label: 'Announcements', to: '/announcements' }, { label: d.title }]} description={d.publish_at ? formatRelative(d.publish_at) : undefined} />
      <Card>
        <CardContent className="p-4">
          <RichTextView html={d.body} />
        </CardContent>
      </Card>
      {d.requires_ack && ackOn && (
        d.my_acknowledged_at ? (
          <p className="flex items-center gap-2 text-sm text-status-approved">
            <CheckCircle2 className="h-4 w-4" /> Acknowledged {formatRelative(d.my_acknowledged_at)}
          </p>
        ) : (
          <Button loading={ack.isPending} onClick={() => ack.mutate(undefined, { onSuccess: () => toast.success('Acknowledged'), onError: (e) => toast.error(getApiError(e)) })}>
            I have read this
          </Button>
        )
      )}
      {d.ack_stats && (
        <p className="text-sm text-muted-foreground">
          {d.ack_stats.read}/{d.ack_stats.total} read · {d.ack_stats.acknowledged} acknowledged
        </p>
      )}
    </div>
  );
}
