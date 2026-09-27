import { useParams } from 'react-router-dom';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { workflowApi } from '../api';
import { ActPanel } from '../components/ActPanel';
import { WorkflowTimeline } from '../components/WorkflowTimeline';
import { useInstance, useWorkflowMutation } from '../hooks';

/** /approvals/instances/:id — one request with its timeline; approvers act here, the requester may cancel. */
export default function ApprovalInstancePage() {
  const { id } = useParams();
  const inst = useInstance(id);
  const cancel = useWorkflowMutation(() => workflowApi.cancel(id!));
  const i = inst.data?.data;
  if (inst.isLoading || !i) return <PageSkeleton />;
  return (
    <div className="space-y-4">
      <PageHeader
        title={i.title ?? i.key}
        breadcrumbs={[{ label: 'Approvals', to: '/approvals' }, { label: i.key }]}
        description={
          <span className="flex items-center gap-2">
            {i.module} · v{i.version} · requested by {i.started_by_name ?? '—'} <StatusBadge status={i.status} />
          </span>
        }
        actions={
          i.can_cancel && (
            <Button variant="outline" onClick={() => cancel.mutate(undefined, { onSuccess: () => toast.success('Cancelled'), onError: (e) => toast.error(getApiError(e)) })}>
              Cancel request
            </Button>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            <WorkflowTimeline instance={i} />
          </CardContent>
        </Card>
        {i.can_act && (
          <Card>
            <CardHeader>
              <CardTitle>Your decision</CardTitle>
            </CardHeader>
            <CardContent>
              <ActPanel instance={i} />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
