import { useEffect, useState } from 'react';
import { BellRing, Calculator, Download, RefreshCw } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { SimpleTable } from '@/features/hr/components/shared';
import { TermPicker } from '@/features/registration/pages/OfferingsPage';
import { attendanceApi } from '../api';
import {
  useAlertConfig,
  useAttendanceMutation,
  useCondonations,
  useDetention,
  useEligibility,
  useMissing,
  useOds,
  useOfferingSummaries,
  useSummaries,
  useUnmatched,
  useVersions,
} from '../hooks';
import { DECISION_VARIANT, hhmm, type EligibilityRow } from '../types';
import { SummaryTable } from './FacultyAttendancePages';

const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));

// ---- /admin/attendance ------------------------------------------------------------------------------------------------
function OfferingsTab() {
  const [term, setTerm] = useState('');
  const [scope, setScope] = useState<string>();
  const [offering, setOffering] = useState('');
  const list = useOfferingSummaries({ term_id: term || undefined, scope });
  const students = useSummaries({ offering_id: offering || undefined, scope, page_size: 200 }, !!offering);
  const recompute = useAttendanceMutation(() => attendanceApi.recompute(term));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <TermPicker value={term} onChange={setTerm} />
        <ScopeTabs visibility={list.data?.meta.visibility} value={scope} onChange={setScope} />
        <Button variant="outline" disabled={!term} onClick={() => recompute.mutate(undefined, { onSuccess: () => toast.success('Recompute queued — see Jobs'), onError: fail })}>
          <RefreshCw className="h-4 w-4" /> Recompute term
        </Button>
      </div>
      <SimpleTable
        head={['Course', 'Students', 'Avg %', 'Eligible', 'Condonable', 'Not eligible', 'Condoned', '']}
        rows={(list.data?.data ?? []).map((o) => [
          `${o.course_code ?? ''} ${o.course_title ?? ''}`,
          Object.values(o.eligibility ?? {}).reduce((a, b) => a + b, 0),
          o.pct.toFixed(1),
          o.eligibility?.eligible ?? 0,
          <Badge key="c" variant="warning">{o.eligibility?.condonable ?? 0}</Badge>,
          <Badge key="n" variant="destructive">{o.eligibility?.not_eligible ?? 0}</Badge>,
          o.eligibility?.condoned ?? 0,
          <Button key="v" size="sm" variant="outline" onClick={() => setOffering(o.offering_id)}>Students</Button>,
        ])}
        empty="No summaries yet — attendance has not been marked for this term."
      />
      {offering && <SummaryTable rows={students.data?.data ?? []} />}
    </div>
  );
}

function MissingTab() {
  const list = useMissing({ days: 14 });
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Past sessions (14 days) still without attendance — flagged nightly; HODs receive a daily digest.</p>
      <SimpleTable
        head={['Date', 'Time', 'Course', 'Faculty']}
        rows={(list.data?.data ?? []).map((m) => [m.session_date, hhmm(m.start_time), m.course_code, m.staff_name ?? '—'])}
        empty="Every past session has attendance."
      />
    </div>
  );
}

function DevicesTab() {
  const { canAny } = usePermission();
  const list = useUnmatched(canAny([['attendance', 'device_manage'], ['attendance', 'view_all']]));
  return (
    <SimpleTable
      head={['When', 'Identifier', 'Reason', 'Candidates']}
      rows={(list.data?.data ?? []).map((p) => [new Date(p.at).toLocaleString(), p.identifier, p.reason, p.candidates])}
      empty="No unmatched punches in the last 30 days."
    />
  );
}

