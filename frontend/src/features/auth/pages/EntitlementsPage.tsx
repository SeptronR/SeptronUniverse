import { PageHeader } from '@/components/shared/PageHeader';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { StatusBadge } from '@/components/ui/Badge';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { formatDate, formatNumber } from '@/utils/formatters';
import { useEntitlements } from '../hooks';

const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(2)} GB`;

/** /admin/settings/entitlements — plan, status, limits and current usage (Prompts/02 §02.9). */
export default function EntitlementsPage() {
  const query = useEntitlements();
  if (query.isLoading) return <PageSkeleton />;
  const e = query.data?.data;
  if (!e) return null;

  const rows = [
    {
      label: 'Students',
      used: formatNumber(e.usage.students),
      limit: e.limits.students ? formatNumber(e.limits.students) : 'unlimited',
    },
    {
      label: 'Staff',
      used: formatNumber(e.usage.staff),
      limit: e.limits.staff ? formatNumber(e.limits.staff) : 'unlimited',
    },
    { label: 'Storage', used: gb(e.usage.storage_bytes), limit: e.limits.storage_gb ? `${e.limits.storage_gb} GB` : 'unlimited' },
    {
      label: 'SMS this month',
      used: formatNumber(e.usage.sms_sent),
      limit: e.limits.sms_credits ? formatNumber(e.limits.sms_credits) : 'unlimited',
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader title="Subscription & entitlements" description="Plan limits are enforced when accounts are created." />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {e.plan_name ?? 'No plan'} <StatusBadge status={e.status} />
          </CardTitle>
          <CardDescription>
            {e.starts_on ? `From ${formatDate(e.starts_on)}` : 'No subscription recorded'}
            {e.ends_on ? ` until ${formatDate(e.ends_on)}` : ''}
            {e.grace_until ? ` · grace until ${formatDate(e.grace_until)}` : ''}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!e.writable && (
            <p role="alert" className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm">
              The workspace is read-only until the subscription is renewed.
            </p>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                <th scope="col" className="py-1">
                  Resource
                </th>
                <th scope="col" className="py-1">
                  Used
                </th>
                <th scope="col" className="py-1">
                  Limit
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-b last:border-0">
                  <td className="py-1.5">{r.label}</td>
                  <td className="py-1.5 tabular-nums">{r.used}</td>
                  <td className="py-1.5 tabular-nums text-muted-foreground">{r.limit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
