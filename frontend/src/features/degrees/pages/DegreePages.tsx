import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { degreesApi, openBlob } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['degrees', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['degrees'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const rupees = (p: number) => `₹${(p / 100).toLocaleString('en-IN')}`;
const FIX: Record<string, string> = {
  BACKLOGS: 'Clear open arrears (supplementary exams)',
  DUES_PENDING: 'Request graduation no-dues',
  HOLD_GRADUATION: 'Contact the office that placed the hold',
  CGPA_BELOW_MIN: 'Improve CGPA (improvement exams)',
  MANDATORY_NONCREDIT: 'Pass the mandatory non-credit courses',
  DURATION_EXCEEDED: 'Maximum duration exceeded — contact the registrar',
};

function ReasonChips({ reasons }: { reasons: string[] }) {
  if (!reasons?.length) return <Badge variant="success">eligible</Badge>;
  return <div className="flex flex-wrap gap-1">{reasons.map((r) => <Badge key={r} variant="destructive" title={FIX[r.split(':')[0]] ?? ''}>{r}</Badge>)}</div>;
}

function BatchPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const batches = useQ(['batches'], () => degreesApi.batches());
  return (
    <select className="h-9 rounded-md border bg-background px-2 text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Batch…</option>
      {list(batches.data).map((b: Any) => <option key={b.id} value={b.id}>{b.code ?? b.admission_year}</option>)}
    </select>
  );
}

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <Card><CardContent className="space-y-3 p-4">
      <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>
      {children}
    </CardContent></Card>
  );
}

// ---- /admin/degrees/eligibility ------------------------------------------------------------------------------------------------
export function DegreeEligibilityPage() {
  useTitle('Degree eligibility');
  const [batch, setBatch] = useState('');
  const [exits, setExits] = useState(false);
  const [filter, setFilter] = useState<'' | 'true' | 'false'>('');
  const q = useQ(['elig', batch, filter], () => degreesApi.eligibility({ batch_id: batch || undefined, eligible: filter || undefined }), !!batch);
  const [drawer, setDrawer] = useState<Any | null>(null);
  const [override, setOverride] = useState<Any | null>(null);
  const [reason, setReason] = useState('');
  const run = useRun();
  const rows: Any[] = q.data?.data ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Degree eligibility" description="Credits & buckets, backlogs, CGPA, duration, mandatory non-credit courses, holds and dues — one row per run (history)." />
      <div className="flex flex-wrap items-center gap-2">
        <BatchPicker value={batch} onChange={setBatch} />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={exits} onChange={(e) => setExits(e.target.checked)} /> include NEP exits</label>
        <Button size="sm" disabled={!batch || run.isPending} onClick={() => run.mutate(() => degreesApi.runEligibility({ batch_id: batch, include_exits: exits }), { onSuccess: () => toast.success('Run queued — refresh in a moment'), onError: fail })}>Run</Button>
        <Button size="sm" variant="outline" disabled={!batch} onClick={() => run.mutate(() => degreesApi.runEligibility({ batch_id: batch, include_exits: exits, notify: true }), { onSuccess: () => toast.success('Run + notifications queued'), onError: fail })}>Run & notify</Button>
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={filter} onChange={(e) => setFilter(e.target.value as '' | 'true' | 'false')}>
          <option value="">All</option><option value="true">Eligible</option><option value="false">Not eligible</option>
        </select>
        <span className="text-xs text-muted-foreground">{rows.filter((r) => r.is_eligible).length} eligible · {rows.filter((r) => !r.is_eligible).length} not</span>
      </div>
      <SimpleTable
        head={['Reg. no', 'Name', 'Credits', 'CGPA', 'Backlogs', 'Status', '']}
        rows={rows.map((r) => [
          r.enrollment.registration_number, r.enrollment.student_name, `${r.credits_earned ?? 0} / ${r.credits_required ?? 0}`, r.cgpa ?? '—', r.backlog_count ?? 0,
          <div key="s" className="space-y-1"><ReasonChips reasons={r.reasons} />{r.overridden && <Badge variant="info" title={r.override_reason}>overridden</Badge>}</div>,
          <div key="a" className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => setDrawer(r)}>Buckets</Button>
            <Button size="sm" variant="outline" onClick={() => { setOverride(r); setReason(''); }}>Override</Button>
          </div>,
        ])}
        empty={batch ? 'No checks yet — run the engine.' : 'Pick a batch.'}
      />
      <Modal open={!!drawer} onOpenChange={(o) => !o && setDrawer(null)} title="Credit buckets" size="lg">
        <SimpleTable head={['Bucket', 'Required', 'Earned', '']} rows={(drawer?.bucket_breakdown ?? []).map((b: Any) => [b.bucket, b.required, b.earned, b.ok ? <Badge key="o" variant="success">ok</Badge> : <Badge key="o" variant="destructive">short</Badge>])} />
      </Modal>
      <Modal open={!!override} onOpenChange={(o) => !o && setOverride(null)} title="Override eligibility"
        footer={<>
          <Button variant="outline" disabled={reason.length < 5} onClick={() => run.mutate(() => degreesApi.override(override.id, { decision: 'ineligible', reason }), { onSuccess: () => { toast.success('Overridden'); setOverride(null); }, onError: fail })}>Mark ineligible</Button>
          <Button disabled={reason.length < 5} onClick={() => run.mutate(() => degreesApi.override(override.id, { decision: 'eligible', reason }), { onSuccess: () => { toast.success('Overridden'); setOverride(null); }, onError: fail })}>Mark eligible</Button>
        </>}>
        <p className="mb-2 text-sm">{override?.enrollment.student_name} — <ReasonChips reasons={override?.reasons ?? []} /></p>
        <textarea className="min-h-24 w-full rounded-md border bg-background p-2 text-sm" placeholder="Reason (e.g. council-approved credit equivalence)" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </div>
  );
}

