import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { academicsApi } from '@/features/academics/api';
import { SimpleTable } from '@/features/hr/components/shared';
import { workflowApi } from '@/features/workflow/api';
import { WorkflowTimeline } from '@/features/workflow/components/WorkflowTimeline';
import { registrationApi } from '../api';
import { useRegistration, useRegistrationMutation, useRegistrations } from '../hooks';
import { REG_STATUSES, label, rupees, type Registration } from '../types';
import { TermPicker } from './OfferingsPage';

/** /admin/registration — ScopeTabs Advisees | Department | All, status filter, bulk-register wizard. */
export default function RegistrationsPage() {
  const navigate = useNavigate();
  const { can } = usePermission();
  const [term, setTerm] = useState('');
  const [scope, setScope] = useState<string | undefined>();
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [bulkOpen, setBulkOpen] = useState(false);
  const list = useRegistrations({ term_id: term || undefined, scope, status: status || undefined, q: q || undefined, page, page_size: 50 });
  useEffect(() => {
    document.title = 'Course registration';
  }, []);
  const pg = list.data?.meta.pagination;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Course registration"
        description="Advisees, department and institution registrations with approvals, overrides and withdrawals."
        actions={
          <div className="flex gap-2">
            <TermPicker value={term} onChange={setTerm} />
            {(can('registration', 'bulk') || can('registration', 'manage')) && <Button variant="outline" onClick={() => setBulkOpen(true)}>Bulk register</Button>}
          </div>
        }
      />
      <ScopeTabs visibility={list.data?.meta.visibility} value={scope} onChange={(s) => { setScope(s); setPage(1); }} labels={{ self: 'Advisees' }} />
      <div className="flex flex-wrap gap-2">
        <Input className="w-56" placeholder="Search name / reg. no." value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select className="w-48" aria-label="Status" placeholder="All statuses" options={REG_STATUSES.map((s) => ({ value: s, label: label(s) }))} value={status} onChange={(e) => setStatus(e.target.value)} />
      </div>
      <SimpleTable
        head={['Student', 'Programme / batch', 'Section', 'Credits', 'Courses', 'Submitted', 'Status']}
        rows={(list.data?.data ?? []).map((r) => [
          <button key="n" type="button" className="text-left font-medium hover:underline" onClick={() => navigate(`/admin/registration/${r.id}`)}>{r.student_name}<div className="font-mono text-xs text-muted-foreground">{r.registration_number}</div></button>,
          `${r.program_code ?? ''} · ${r.batch_code ?? ''}`,
          r.section_name ?? '—',
          r.total_credits,
          `${r.items_count}${r.waitlisted_count ? ` (+${r.waitlisted_count} wl)` : ''}`,
          r.submitted_at ? new Date(r.submitted_at).toLocaleString() : '—',
          <StatusBadge key="s" status={r.status} />,
        ])}
        empty={list.isLoading ? 'Loading…' : 'No registrations.'}
      />
      {pg && pg.total_pages > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          Page {pg.page} of {pg.total_pages} · {pg.total}
          <Button size="sm" variant="outline" disabled={page >= pg.total_pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
      {bulkOpen && <BulkRegisterDialog termId={term} onClose={() => setBulkOpen(false)} />}
    </div>
  );
}

function BulkRegisterDialog({ termId, onClose }: { termId: string; onClose: () => void }) {
  const batches = useQuery({ queryKey: ['batches', 'active'], queryFn: () => academicsApi.batches({ status: 'active', page_size: 100 }) });
  const [batch, setBatch] = useState('');
  const [electives, setElectives] = useState(false);
  const run = useRegistrationMutation(() => registrationApi.bulkRegister({ batch_id: batch, term_id: termId, include_electives: electives }));
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Bulk register a batch" footer={
      <Button disabled={!batch || run.isPending} onClick={() => run.mutateAsync(undefined).then(() => { toast.success('Queued — the report appears in the jobs tray'); onClose(); }).catch((e) => toast.error(getApiError(e)))}>Register</Button>
    }>
      <div className="space-y-3 text-sm">
        <p>Registers every active student of the batch for the mandatory courses of its current term (auto-approved, seats enforced; shortfalls are reported).</p>
        <Select aria-label="Batch" placeholder="Select a batch…" options={((batches.data?.data ?? []) as { id: string; code: string }[]).map((b) => ({ value: b.id, label: b.code }))} value={batch} onChange={(e) => setBatch(e.target.value)} />
        <label className="flex items-center gap-2"><input type="checkbox" checked={electives} onChange={(e) => setElectives(e.target.checked)} /> Include allocated electives</label>
      </div>
    </Modal>
  );
}