function AlertsTab() {
  const cfg = useAlertConfig();
  const [form, setForm] = useState({ consecutive_absences: 3, checkpoints: '25,50,75', notify_guardians: true, notify_mentor: true });
  useEffect(() => {
    const d = cfg.data?.data;
    if (d) setForm({ consecutive_absences: d.consecutive_absences ?? 3, checkpoints: (d.checkpoints ?? []).join(','), notify_guardians: d.notify_guardians ?? true, notify_mentor: d.notify_mentor ?? true });
  }, [cfg.data]);
  const save = useAttendanceMutation(() =>
    attendanceApi.saveAlertConfig({
      ...form,
      checkpoints: form.checkpoints.split(',').map((x) => Number(x.trim())).filter((n) => n > 0 && n <= 100),
    }),
  );
  if (cfg.error) return <p className="text-sm text-muted-foreground">{getApiError(cfg.error)}</p>;
  return (
    <div className="max-w-md space-y-3">
      <label className="block text-sm">
        Alert guardians after consecutive absences
        <Input type="number" min={1} max={20} value={form.consecutive_absences} onChange={(e) => setForm({ ...form, consecutive_absences: Number(e.target.value) })} />
      </label>
      <label className="block text-sm">
        Warning checkpoints (% of instruction days)
        <Input value={form.checkpoints} onChange={(e) => setForm({ ...form, checkpoints: e.target.value })} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.notify_guardians} onChange={(e) => setForm({ ...form, notify_guardians: e.target.checked })} /> Copy alerts to guardians
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.notify_mentor} onChange={(e) => setForm({ ...form, notify_mentor: e.target.checked })} /> Copy warnings to the mentor / advisor
      </label>
      <Button onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Alert settings saved'), onError: fail })}>Save</Button>
    </div>
  );
}

export function AdminAttendancePage() {
  useTitle('Attendance');
  const { can } = usePermission();
  return (
    <div className="space-y-4">
      <PageHeader title="Attendance" description="Offering summaries, missing sessions, device punches and alert settings." />
      <Tabs defaultValue="offerings">
        <TabsList>
          <TabsTrigger value="offerings">Offerings</TabsTrigger>
          <TabsTrigger value="missing">Missing sessions</TabsTrigger>
          <TabsTrigger value="devices">Devices</TabsTrigger>
          {can('settings', 'manage') && <TabsTrigger value="alerts">Alerts</TabsTrigger>}
        </TabsList>
        <TabsContent value="offerings"><OfferingsTab /></TabsContent>
        <TabsContent value="missing"><MissingTab /></TabsContent>
        <TabsContent value="devices"><DevicesTab /></TabsContent>
        {can('settings', 'manage') && <TabsContent value="alerts"><AlertsTab /></TabsContent>}
      </Tabs>
    </div>
  );
}