// ---- /admin/degrees/convocations ------------------------------------------------------------------------------------------------
export function ConvocationsPage() {
  useTitle('Convocations');
  const q = useQ(['convs'], () => degreesApi.convocations());
  const [sel, setSel] = useState<Any | null>(null);
  const [form, setForm] = useState<Any | null>(null);
  const [scan, setScan] = useState('');
  const regs = useQ(['regs', sel?.id], () => degreesApi.registrations(sel.id), !!sel);
  const [report, setReport] = useState<'gowns' | 'seating' | 'attendance' | ''>('');
  const rep = useQ(['report', sel?.id, report], () => degreesApi.report(sel.id, report as 'gowns'), !!sel && !!report);
  const run = useRun();
  const next: Record<string, string[]> = { planned: ['registration_open'], registration_open: ['closed'], closed: ['registration_open', 'completed'], completed: [] };
  return (
    <div className="space-y-4">
      <PageHeader title="Convocations" description="Events, registrations (in person / absentia, fee, gown), reports and day-of attendance." actions={<Button onClick={() => setForm({ name: '', held_on: '', venue: '', registration_deadline: '', fee: 0 })}>New convocation</Button>} />
      <SimpleTable
        head={['Name', 'Date', 'Deadline', 'Fee', 'Registrations', 'Status', '']}
        rows={(q.data?.data ?? []).map((c: Any) => [
          c.name, c.held_on ?? '—', c.registration_deadline ?? '—', rupees(c.fee_paise), `${c.counts?.total ?? 0} (${c.counts?.absentia ?? 0} absentia)`, <StatusBadge key="s" status={c.status} />,
          <div key="a" className="flex flex-wrap gap-1">
            <Button size="sm" variant="outline" onClick={() => setSel(c)}>Open</Button>
            {(next[c.status] ?? []).map((s) => <Button key={s} size="sm" variant="ghost" onClick={() => run.mutate(() => degreesApi.convocationStatus(c.id, s), { onSuccess: () => toast.success(s), onError: fail })}>{s.replace('_', ' ')}</Button>)}
          </div>,
        ])}
      />
      {sel && (
        <Section title={`${sel.name} — registrations`} action={<div className="flex gap-1">{(['gowns', 'seating', 'attendance'] as const).map((k) => <Button key={k} size="sm" variant={report === k ? 'default' : 'outline'} onClick={() => setReport(k)}>{k}</Button>)}</div>}>
          <div className="flex gap-2">
            <Input className="w-96" placeholder="Scan / paste attendance QR (cv.…)" value={scan} onChange={(e) => setScan(e.target.value)} />
            <Button size="sm" disabled={!scan} onClick={() => run.mutate(() => degreesApi.attendance(sel.id, { token: scan.trim() }), { onSuccess: () => { toast.success('Marked attended'); setScan(''); }, onError: fail })}>Mark attended</Button>
          </div>
          {report && rep.data && <SimpleTable head={Object.keys((rep.data.data ?? [])[0] ?? { empty: '' })} rows={(rep.data.data ?? []).map((r: Any) => Object.values(r).map((v) => String(v ?? '')))} />}
          <SimpleTable head={['Reg. no', 'Name', 'Programme', 'Mode', 'Gown', 'Guests', 'Fee', 'Status']} rows={(regs.data?.data ?? []).map((r: Any) => [r.enrollment.registration_number, r.enrollment.student_name, r.enrollment.program_code, r.mode, r.gown_size ?? '—', r.guests ?? 0, r.fee_status ?? '—', <StatusBadge key="s" status={r.status} />])} />
        </Section>
      )}
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="New convocation"
        footer={<Button disabled={!form?.name} onClick={() => run.mutate(() => degreesApi.createConvocation({ name: form.name, held_on: form.held_on || undefined, venue: form.venue || undefined, registration_deadline: form.registration_deadline || undefined, fee_paise: Math.round(Number(form.fee || 0) * 100) }), { onSuccess: () => { toast.success('Created'); setForm(null); }, onError: fail })}>Create</Button>}>
        {form && (
          <div className="space-y-2 text-sm">
            <Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label className="block">Date <Input type="date" value={form.held_on} onChange={(e) => setForm({ ...form, held_on: e.target.value })} /></label>
            <Input placeholder="Venue" value={form.venue} onChange={(e) => setForm({ ...form, venue: e.target.value })} />
            <label className="block">Registration deadline <Input type="date" value={form.registration_deadline} onChange={(e) => setForm({ ...form, registration_deadline: e.target.value })} /></label>
            <label className="block">Fee (₹) <Input type="number" value={form.fee} onChange={(e) => setForm({ ...form, fee: e.target.value })} /></label>
          </div>
        )}
      </Modal>
    </div>
  );
}

