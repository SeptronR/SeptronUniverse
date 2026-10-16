import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { academicsApi } from '@/features/academics/api';
import { SimpleTable } from '@/features/hr/components/shared';
import { registrationApi } from '../api';
import { useArrears, useRegistrationMutation, useWindows } from '../hooks';
import { WINDOW_TYPES, label, rupees, type AllocationSummary } from '../types';
import { TermPicker } from './OfferingsPage';

/** /admin/registration/windows — windows of the term with open / close actions and a create dialog. */
export function WindowsPage() {
  const [term, setTerm] = useState('');
  const windows = useWindows({ term_id: term || undefined });
  const [open, setOpen] = useState(false);
  const status = useRegistrationMutation((v: { id: string; status: string }) => registrationApi.windowStatus(v.id, v.status));
  useEffect(() => {
    document.title = 'Registration windows';
  }, []);
  return (
    <div className="space-y-4">
      <PageHeader title="Registration windows" description="Regular, add/drop, late, arrear and other windows with applies-to rules." actions={<div className="flex gap-2"><TermPicker value={term} onChange={setTerm} /><Button onClick={() => setOpen(true)}>New window</Button></div>} />
      <SimpleTable
        head={['Window', 'Type', 'From', 'To', 'Applies to', 'Advisor', 'Late fee', 'Status', '']}
        rows={(windows.data?.data ?? []).map((w) => [
          w.name,
          label(w.window_type),
          new Date(w.starts_at).toLocaleString(),
          new Date(w.ends_at).toLocaleString(),
          w.applies_to && Object.keys(w.applies_to).length ? Object.keys(w.applies_to).map(label).join(', ') : 'Everyone',
          w.requires_advisor_approval ? 'Yes' : 'No',
          rupees(w.late_fee_paise),
          <StatusBadge key="s" status={w.is_open_now ? 'open' : w.status} />,
          <div key="a" className="flex gap-1">
            {w.status !== 'closed' && <Button size="sm" variant="ghost" onClick={() => status.mutateAsync({ id: w.id, status: 'closed' }).then(() => toast.success('Closed')).catch((e) => toast.error(getApiError(e)))}>Close</Button>}
            {w.status !== 'open' && <Button size="sm" variant="ghost" onClick={() => status.mutateAsync({ id: w.id, status: 'open' }).then(() => toast.success('Opened')).catch((e) => toast.error(getApiError(e)))}>Open</Button>}
          </div>,
        ])}
        empty={windows.isLoading ? 'Loading…' : 'No windows for this term.'}
      />
      {open && <WindowDialog termId={term} onClose={() => setOpen(false)} />}
    </div>
  );
}