// ---- /admin/attendance/od ---------------------------------------------------------------------------------------------------
export function OdQueuePage() {
  useTitle('On-duty requests');
  const [scope, setScope] = useState<string>();
  const [status, setStatus] = useState('requested');
  const list = useOds({ scope, status: status || undefined, page_size: 100 });
  const act = useAttendanceMutation((v: { id: string; action: 'recommend' | 'approve' | 'reject' }) => attendanceApi.odAction(v.id, v.action));
  const run = (id: string, action: 'recommend' | 'approve' | 'reject') =>
    act.mutate({ id, action }, { onSuccess: (r) => toast.success(`${action}: ${r.data.status}${r.data.sessions_applied ? ` (${r.data.sessions_applied.length} sessions)` : ''}`), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="On-duty requests" description="Recommend (faculty / advisor), approve (HOD / registrar) — approval marks the sessions on duty." />
      <div className="flex flex-wrap gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={scope} onChange={setScope} />
        <Select className="w-44" aria-label="Status" options={['', 'requested', 'recommended', 'approved', 'rejected', 'withdrawn'].map((s) => ({ value: s, label: s || 'All' }))} value={status} onChange={(e) => setStatus(e.target.value)} />
      </div>
      <SimpleTable
        head={['Student', 'Dates', 'Reason', 'Docs', 'Status', '']}
        rows={(list.data?.data ?? []).map((o) => [
          <span key="s">{o.student_name} <span className="text-xs text-muted-foreground">{o.registration_number}</span></span>,
          `${o.from_date} → ${o.to_date}`,
          `${o.reason_type}${o.reason ? ` — ${o.reason}` : ''}`,
          (o.documents ?? []).length,
          <StatusBadge key="st" status={o.status} />,
          <span key="a" className="flex gap-1">
            {o.can_recommend && <Button size="sm" variant="outline" onClick={() => run(o.id, 'recommend')}>Recommend</Button>}
            {o.can_approve && <Button size="sm" onClick={() => run(o.id, 'approve')}>Approve</Button>}
            {o.can_approve && <Button size="sm" variant="outline" onClick={() => run(o.id, 'reject')}>Reject</Button>}
          </span>,
        ])}
        empty="No requests."
      />
    </div>
  );
}

// ---- /admin/attendance/condonations ------------------------------------------------------------------------------------------------
export function CondonationsPage() {
  useTitle('Condonations');
  const [scope, setScope] = useState<string>();
  const [status, setStatus] = useState('');
  const list = useCondonations({ scope, status: status || undefined, page_size: 100 });
  const act = useAttendanceMutation((v: { id: string; action: 'recommend' | 'approve' | 'reject' }) => attendanceApi.condonationAction(v.id, v.action));
  const run = (id: string, action: 'recommend' | 'approve' | 'reject') =>
    act.mutate({ id, action }, { onSuccess: (r) => toast.success(`Condonation ${r.data.status}`), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Condonations" description="HOD recommends, registrar / principal approves; the fee (if any) condones on payment." />
      <div className="flex flex-wrap gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={scope} onChange={setScope} />
        <Select className="w-48" aria-label="Status" options={['', 'requested', 'hod_recommended', 'approved', 'rejected'].map((s) => ({ value: s, label: s || 'All' }))} value={status} onChange={(e) => setStatus(e.target.value)} />
      </div>
      <SimpleTable
        head={['Student', 'Course', '%', 'Reason', 'Fee', 'Status', '']}
        rows={(list.data?.data ?? []).map((c) => [
          <span key="s">{c.student_name} <span className="text-xs text-muted-foreground">{c.registration_number}</span></span>,
          c.course_code ?? 'aggregate',
          c.actual_pct.toFixed(1),
          `${c.reason_type}${c.reason ? ` — ${c.reason}` : ''}${(c.documents ?? []).length ? ` (${(c.documents ?? []).length} doc)` : ''}`,
          c.fee_paise ? <span key="f">₹{(c.fee_paise / 100).toFixed(2)} <StatusBadge status={c.fee_status} /></span> : '—',
          <StatusBadge key="st" status={c.status} />,
          c.can_act ? (
            <span key="a" className="flex gap-1">
              {c.status === 'requested' && <Button size="sm" variant="outline" onClick={() => run(c.id, 'recommend')}>Recommend</Button>}
              <Button size="sm" onClick={() => run(c.id, 'approve')}>Approve</Button>
              <Button size="sm" variant="outline" onClick={() => run(c.id, 'reject')}>Reject</Button>
            </span>
          ) : null,
        ])}
        empty="No condonation requests."
      />
    </div>
  );
}

// ---- /admin/attendance/eligibility -----------------------------------------------------------------------------------------------
export function EligibilityPage() {
  useTitle('Eligibility');
  const { can } = usePermission();
  const [term, setTerm] = useState('');
  const [version, setVersion] = useState('');
  const [decision, setDecision] = useState('');
  const [deciding, setDeciding] = useState<EligibilityRow>();
  const [d, setD] = useState({ decision: 'eligible', reason: '' });
  const versions = useVersions(term || undefined);
  const rows = useEligibility(term || undefined, { version: version || undefined, decision: decision || undefined, page_size: 200 });
  const detention = useDetention(term || undefined, {});
  const compute = useAttendanceMutation((dry: boolean) => attendanceApi.compute(term, { dry_run: dry }));
  const decide = useAttendanceMutation(() => attendanceApi.decide(deciding!.id, d));
  const exportList = useAttendanceMutation(() => attendanceApi.exportDetention(term));
  const notify = useAttendanceMutation(() => attendanceApi.notifyDetained(term));
  const writer = can('exams', 'eligibility');
  return (
    <div className="space-y-4">
      <PageHeader
        title="Eligibility"
        description="Versioned term snapshots: attendance, CIA, fees and exam holds. Phase 14 reads the latest version into exam registrations."
        actions={
          writer && (
            <div className="flex gap-2">
              <Button variant="outline" disabled={!term} onClick={() => compute.mutate(true, { onSuccess: (r) => toast.success(`Dry run: ${r.data.rows} rows ${JSON.stringify(r.data.counts)}`), onError: fail })}>
                <Calculator className="h-4 w-4" /> Dry run
              </Button>
              <Button disabled={!term} onClick={() => compute.mutate(false, { onSuccess: () => toast.success('Computation queued — see Jobs'), onError: fail })}>
                <Calculator className="h-4 w-4" /> Compute
              </Button>
            </div>
          )
        }
      />
      <div className="flex flex-wrap gap-2">
        <TermPicker value={term} onChange={setTerm} />
        <Select className="w-36" aria-label="Version" options={[{ value: '', label: 'Latest' }, ...(versions.data?.data ?? []).map((v) => ({ value: String(v), label: `v${v}` }))]} value={version} onChange={(e) => setVersion(e.target.value)} />
        <Select className="w-40" aria-label="Decision" options={['', 'eligible', 'pending', 'detained', 'condoned', 'debarred'].map((s) => ({ value: s, label: s || 'All decisions' }))} value={decision} onChange={(e) => setDecision(e.target.value)} />
      </div>
      <SimpleTable
        head={['Student', 'Course', 'Att. %', 'CIA', 'Fee', 'Hold', 'Decision', 'Reasons', 'v', '']}
        rows={(rows.data?.data ?? []).map((r) => [
          <span key="s">{r.student_name} <span className="text-xs text-muted-foreground">{r.registration_number}</span></span>,
          r.course_code,
          r.attendance_pct?.toFixed(1) ?? '—',
          r.is_cia_ok ? 'ok' : 'fail',
          r.is_fee_ok ? 'ok' : 'due',
          r.is_hold_ok ? 'ok' : 'hold',
          <Badge key="d" variant={DECISION_VARIANT[r.decision] ?? 'outline'}>{r.decision}</Badge>,
          (r.reason_codes ?? []).join(', '),
          r.version,
          writer ? <Button key="x" size="sm" variant="outline" onClick={() => { setDeciding(r); setD({ decision: r.decision, reason: '' }); }}>Decide</Button> : null,
        ])}
        empty={term ? 'Not computed yet for this term.' : 'Choose a term.'}
      />
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="font-medium">Detention list ({detention.data?.data.length ?? 0})</h3>
          <Button size="sm" variant="outline" disabled={!term} onClick={() => exportList.mutate(undefined, { onSuccess: () => toast.success('XLSX export queued — see Jobs'), onError: fail })}>
            <Download className="h-4 w-4" /> Export
          </Button>
          {writer && (
            <Button size="sm" variant="outline" disabled={!term} onClick={() => notify.mutate(undefined, { onSuccess: (r) => toast.success(r.message ?? 'Notified'), onError: fail })}>
              <BellRing className="h-4 w-4" /> Notify detained
            </Button>
          )}
        </div>
        <SimpleTable
          head={['Programme', 'Reg. no.', 'Student', 'Course', '%', 'Reasons']}
          rows={(detention.data?.data ?? []).map((x) => [x.program_code, x.registration_number, x.student_name, x.course_code, x.attendance_pct?.toFixed(1) ?? '—', (x.reason_codes ?? []).join(', ')])}
          empty="Nobody is detained in the latest version."
        />
      </section>
      <Modal
        open={!!deciding}
        onOpenChange={(o) => !o && setDeciding(undefined)}
        title={`Decide — ${deciding?.student_name ?? ''} ${deciding?.course_code ?? ''}`}
        footer={<Button disabled={d.reason.trim().length < 3} onClick={() => decide.mutate(undefined, { onSuccess: () => { toast.success('Decision recorded'); setDeciding(undefined); }, onError: fail })}>Save</Button>}
      >
        <Select aria-label="Decision" options={['eligible', 'pending', 'detained', 'condoned', 'debarred'].map((s) => ({ value: s, label: s }))} value={d.decision} onChange={(e) => setD({ ...d, decision: e.target.value })} />
        <Textarea className="mt-2" aria-label="Reason" placeholder="Reason (audited)" value={d.reason} onChange={(e) => setD({ ...d, reason: e.target.value })} />
      </Modal>
    </div>
  );
}