// ---- /admin/degrees/awards ------------------------------------------------------------------------------------------------------
export function AwardsPage() {
  useTitle('Degree awards');
  const convs = useQ(['convs'], () => degreesApi.convocations());
  const [source, setSource] = useState({ convocation_id: '', batch_id: '' });
  const [status, setStatus] = useState('');
  const [preview, setPreview] = useState<Any | null>(null);
  const [resolution, setResolution] = useState('');
  const [esign, setEsign] = useState(false);
  const [dialog, setDialog] = useState<{ kind: 'revoke' | 'reissue'; award: Any } | null>(null);
  const [text, setText] = useState('');
  const [name, setName] = useState('');
  const q = useQ(['awards', status, source], () => degreesApi.awards({ status: status || undefined, convocation_id: source.convocation_id || undefined, batch_id: source.batch_id || undefined }));
  const run = useRun();
  const body = () => ({ convocation_id: source.convocation_id || undefined, batch_id: source.batch_id || undefined, award_type: 'degree' });
  const rows: Any[] = q.data?.data ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Degree awards" description="Recommend → council approval (resolution) → issue (serial, PDF, QR, eSign) → print; revoke / reissue; statutory register." />
      <Section title="Award batch">
        <div className="flex flex-wrap items-center gap-2">
          <select className="h-9 rounded-md border bg-background px-2 text-sm" value={source.convocation_id} onChange={(e) => setSource({ convocation_id: e.target.value, batch_id: '' })}>
            <option value="">Convocation…</option>
            {(convs.data?.data ?? []).map((c: Any) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <span className="text-xs text-muted-foreground">or</span>
          <BatchPicker value={source.batch_id} onChange={(v) => setSource({ convocation_id: '', batch_id: v })} />
          <Button size="sm" variant="outline" disabled={!source.convocation_id && !source.batch_id} onClick={() => run.mutate(() => degreesApi.awardBatch(body(), true).then((r: Any) => setPreview(r.data)), { onError: fail })}>Preview</Button>
          <Button size="sm" disabled={!preview?.eligible} onClick={() => run.mutate(() => degreesApi.awardBatch(body()), { onSuccess: (r: Any) => { toast.success(`${r?.data?.created ?? 0} recommended`); setPreview(null); }, onError: fail })}>Recommend {preview?.eligible ?? ''}</Button>
        </div>
        {preview && <p className="text-sm">{preview.eligible} eligible · {preview.skipped} skipped ({[...new Set(preview.rows.filter((r: Any) => r.skip_reason).map((r: Any) => r.skip_reason))].join(', ') || '—'})</p>}
      </Section>
      <div className="flex flex-wrap items-center gap-2">
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{['recommended', 'council_approved', 'issued', 'cancelled', 'reissued'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <Input className="w-80" placeholder="Council resolution id (when governance minutes are on)" value={resolution} onChange={(e) => setResolution(e.target.value)} />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={esign} onChange={(e) => setEsign(e.target.checked)} /> eSign</label>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => degreesApi.issueBatch({ convocation_id: source.convocation_id || undefined, esign }), { onSuccess: () => toast.success('Issue batch queued'), onError: fail })}>Issue approved</Button>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => degreesApi.printBatch({ convocation_id: source.convocation_id || undefined }), { onSuccess: () => toast.success('Print batch queued (Background jobs)'), onError: fail })}>Print batch</Button>
        <Button size="sm" variant="ghost" onClick={() => degreesApi.register_csv(source.batch_id || undefined).then((b) => openBlob(b, 'degree-register.csv')).catch(fail)}><Download className="mr-1 h-4 w-4" />Register</Button>
      </div>
      <SimpleTable
        head={['Serial', 'Certificate', 'Reg. no', 'Name', 'Award', 'Class / CGPA', 'Status', '']}
        rows={rows.map((a) => [
          a.serial_no ?? '—', a.certificate_number ?? '—', a.enrollment.registration_number, a.enrollment.student_name, a.degree_name, `${a.result_class ?? '—'} / ${a.cgpa ?? '—'}`,
          <div key="s" className="space-y-1"><StatusBadge status={a.status} />{a.credential_status && <Badge variant="info">DigiLocker {a.credential_status}</Badge>}</div>,
          <div key="b" className="flex flex-wrap gap-1">
            {a.status === 'recommended' && <Button size="sm" onClick={() => run.mutate(() => degreesApi.approve(a.id, { resolution_id: resolution || undefined }), { onSuccess: () => toast.success('Approved'), onError: fail })}>Approve</Button>}
            {a.status === 'council_approved' && <Button size="sm" onClick={() => run.mutate(() => degreesApi.issue(a.id, esign), { onSuccess: () => toast.success('Issued'), onError: fail })}>Issue</Button>}
            {['issued', 'reissued', 'cancelled'].includes(a.status) && a.pdf_url && <Button size="sm" variant="ghost" onClick={() => degreesApi.certificate(a.id).then((b) => openBlob(b, `${a.certificate_number ?? a.id}.pdf`)).catch(fail)}>PDF</Button>}
            {a.status === 'issued' && <><Button size="sm" variant="outline" onClick={() => { setDialog({ kind: 'reissue', award: a }); setText(''); setName(''); }}>Reissue</Button><Button size="sm" variant="destructive" onClick={() => { setDialog({ kind: 'revoke', award: a }); setText(''); }}>Revoke</Button></>}
          </div>,
        ])}
      />
      <Modal open={!!dialog} onOpenChange={(o) => !o && setDialog(null)} title={dialog?.kind === 'revoke' ? 'Revoke award' : 'Reissue award'}
        footer={<Button variant={dialog?.kind === 'revoke' ? 'destructive' : 'default'} disabled={text.length < 5} onClick={() => run.mutate(() => (dialog!.kind === 'revoke' ? degreesApi.revoke(dialog!.award.id, text) : degreesApi.reissue(dialog!.award.id, { reason: text, corrections: name ? { holder_name: name } : undefined })), { onSuccess: () => { toast.success('Done'); setDialog(null); }, onError: fail })}>Confirm</Button>}>
        <div className="space-y-2 text-sm">
          <textarea className="min-h-20 w-full rounded-md border bg-background p-2" placeholder="Reason" value={text} onChange={(e) => setText(e.target.value)} />
          {dialog?.kind === 'reissue' && <Input placeholder="Corrected holder name (optional)" value={name} onChange={(e) => setName(e.target.value)} />}
        </div>
      </Modal>
    </div>
  );
}