/** /admin/registration/:id — items, checks, workflow timeline; approve / reject / request changes; override; withdraw. */
export function RegistrationDetailPage() {
  const { id } = useParams();
  const { can } = usePermission();
  const reg = useRegistration(id);
  const r = reg.data?.data;
  const instance = useQuery({ queryKey: ['workflow', 'instance', r?.workflow_instance_id], queryFn: () => workflowApi.instance(r!.workflow_instance_id!), enabled: !!r?.workflow_instance_id });
  const [decision, setDecision] = useState<null | 'reject' | 'request-changes'>(null);
  const [comment, setComment] = useState('');
  const [drops, setDrops] = useState<string[]>([]);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [withdraw, setWithdraw] = useState<string | null>(null);
  const decide = useRegistrationMutation((a: 'approve' | 'reject' | 'request-changes') =>
    registrationApi.decide(id!, a, { decision: a === 'request-changes' ? 'request_changes' : a, comment: comment || undefined, item_decisions: drops.map((item_id) => ({ item_id, decision: 'drop' })) }),
  );
  const lock = useRegistrationMutation((v: boolean) => registrationApi.lock(id!, v));
  if (!r) return <div className="p-4 text-sm text-muted-foreground">{reg.isLoading ? 'Loading…' : 'Not found.'}</div>;
  const act = (a: 'approve' | 'reject' | 'request-changes') =>
    decide.mutateAsync(a).then((x) => { toast.success(`Registration ${label(x.data.status)}`); setDecision(null); setComment(''); setDrops([]); }).catch((e) => toast.error(getApiError(e)));
  const pending = r.status === 'advisor_pending' && can('registration', 'approve');
  const overrides = can('registration', 'override') || can('registration', 'manage');
  return (
    <div className="space-y-4">
      <PageHeader
        title={`${r.student_name ?? ''} · ${r.registration_number ?? ''}`}
        description={`${r.program_code} ${r.batch_code} ${r.section_name ? `section ${r.section_name}` : ''} — ${r.term_name} (term ${r.term_number ?? '—'})`}
        actions={
          <div className="flex flex-wrap gap-2">
            <StatusBadge status={r.status} />
            {pending && <Button onClick={() => act('approve')} disabled={decide.isPending}>Approve</Button>}
            {pending && <Button variant="outline" onClick={() => setDecision('request-changes')}>Request changes</Button>}
            {pending && <Button variant="destructive" onClick={() => setDecision('reject')}>Reject</Button>}
            {overrides && <Button variant="outline" onClick={() => setOverrideOpen(true)}>Override</Button>}
            {overrides && r.status === 'approved' && <Button variant="outline" onClick={() => lock.mutateAsync(true).then(() => toast.success('Locked')).catch((e) => toast.error(getApiError(e)))}>Lock</Button>}
            {overrides && r.status === 'locked' && <Button variant="outline" onClick={() => lock.mutateAsync(false).then(() => toast.success('Unlocked')).catch((e) => toast.error(getApiError(e)))}>Unlock</Button>}
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Courses · {r.total_credits} credits {r.limits && `(min ${r.limits.min}, max ${r.limits.max})`}</CardTitle></CardHeader>
          <CardContent>
            <SimpleTable
              head={['Course', 'Sec', 'Credits', 'Type', 'Status', '']}
              rows={r.items.map((i) => [
                <div key="c"><div className="font-medium">{i.course_code}</div><div className="text-xs text-muted-foreground">{i.course_title}</div></div>,
                i.section_code,
                i.credits,
                `${label(i.registration_type)}${i.attempt_number > 1 ? ` (attempt ${i.attempt_number})` : ''}`,
                <div key="s"><StatusBadge status={i.status} />{i.drop_reason && <div className="text-xs text-muted-foreground">{i.drop_reason}</div>}</div>,
                <div key="a" className="flex gap-1">
                  {pending && ['selected', 'waitlisted'].includes(i.status) && (
                    <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={drops.includes(i.id)} onChange={(e) => setDrops(e.target.checked ? [...drops, i.id] : drops.filter((x) => x !== i.id))} /> drop</label>
                  )}
                  {overrides && ['confirmed', 'selected'].includes(i.status) && ['approved', 'locked'].includes(r.status) && <Button size="sm" variant="ghost" onClick={() => setWithdraw(i.id)}>Withdraw</Button>}
                </div>,
              ])}
            />
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Checks</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-sm">
              {r.checks.map((c) => <div key={c.key} className={c.passed ? 'text-status-approved' : 'text-status-rejected'}>{c.passed ? '✓' : '✗'} {c.label}{c.detail ? ` — ${c.detail}` : ''}</div>)}
              {r.fee && <div>Fee order {r.fee.ref}: {rupees(r.fee.amount_paise)} ({label(r.fee.status)})</div>}
              {r.overrides && <div className="text-xs text-muted-foreground">Overrides: {JSON.stringify(r.overrides)}</div>}
              {r.advisor_comment && <div className="text-xs">Advisor: {r.advisor_comment}</div>}
            </CardContent>
          </Card>
          {instance.data?.data && <Card><CardHeader><CardTitle>Approval</CardTitle></CardHeader><CardContent><WorkflowTimeline instance={instance.data.data} /></CardContent></Card>}
        </div>
      </div>
      <Modal open={!!decision} onOpenChange={(o) => !o && setDecision(null)} title={decision === 'reject' ? 'Reject registration' : 'Request changes'} footer={<Button disabled={!comment.trim() || decide.isPending} onClick={() => decision && act(decision)}>Send</Button>}>
        <Textarea aria-label="Comment" placeholder="Comment for the student (required)" value={comment} onChange={(e) => setComment(e.target.value)} />
        {drops.length > 0 && <p className="mt-2 text-xs">{drops.length} course(s) will be dropped.</p>}
      </Modal>
      {overrideOpen && <OverrideDialog reg={r} onClose={() => setOverrideOpen(false)} />}
      {withdraw && <WithdrawDialog regId={r.id} itemId={withdraw} onClose={() => setWithdraw(null)} />}
    </div>
  );
}

function OverrideDialog({ reg, onClose }: { reg: Registration; onClose: () => void }) {
  const [form, setForm] = useState({ reason: '', max_credits: '', skip_holds: false });
  const run = useRegistrationMutation(() =>
    registrationApi.override(reg.id, { reason: form.reason, max_credits: form.max_credits ? Number(form.max_credits) : undefined, skip_holds: form.skip_holds }),
  );
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Registrar override" footer={<Button disabled={form.reason.trim().length < 5 || run.isPending} onClick={() => run.mutateAsync(undefined).then(() => { toast.success('Override recorded'); onClose(); }).catch((e) => toast.error(getApiError(e)))}>Save</Button>}>
      <div className="grid gap-3">
        <FormField label="Reason" required value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <FormField label="Maximum credits" type="number" value={form.max_credits} onChange={(e) => setForm({ ...form, max_credits: e.target.value })} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.skip_holds} onChange={(e) => setForm({ ...form, skip_holds: e.target.checked })} /> Skip registration holds</label>
      </div>
    </Modal>
  );
}

function WithdrawDialog({ regId, itemId, onClose }: { regId: string; itemId: string; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const run = useRegistrationMutation(() => registrationApi.withdrawItem(regId, itemId, reason));
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Withdraw course (W)" footer={<Button variant="destructive" disabled={reason.trim().length < 3 || run.isPending} onClick={() => run.mutateAsync(undefined).then(() => { toast.success('Withdrawn'); onClose(); }).catch((e) => toast.error(getApiError(e)))}>Withdraw</Button>}>
      <FormField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} />
    </Modal>
  );
}
