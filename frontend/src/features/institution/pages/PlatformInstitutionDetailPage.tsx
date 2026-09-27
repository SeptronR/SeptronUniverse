import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Ban, CheckCircle2, ToggleLeft } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button, buttonVariants } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { institutionApi } from '../api';
import { useInstMutation } from '../hooks';

/** /super-admin/institutions/:id — profile summary, subscription, Features tab (Phase 02 page), suspend / activate. */
export default function PlatformInstitutionDetailPage() {
  const { id } = useParams();
  const inst = useQuery({ queryKey: ['platform-institutions', 'one', id], queryFn: () => institutionApi.platformInstitution(id!), enabled: !!id });
  const suspend = useInstMutation(() => institutionApi.suspend(id!, 'suspended by the platform'), ['platform-institutions']);
  const activate = useInstMutation(() => institutionApi.activate(id!), ['platform-institutions']);
  const i = inst.data?.data;
  if (inst.isLoading || !i) return <PageSkeleton />;
  const onErr = (e: unknown) => toast.error(getApiError(e));
  return (
    <div className="space-y-4">
      <PageHeader
        title={i.name}
        breadcrumbs={[{ label: 'Institutions', to: '/super-admin/institutions' }, { label: i.slug }]}
        description={<span className="flex items-center gap-2">{i.institution_type.replace(/_/g, ' ')} · pack {i.regulatory_pack} <StatusBadge status={i.status} /></span>}
        actions={
          <>
            <Link to={`/super-admin/institutions/${i.id}/features`} className={buttonVariants({ variant: 'outline' })}>
              <ToggleLeft className="h-4 w-4" /> Features
            </Link>
            {i.status === 'suspended' ? (
              <Button onClick={() => activate.mutate(undefined, { onSuccess: () => toast.success('Activated'), onError: onErr })}>
                <CheckCircle2 className="h-4 w-4" /> Activate
              </Button>
            ) : (
              <Button variant="destructive" onClick={() => suspend.mutate(undefined, { onSuccess: () => toast.success('Suspended — sessions revoked'), onError: onErr })}>
                <Ban className="h-4 w-4" /> Suspend
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Subscription</CardTitle></CardHeader>
          <CardContent className="text-sm">
            Plan <b>{i.plan_code ?? '—'}</b> · {i.subscription_status ?? 'none'}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Structure</CardTitle></CardHeader>
          <CardContent className="text-sm">{i.college_count} college(s) · {i.user_count} user(s)</CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Settings</CardTitle></CardHeader>
          <CardContent className="text-sm">Timezone {i.timezone} · created {new Date(i.created_at).toLocaleDateString()}</CardContent>
        </Card>
      </div>
    </div>
  );
}