// ---- /admin/degrees/provisional -------------------------------------------------------------------------------------------------
export function ProvisionalPage() {
  useTitle('Provisional certificates');
  const [batch, setBatch] = useState('');
  const q = useQ(['elig-ok', batch], () => degreesApi.eligibility({ batch_id: batch, eligible: true }), !!batch);
  const [issued, setIssued] = useState<Record<string, Any>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Provisional certificates" description="For eligible students whose degree is not issued yet; superseded once the degree is issued." />
      <BatchPicker value={batch} onChange={setBatch} />
      <SimpleTable head={['Reg. no', 'Name', 'CGPA', '']} rows={(q.data?.data ?? []).map((r: Any) => [r.enrollment.registration_number, r.enrollment.student_name, r.cgpa ?? '—',
        issued[r.enrollment.id] ? <span key="i" className="font-mono text-xs">{issued[r.enrollment.id].document_number}</span> :
          <Button key="b" size="sm" onClick={() => run.mutate(() => degreesApi.provisional(r.enrollment.id).then((x: Any) => setIssued((m) => ({ ...m, [r.enrollment.id]: x.data }))), { onSuccess: () => toast.success('Issued'), onError: fail })}>Issue</Button>])} />
    </div>
  );
}

// ---- /admin/degrees/credentials -------------------------------------------------------------------------------------------------
export function CredentialsPage() {
  useTitle('Digital credentials');
  const [status, setStatus] = useState('');
  const [batch, setBatch] = useState('');
  const q = useQ(['creds', status], () => degreesApi.credentials({ status: status || undefined }));
  const abc = useQ(['abc'], () => degreesApi.abcLedger({}));
  const run = useRun();
  const rows: Any[] = q.data?.data ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Digital credentials" description="DigiLocker / NAD pushes with retries, and the ABC credit ledger (revoked / re-pushed on new result versions)." />
      <Section title="Push" action={<div className="flex gap-2"><BatchPicker value={batch} onChange={setBatch} />
        <Button size="sm" onClick={() => run.mutate(() => degreesApi.pushCredentials({ entity_type: 'degree', channel: 'digilocker', batch_id: batch || undefined }), { onSuccess: () => toast.success('Push queued'), onError: fail })}>Push degrees</Button>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => degreesApi.abcPush({}), { onSuccess: () => toast.success('ABC push queued'), onError: fail })}>Push ABC</Button></div>}>
        <div className="flex flex-wrap gap-2 text-sm">
          {['pending', 'pushed', 'acknowledged', 'failed', 'revoked'].map((s) => <Badge key={s} variant={s === 'failed' ? 'destructive' : s === 'acknowledged' ? 'success' : 'outline'}>{s}: {rows.filter((r) => r.status === s).length}</Badge>)}
          <select className="h-8 rounded-md border bg-background px-2" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['pending', 'pushed', 'acknowledged', 'failed', 'revoked'].map((s) => <option key={s}>{s}</option>)}</select>
        </div>
        <SimpleTable head={['Holder', 'Type', 'Channel', 'Status', 'Attempts', 'Ack ref', '']} rows={rows.map((c) => [c.holder ?? '—', c.entity_type, c.channel, <StatusBadge key="s" status={c.status} />, c.attempts, c.ack_ref ?? '—',
          c.status === 'failed' ? <Button key="r" size="sm" variant="outline" onClick={() => run.mutate(() => degreesApi.retryCredential(c.id), { onSuccess: () => toast.success('Retried'), onError: fail })}>Retry</Button> : null])} />
      </Section>
      <Section title="ABC credit ledger">
        <SimpleTable head={['APAAR', 'Course', 'Credits', 'Grade', 'Year', 'Status', 'Batch', '']} rows={(abc.data?.data ?? []).slice(0, 300).map((r: Any) => [r.apaar_id ?? <Badge key="n" variant="warning">no APAAR</Badge>, `${r.course_code} ${r.course_title}`, r.credits, r.letter_grade ?? '—', r.academic_year ?? '—', <StatusBadge key="s" status={r.status} />, r.push_batch_id?.slice(0, 8) ?? '—',
          r.status === 'failed' ? <Button key="r" size="sm" variant="outline" onClick={() => run.mutate(() => degreesApi.abcRetry(r.id), { onError: fail })}>Retry</Button> : null])} />
      </Section>
    </div>
  );
}

