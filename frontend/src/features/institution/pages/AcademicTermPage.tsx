import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { AlertTriangle, Check, Star } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DateField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { cn } from '@/utils/cn';
import { institutionApi } from '../api';
import { useInstMutation, useTerm } from '../hooks';
import { TERM_STATUSES } from '../types';

const DATE_FIELDS = [
  ['start_date', 'Starts'],
  ['registration_start', 'Registration opens'],
  ['registration_end', 'Registration closes'],
  ['add_drop_end', 'Add/drop ends'],
  ['last_instruction_date', 'Last instruction day'],
  ['end_date', 'Ends'],
] as const;
type DateKey = (typeof DATE_FIELDS)[number][0];

/** /admin/academic-terms/:id — dates, registration windows and the forward-only status stepper with blocking checks. */
export default function AcademicTermPage() {
  const { id } = useParams();
  const { can } = usePermission();
  const term = useTerm(id);
  const roots = ['academic-terms', 'academic-years'];
  const save = useInstMutation((b: Record<string, unknown>) => institutionApi.updateTerm(id!, b), roots);
  const advance = useInstMutation((s: string) => institutionApi.changeTermStatus(id!, s), roots);
  const current = useInstMutation(() => institutionApi.setCurrentTerm(id!), roots);
  const [dates, setDates] = useState<Record<DateKey, string | null>>({} as Record<DateKey, string | null>);
  const t = term.data?.data;

  useEffect(() => {
    if (t) setDates(Object.fromEntries(DATE_FIELDS.map(([k]) => [k, t[k]])) as Record<DateKey, string | null>);
  }, [t]);

  if (term.isLoading || !t) return <PageSkeleton />;
  const idx = TERM_STATUSES.indexOf(t.status as (typeof TERM_STATUSES)[number]);
  const manage = can('sessions', 'manage') && !t.is_locked;
  const onErr = (e: unknown) => toast.error(getApiError(e));

  return (
    <div className="space-y-4">
      <PageHeader
        title={t.name}
        breadcrumbs={[{ label: 'Academic years', to: '/admin/academic-years' }, { label: t.academic_year_name ?? '' }, { label: t.name }]}
        description={`${t.term_type} · sequence ${t.sequence}`}
        actions={
          manage &&
          !t.is_current && (
            <Button variant="outline" onClick={() => current.mutate(undefined, { onSuccess: () => toast.success('Current term set'), onError: onErr })}>
              <Star className="h-4 w-4" /> Set current
            </Button>
          )
        }
      />
      <Card>
        <CardHeader>
          <CardTitle>Status</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <ol className="flex flex-wrap items-center gap-2">
            {TERM_STATUSES.map((s, i) => (
              <li key={s} className="flex items-center gap-2">
                <span
                  className={cn(
                    'flex items-center gap-1 rounded-full border px-3 py-1 text-xs',
                    i < idx && 'border-status-approved text-status-approved',
                    i === idx && 'border-primary bg-primary text-primary-foreground',
                    i > idx && 'text-muted-foreground',
                  )}
                >
                  {i < idx && <Check className="h-3 w-3" />}
                  {s.replace(/_/g, ' ')}
                </span>
                {i < TERM_STATUSES.length - 1 && <span className="text-muted-foreground">→</span>}
              </li>
            ))}
          </ol>
          {t.blocking_checks.length > 0 && (
            <div className="rounded-md border border-status-pending/40 bg-status-pending/10 p-3 text-sm">
              <p className="mb-1 flex items-center gap-1 font-medium">
                <AlertTriangle className="h-4 w-4" /> Closing is blocked by:
              </p>
              <ul className="list-disc pl-5">
                {t.blocking_checks.map((c) => (
                  <li key={c.key}>
                    {c.label}
                    {c.detail ? ` — ${c.detail}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {manage && t.next_status && (
            <Button
              disabled={t.blocking_checks.length > 0 || (t.next_status === 'closed' && !can('sessions', 'close'))}
              loading={advance.isPending}
              onClick={() =>
                advance.mutate(t.next_status!, { onSuccess: () => toast.success(`Moved to ${t.next_status}`), onError: onErr })
              }
            >
              Advance to {t.next_status.replace(/_/g, ' ')}
            </Button>
          )}
          {t.is_locked && <Badge variant="warning">locked</Badge>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Dates and windows</CardTitle>
        </CardHeader>
        <CardContent>
          <fieldset disabled={!manage} className="grid gap-3 sm:grid-cols-3">
            {DATE_FIELDS.map(([k, label]) => (
              <DateField key={k} label={label} value={dates[k]} onChange={(v) => setDates({ ...dates, [k]: v })} />
            ))}
          </fieldset>
          {manage && (
            <Button
              className="mt-3"
              loading={save.isPending}
              onClick={() => save.mutate({ ...dates, version: t.version }, { onSuccess: () => toast.success('Dates saved'), onError: onErr })}
            >
              Save dates
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
