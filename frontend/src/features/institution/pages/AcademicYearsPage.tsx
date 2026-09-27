import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CalendarRange, Lock, LockOpen, Plus, RefreshCw, Star } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DateField, FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { institutionApi } from '../api';
import { useInstMutation, useYears } from '../hooks';
import type { AcademicYear, RolloverPayload, RolloverTerm } from '../types';

const ROOTS = ['academic-years', 'academic-terms'];

function nextYearDefaults(current: AcademicYear | undefined): RolloverPayload {
  const start = current ? new Date(current.end_date) : new Date();
  start.setDate(start.getDate() + 1);
  const y = start.getFullYear();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const end = new Date(y + 1, start.getMonth(), start.getDate() - 1);
  const terms: RolloverTerm[] = (current?.terms.length ? current.terms : [
    { name: 'Odd Semester', term_type: 'odd', sequence: 1, start_date: '', end_date: '' },
    { name: 'Even Semester', term_type: 'even', sequence: 2, start_date: '', end_date: '' },
  ]).map((t) => {
    const shift = (s: string) => (s ? iso(new Date(new Date(s).setFullYear(new Date(s).getFullYear() + 1))) : '');
    return { name: t.name, term_type: t.term_type, sequence: t.sequence, start_date: shift(t.start_date), end_date: shift(t.end_date) };
  });
  return {
    new_year_name: `${y}-${String((y + 1) % 100).padStart(2, '0')}`,
    start_date: iso(start),
    end_date: iso(end),
    terms,
    promote_batches: false,
    college_id: current?.college_id ?? null,
    lock_previous: false,
  };
}

/** Rollover wizard: new year → terms template → promote batches → summary (Prompts/03 §03.9). */
function RolloverWizard({ current, onClose }: { current: AcademicYear | undefined; onClose: () => void }) {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<RolloverPayload>(() => nextYearDefaults(current));
  const rollover = useInstMutation((b: RolloverPayload) => institutionApi.rollover(b), ROOTS);
  const steps = ['New year', 'Terms', 'Batches', 'Summary'];
  const setTerm = (i: number, patch: Partial<RolloverTerm>) =>
    setData({ ...data, terms: data.terms.map((t, j) => (j === i ? { ...t, ...patch } : t)) });

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      size="lg"
      title="Academic year rollover"
      description={`Step ${step + 1} of 4 · ${steps[step]}`}
      footer={
        <>
          {step > 0 && (
            <Button variant="outline" onClick={() => setStep(step - 1)}>
              Back
            </Button>
          )}
          {step < 3 ? (
            <Button onClick={() => setStep(step + 1)}>Next</Button>
          ) : (
            <Button
              loading={rollover.isPending}
              onClick={() =>
                rollover.mutate(data, {
                  onSuccess: (r) => {
                    toast.success(`Rolled over to ${r.data.year.name}`);
                    onClose();
                  },
                  onError: (e) => toast.error(getApiError(e)),
                })
              }
            >
              Roll over
            </Button>
          )}
        </>
      }
    >
      {step === 0 && (
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Name" value={data.new_year_name} onChange={(e) => setData({ ...data, new_year_name: e.target.value })} />
          <DateField label="Starts" value={data.start_date} onChange={(v) => setData({ ...data, start_date: v ?? '' })} />
          <DateField label="Ends" value={data.end_date} onChange={(v) => setData({ ...data, end_date: v ?? '' })} />
        </div>
      )}
      {step === 1 && (
        <div className="space-y-2">
          {data.terms.map((t, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-4">
              <FormField label="Term" value={t.name} onChange={(e) => setTerm(i, { name: e.target.value })} />
              <FormField label="Type" value={t.term_type} disabled />
              <DateField label="Starts" value={t.start_date} onChange={(v) => setTerm(i, { start_date: v ?? '' })} />
              <DateField label="Ends" value={t.end_date} onChange={(v) => setTerm(i, { end_date: v ?? '' })} />
            </div>
          ))}
        </div>
      )}
      {step === 2 && (
        <div className="space-y-3 text-sm">
          <label className="flex items-center gap-2">
            <Checkbox checked={data.promote_batches} onCheckedChange={(c) => setData({ ...data, promote_batches: c === true })} />
            Promote batches to the next term (runs the batch/student hooks — available from Phases 05/07)
          </label>
          <label className="flex items-center gap-2">
            <Checkbox checked={!!data.lock_previous} onCheckedChange={(c) => setData({ ...data, lock_previous: c === true })} />
            Lock the previous year {current ? `(${current.name})` : ''}
          </label>
        </div>
      )}
      {step === 3 && (
        <ul className="space-y-1 text-sm">
          <li>
            New year <b>{data.new_year_name}</b>: {data.start_date} → {data.end_date} (becomes current)
          </li>
          {data.terms.map((t) => (
            <li key={t.sequence}>
              {t.name} ({t.term_type}): {t.start_date} → {t.end_date}
            </li>
          ))}
          <li>Promote batches: {data.promote_batches ? 'yes' : 'no'} · Lock previous: {data.lock_previous ? 'yes' : 'no'}</li>
        </ul>
      )}
    </Modal>
  );
}