// ---- /admin/degrees/stats -------------------------------------------------------------------------------------------------------
export function GraduationStatsPage() {
  useTitle('Graduation statistics');
  const [batch, setBatch] = useState('');
  const q = useQ(['stats', batch], () => degreesApi.stats({ batch_id: batch || undefined }));
  const s = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Graduation statistics" description="GPH (graduated on time ÷ admitted), GPHD and median CGPA — inputs to IQAC / NIRF metrics." />
      <BatchPicker value={batch} onChange={setBatch} />
      {s && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            {[['GPH', s.gph !== null ? `${s.gph}%` : '—'], ['Graduated', `${s.graduated} / ${s.admitted}`], ['On time', s.on_time_pct !== null ? `${s.on_time_pct}%` : '—'], ['Median CGPA', s.median_cgpa ?? '—'], ['PhD awarded', s.gphd]].map(([k, v]) => (
              <Card key={String(k)}><CardContent className="p-4"><p className="text-xs text-muted-foreground">{k}</p><p className="text-xl font-semibold">{String(v)}</p></CardContent></Card>
            ))}
          </div>
          <SimpleTable head={['Programme', 'Admitted', 'Graduated', 'On time', 'GPH %']} rows={s.by_program.map((p: Any) => [p.program, p.admitted, p.graduated, p.on_time, p.gph ?? '—'])} />
        </>
      )}
    </div>
  );
}