function WindowDialog({ termId, onClose }: { termId: string; onClose: () => void }) {
  const batches = useQuery({ queryKey: ['batches', 'active'], queryFn: () => academicsApi.batches({ status: 'active', page_size: 100 }) });
  const [form, setForm] = useState({ name: '', window_type: 'regular', starts_at: '', ends_at: '', late_fee: '0', advisor: true, batch_ids: [] as string[] });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useRegistrationMutation(() =>
    registrationApi.createWindow({
      term_id: termId,
      name: form.name,
      window_type: form.window_type,
      starts_at: new Date(form.starts_at).toISOString(),
      ends_at: new Date(form.ends_at).toISOString(),
      late_fee_paise: Math.round(Number(form.late_fee || 0) * 100),
      requires_advisor_approval: form.advisor,
      applies_to: form.batch_ids.length ? { batch_ids: form.batch_ids } : undefined,
    }),
  );
  const submit = () => {
    const e: Record<string, string> = {};
    if (form.name.trim().length < 3) e.name = 'At least 3 characters';
    if (!form.starts_at) e.starts_at = 'Required';
    if (!form.ends_at || form.ends_at <= form.starts_at) e.ends_at = 'Must be after the start';
    setErrors(e);
    if (Object.keys(e).length) return;
    create.mutateAsync(undefined).then(() => { toast.success('Window created'); onClose(); }).catch((err) => toast.error(getApiError(err)));
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New registration window" footer={<Button disabled={create.isPending} onClick={submit}>Create</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Name" required error={errors.name} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Select aria-label="Type" options={WINDOW_TYPES.map((t) => ({ value: t, label: label(t) }))} value={form.window_type} onChange={(e) => setForm({ ...form, window_type: e.target.value })} />
        <FormField label="Starts" type="datetime-local" error={errors.starts_at} value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
        <FormField label="Ends" type="datetime-local" error={errors.ends_at} value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
        <FormField label="Late fee (₹)" type="number" value={form.late_fee} onChange={(e) => setForm({ ...form, late_fee: e.target.value })} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.advisor} onChange={(e) => setForm({ ...form, advisor: e.target.checked })} /> Advisor approval</label>
        <div className="sm:col-span-2">
          <div className="mb-1 text-sm font-medium">Applies to batches (none = everyone)</div>
          <div className="grid max-h-32 grid-cols-2 gap-1 overflow-y-auto text-sm">
            {((batches.data?.data ?? []) as { id: string; code: string }[]).map((b) => (
              <label key={b.id} className="flex items-center gap-2"><input type="checkbox" checked={form.batch_ids.includes(b.id)} onChange={(e) => setForm({ ...form, batch_ids: e.target.checked ? [...form.batch_ids, b.id] : form.batch_ids.filter((x) => x !== b.id) })} />{b.code}</label>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}

/** /admin/registration/allocation — basket + term → dry-run summary → run (job) → manual assignment of unallocated. */
export function AllocationPage() {
  const [term, setTerm] = useState('');
  const [basket, setBasket] = useState('');
  const [mode, setMode] = useState('priority_cgpa');
  const [summary, setSummary] = useState<AllocationSummary | null>(null);
  const baskets = useQuery({ queryKey: ['baskets', 'all'], queryFn: () => academicsApi.baskets({ page_size: 200 }) });
  const forms = useQuery({ queryKey: ['registration', 'forms', basket, term], queryFn: () => registrationApi.basketForms(basket, term), enabled: !!basket && !!term });
  const run = useRegistrationMutation((dry: boolean) => registrationApi.allocate(basket, term, mode, dry));
  const manual = useRegistrationMutation((v: { form: string; course: string }) => registrationApi.manual(basket, v.form, v.course));
  const basketList = (baskets.data?.data ?? []) as { id: string; code: string; name: string; courses?: { course_id: string; code?: string }[] }[];
  const chosen = basketList.find((b) => b.id === basket);
  useEffect(() => {
    document.title = 'Elective allocation';
  }, []);
  return (
    <div className="space-y-4">
      <PageHeader title="Elective allocation" description="Allocate basket electives from the students' choice forms (priority-CGPA, FCFS or lottery)." actions={<TermPicker value={term} onChange={setTerm} />} />
      <div className="flex flex-wrap gap-2">
        <Select className="w-72" aria-label="Basket" placeholder="Select a basket…" options={basketList.map((b) => ({ value: b.id, label: `${b.code} — ${b.name}` }))} value={basket} onChange={(e) => { setBasket(e.target.value); setSummary(null); }} />
        <Select className="w-48" aria-label="Mode" options={['priority_cgpa', 'fcfs', 'lottery'].map((m) => ({ value: m, label: label(m) }))} value={mode} onChange={(e) => setMode(e.target.value)} />
        <Button variant="outline" disabled={!basket || !term || run.isPending} onClick={() => run.mutateAsync(true).then((r) => setSummary(r.data)).catch((e) => toast.error(getApiError(e)))}>Dry run</Button>
        <Button disabled={!summary || run.isPending} onClick={() => run.mutateAsync(false).then(() => toast.success('Allocation queued — see the jobs tray')).catch((e) => toast.error(getApiError(e)))}>Run allocation</Button>
      </div>
      {summary && (
        <div className="space-y-2">
          <div className="text-sm">{summary.candidates} forms · <b>{summary.allocated}</b> allocated · <b>{summary.unallocated}</b> to assign manually</div>
          <div className="flex flex-wrap gap-2 text-xs">{summary.per_course.map((c) => <span key={c.code} className="rounded border px-2 py-1">{c.code}: {c.allocated}/{c.seats}</span>)}</div>
          <SimpleTable head={['Rank', 'Student', 'Key', 'Allocated', 'Choice', 'Status']} rows={summary.results.map((r) => [r.rank, `${r.student_name ?? ''} (${r.registration_number ?? ''})`, r.sort_key ?? '—', r.allocated_course_code ?? '—', r.choice_number ?? '—', <StatusBadge key="s" status={r.status} />])} />
        </div>
      )}
      {basket && term && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Choice forms</h2>
          <SimpleTable
            head={['Student', 'Choices', 'Status', 'Allocated', '']}
            rows={(forms.data?.data ?? []).map((f) => [
              `${f.student_name ?? ''} (${f.registration_number ?? ''})`,
              f.choices.map((c) => `${c.priority}. ${c.code}`).join(' · '),
              <StatusBadge key="s" status={f.status} />,
              f.allocated_course_code ?? '—',
              f.status === 'manual' || f.status === 'unallocated' ? (
                <Select key="m" className="w-40" aria-label="Assign" placeholder="Assign…" options={(chosen?.courses ?? f.choices.map((c) => ({ course_id: c.course_id, code: c.code ?? '' }))).map((c) => ({ value: c.course_id, label: c.code ?? c.course_id }))} value="" onChange={(e) => manual.mutateAsync({ form: f.id, course: e.target.value }).then(() => toast.success('Allocated')).catch((err) => toast.error(getApiError(err)))} />
              ) : null,
            ])}
            empty={forms.isLoading ? 'Loading…' : 'No choice forms.'}
          />
        </div>
      )}
    </div>
  );
}

/** /admin/registration/arrears — arrears register (per student / course) with waive. */
export function ArrearsPage() {
  const { can } = usePermission();
  const [scope, setScope] = useState<string | undefined>();
  const [status, setStatus] = useState('open');
  const [q, setQ] = useState('');
  const list = useArrears({ scope, status: status || undefined, q: q || undefined, page_size: 100 });
  const [waive, setWaive] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const run = useRegistrationMutation(() => registrationApi.waive(waive!, reason));
  useEffect(() => {
    document.title = 'Arrears';
  }, []);
  return (
    <div className="space-y-4">
      <PageHeader title="Arrears" description="Open, registered, cleared and waived arrears; Phase 15 results maintain the register." />
      <ScopeTabs visibility={list.data?.meta.visibility} value={scope} onChange={setScope} labels={{ self: 'Advisees' }} />
      <div className="flex flex-wrap gap-2">
        <Input className="w-56" placeholder="Search name / reg. no." value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-44" aria-label="Status" placeholder="All statuses" options={['open', 'registered', 'cleared', 'waived'].map((s) => ({ value: s, label: label(s) }))} value={status} onChange={(e) => setStatus(e.target.value)} />
      </div>
      <SimpleTable
        head={['Student', 'Batch', 'Course', 'Credits', 'Attempts', 'Status', '']}
        rows={(list.data?.data ?? []).map((a) => [
          `${a.student_name ?? ''} (${a.registration_number ?? ''})`,
          a.batch_code,
          `${a.course_code} — ${a.course_title}`,
          a.credits,
          a.attempts,
          <StatusBadge key="s" status={a.status} />,
          can('students', 'manage') && ['open', 'registered'].includes(a.status) ? <Button key="w" size="sm" variant="ghost" onClick={() => setWaive(a.id)}>Waive</Button> : null,
        ])}
        empty={list.isLoading ? 'Loading…' : 'No arrears.'}
      />
      <Modal open={!!waive} onOpenChange={(o) => !o && setWaive(null)} title="Waive arrear" footer={<Button disabled={reason.trim().length < 5 || run.isPending} onClick={() => run.mutateAsync(undefined).then(() => { toast.success('Waived'); setWaive(null); setReason(''); }).catch((e) => toast.error(getApiError(e)))}>Waive</Button>}>
        <FormField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </div>
  );
}