function NewYearModal({ onClose }: { onClose: () => void }) {
  const [v, setV] = useState({ name: '', start_date: '', end_date: '', is_current: false });
  const create = useInstMutation((b: typeof v) => institutionApi.createYear(b), ROOTS);
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="New academic year"
      footer={
        <Button
          loading={create.isPending}
          onClick={() =>
            create.mutate(v, { onSuccess: () => { toast.success('Year created'); onClose(); }, onError: (e) => toast.error(getApiError(e)) })
          }
        >
          Create
        </Button>
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <FormField label="Name" placeholder="2026-27" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <DateField label="Starts" value={v.start_date} onChange={(d) => setV({ ...v, start_date: d ?? '' })} />
        <DateField label="Ends" value={v.end_date} onChange={(d) => setV({ ...v, end_date: d ?? '' })} />
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={v.is_current} onCheckedChange={(c) => setV({ ...v, is_current: c === true })} /> Make current
        </label>
      </div>
    </Modal>
  );
}

/** /admin/academic-years — years with a terms timeline; set current; lock; rollover wizard. */
export default function AcademicYearsPage() {
  const { can } = usePermission();
  const years = useYears({ page_size: 50 });
  const [wizard, setWizard] = useState(false);
  const [creating, setCreating] = useState(false);
  const setCurrent = useInstMutation((id: string) => institutionApi.setCurrentYear(id), ROOTS);
  const lock = useInstMutation(({ id, lock: l }: { id: string; lock: boolean }) => institutionApi.lockYear(id, l), ROOTS);
  if (years.isLoading) return <PageSkeleton />;
  const rows = years.data?.data ?? [];
  const current = rows.find((y) => y.is_current && !y.college_id) ?? rows.find((y) => y.is_current);
  const manage = can('sessions', 'manage');
  const onErr = (e: unknown) => toast.error(getApiError(e));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Academic years"
        description="Years and their terms. Exactly one current year per institution / college."
        actions={
          <>
            {manage && (
              <Button variant="outline" onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New year
              </Button>
            )}
            {can('sessions', 'rollover') && (
              <Button onClick={() => setWizard(true)}>
                <RefreshCw className="h-4 w-4" /> Rollover
              </Button>
            )}
          </>
        }
      />
      {rows.map((y) => {
        const span = new Date(y.end_date).getTime() - new Date(y.start_date).getTime();
        return (
          <Card key={y.id} className={y.is_locked ? 'opacity-80' : undefined}>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2">
                <CalendarRange className="h-4 w-4" /> {y.name}
                {y.is_current && <Badge variant="success">current</Badge>}
                {y.is_locked && <Badge variant="warning">locked</Badge>}
                {y.college_id && <Badge variant="outline">college</Badge>}
              </CardTitle>
              <div className="flex items-center gap-1">
                <span className="mr-2 text-xs text-muted-foreground">
                  {y.start_date} → {y.end_date}
                </span>
                {manage && !y.is_current && (
                  <Button size="sm" variant="ghost" onClick={() => setCurrent.mutate(y.id, { onSuccess: () => toast.success(`${y.name} is current`), onError: onErr })}>
                    <Star className="h-4 w-4" /> Set current
                  </Button>
                )}
                {can('sessions', 'lock') && (
                  <Button size="sm" variant="ghost" onClick={() => lock.mutate({ id: y.id, lock: !y.is_locked }, { onError: onErr })}>
                    {y.is_locked ? <LockOpen className="h-4 w-4" /> : <Lock className="h-4 w-4" />} {y.is_locked ? 'Unlock' : 'Lock'}
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="relative h-10 rounded-md bg-muted">
                {y.terms.map((t) => {
                  const left = ((new Date(t.start_date).getTime() - new Date(y.start_date).getTime()) / span) * 100;
                  const width = ((new Date(t.end_date).getTime() - new Date(t.start_date).getTime()) / span) * 100;
                  return (
                    <Link
                      key={t.id}
                      to={`/admin/academic-terms/${t.id}`}
                      className="absolute top-1 flex h-8 items-center justify-center overflow-hidden rounded bg-primary/80 px-1 text-xs text-primary-foreground hover:bg-primary"
                      style={{ left: `${left}%`, width: `${Math.max(width, 4)}%` }}
                      title={`${t.name}: ${t.start_date} → ${t.end_date} (${t.status})`}
                    >
                      <span className="truncate">
                        {t.is_current ? '★ ' : ''}
                        {t.name}
                      </span>
                    </Link>
                  );
                })}
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                {y.terms.map((t) => (
                  <Link key={t.id} to={`/admin/academic-terms/${t.id}`} className="flex items-center gap-1 hover:underline">
                    {t.name} <StatusBadge status={t.status} />
                  </Link>
                ))}
              </div>
            </CardContent>
          </Card>
        );
      })}
      {rows.length === 0 && <p className="text-sm text-muted-foreground">No academic years yet.</p>}
      {wizard && <RolloverWizard current={current} onClose={() => setWizard(false)} />}
      {creating && <NewYearModal onClose={() => setCreating(false)} />}
    </div>
  );
}