// ---- /student/degree ------------------------------------------------------------------------------------------------------------
export function StudentDegreePage() {
  useTitle('My degree');
  const elig = useQ(['me-elig'], () => degreesApi.eligibilityMe());
  const convs = useQ(['convs-open'], () => degreesApi.convocations().catch(() => ({ data: [] }) as Any));
  const mine = useQ(['me-convs'], () => degreesApi.myConvocations());
  const awards = useQ(['me-awards'], () => degreesApi.myDegrees());
  const prov = useQ(['me-prov'], () => degreesApi.myProvisional().catch(() => ({ data: [] }) as Any));
  const creds = useQ(['me-creds'], () => degreesApi.myCredentials().catch(() => ({ data: [] }) as Any));
  const abc = useQ(['me-abc'], () => degreesApi.abcMe().catch(() => ({ data: [] }) as Any));
  const [reg, setReg] = useState<Any | null>(null);
  const run = useRun();
  const c = (elig.data?.data ?? [])[0];
  const open = (convs.data?.data ?? []).filter((x: Any) => x.status === 'registration_open');
  const registered = new Set((mine.data?.data ?? []).map((r: Any) => r.convocation_id));
  return (
    <div className="space-y-4">
      <PageHeader title="My degree" description="Eligibility, convocation, certificates and digital credentials." />
      <Section title="Eligibility">
        {c ? (
          <div className="space-y-2 text-sm">
            <p>Credits {c.credits_earned} / {c.credits_required} · CGPA {c.cgpa ?? '—'} · backlogs {c.backlog_count ?? 0}</p>
            <ReasonChips reasons={c.reasons} />
            {c.reasons.map((r: string) => FIX[r.split(':')[0]] && <p key={r} className="text-xs text-muted-foreground">• {FIX[r.split(':')[0]]}</p>)}
          </div>
        ) : <p className="text-sm text-muted-foreground">Not checked yet.</p>}
      </Section>
      <Section title="Convocation">
        {open.filter((x: Any) => !registered.has(x.id)).map((x: Any) => (
          <div key={x.id} className="flex items-center justify-between rounded border p-2 text-sm">
            <span>{x.name} · {x.held_on ?? 'date tbc'} · fee {rupees(x.fee_paise)} · register by {x.registration_deadline ?? '—'}</span>
            <Button size="sm" onClick={() => setReg({ convocation: x, mode: 'in_person', gown_size: 'M', guests: 1 })}>Register</Button>
          </div>
        ))}
        <SimpleTable head={['Convocation', 'Mode', 'Gown', 'Fee', 'Status', 'Invitation QR']} rows={(mine.data?.data ?? []).map((r: Any) => [r.convocation, r.mode, r.gown_size ?? '—', r.fee_status ?? '—', <StatusBadge key="s" status={r.status} />, r.attendance_token ? <code key="q" className="text-[10px]">{r.attendance_token}</code> : '—'])} empty="Not registered." />
      </Section>
      <Section title="Certificates">
        <SimpleTable head={['Award', 'Certificate', 'Date', 'Status', 'Credential', '']} rows={(awards.data?.data ?? []).map((a: Any) => [a.degree_name, a.certificate_number ?? '—', a.date_of_award ?? '—', <StatusBadge key="s" status={a.status} />, a.credential_status ?? '—',
          a.pdf_url && a.status === 'issued' ? <Button key="d" size="sm" variant="outline" onClick={() => degreesApi.certificate(a.id).then((b) => openBlob(b, `${a.certificate_number}.pdf`)).catch(fail)}>Download</Button> : null])} empty="No awards yet." />
        {(prov.data?.data ?? []).map((p: Any) => <p key={p.document_number} className="text-sm">Provisional certificate {p.document_number} {p.superseded && <Badge variant="secondary">superseded</Badge>}</p>)}
      </Section>
      <Section title="Digital credentials & ABC">
        <SimpleTable head={['Document', 'Channel', 'Status']} rows={(creds.data?.data ?? []).map((x: Any) => [x.entity_type, x.channel, <StatusBadge key="s" status={x.status} />])} empty="Nothing pushed yet (needs an APAAR id)." />
        <p className="text-xs text-muted-foreground">ABC: {(abc.data?.data ?? []).filter((r: Any) => r.status === 'acknowledged').length} credit rows acknowledged of {(abc.data?.data ?? []).length}.</p>
      </Section>
      <Modal open={!!reg} onOpenChange={(o) => !o && setReg(null)} title={`Register — ${reg?.convocation?.name ?? ''}`}
        footer={<Button onClick={() => run.mutate(() => degreesApi.register(reg.convocation.id, { mode: reg.mode, gown_size: reg.mode === 'in_person' ? reg.gown_size : undefined, guests: reg.mode === 'in_person' ? Number(reg.guests) : undefined }), { onSuccess: () => { toast.success('Registered — pay the fee under Fees'); setReg(null); }, onError: fail })}>Register</Button>}>
        {reg && (
          <div className="space-y-2 text-sm">
            <select className="h-9 w-full rounded-md border bg-background px-2" value={reg.mode} onChange={(e) => setReg({ ...reg, mode: e.target.value })}><option value="in_person">In person</option><option value="absentia">In absentia</option></select>
            {reg.mode === 'in_person' && <>
              <select className="h-9 w-full rounded-md border bg-background px-2" value={reg.gown_size} onChange={(e) => setReg({ ...reg, gown_size: e.target.value })}>{['XS', 'S', 'M', 'L', 'XL', 'XXL'].map((g) => <option key={g}>{g}</option>)}</select>
              <Input type="number" min={0} max={4} value={reg.guests} onChange={(e) => setReg({ ...reg, guests: e.target.value })} />
            </>}
          </div>
        )}
      </Modal>
    </div>
  );
}

// ---- /verify/bulk (public, employers) ------------------------------------------------------------------------------------------
export function BulkVerifyPage() {
  useTitle('Bulk verification');
  const [tokens, setTokens] = useState('');
  const [out, setOut] = useState<Any[]>([]);
  return (
    <div className="flex min-h-screen items-start justify-center bg-background p-4">
      <Card className="w-full max-w-3xl"><CardContent className="space-y-3 pt-6">
        <h1 className="text-lg font-semibold">Verify certificates in bulk</h1>
        <p className="text-sm text-muted-foreground">Paste up to 50 verification codes (one per line) from the QR on degree certificates, provisional certificates, grade cards or transcripts.</p>
        <textarea className="min-h-32 w-full rounded-md border bg-background p-2 font-mono text-xs" value={tokens} onChange={(e) => setTokens(e.target.value)} />
        <Button disabled={!tokens.trim()} onClick={() => degreesApi.bulkVerify({ tokens: tokens.split(/\s+/).filter(Boolean).slice(0, 50) }).then((r: Any) => setOut(r.data)).catch(fail)}>Verify</Button>
        <SimpleTable head={['Code', 'Valid', 'Holder', 'Details']} rows={out.map((r) => [<code key="c" className="text-[10px]">{String(r.token).slice(0, 16)}…</code>, r.valid ? <Badge key="v" variant="success">valid</Badge> : <Badge key="v" variant="destructive">{r.revoked ? 'revoked' : 'not valid'}</Badge>, r.holder_masked ?? r.holder_name ?? '—', r.award?.degree ?? r.award?.programme ?? r.document_type ?? r.message ?? '—'])} />
      </CardContent></Card>
    </div>
  );
}
