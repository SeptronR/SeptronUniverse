import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { affApi as aa } from '../api';

// Phase 34 web screens (Prompts/34 §34.9). College scope, inspector ownership, the decision / resolution rule, intake
// gates, submission locks and result gating are enforced by the API; these screens only present them.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const done = (m: string) => () => toast.success(m);
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['aff', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['aff'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const data = (r: Any) => r?.data;
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const rupees = (p?: number | null) => (p === null || p === undefined ? '—' : `₹${(p / 100).toLocaleString('en-IN')}`);
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[90px] w-full rounded-md border bg-background p-2 text-sm';
const openBlob = (b: Blob) => window.open(URL.createObjectURL(b), '_blank');
const APP_TYPES = ['new', 'renewal', 'extension', 'intake_increase', 'program_addition', 'program_closure', 'autonomy'];
const SUB_TYPES = ['student_registrations', 'course_registrations', 'cia_marks', 'attendance_eligibility', 'practical_marks', 'exam_registrations', 'internal_faculty_list'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function Err({ q }: { q: Any }) {
  return q.isError ? <p className="text-sm text-destructive">{getApiError(q.error)}</p> : null;
}
function Chip({ tone, label }: { tone: 'ok' | 'warn' | 'bad'; label: string }) {
  const cls = tone === 'ok' ? 'bg-emerald-100 text-emerald-800' : tone === 'warn' ? 'bg-amber-100 text-amber-800' : 'bg-red-100 text-red-800';
  return <span className={`rounded px-1.5 py-0.5 text-xs ${cls}`}>{label}</span>;
}
const validityChip = (v: string) => <Chip key="v" tone={v === 'valid' ? 'ok' : v === 'expiring' ? 'warn' : 'bad'} label={v} />;
const subChip = (s?: string) => (s ? <Chip key={s} tone={s === 'locked' || s === 'accepted' ? 'ok' : s === 'returned' ? 'bad' : 'warn'} label={s} /> : <span key="none" className="text-xs text-muted-foreground">—</span>);
const kv = (o: Record<string, Any> | undefined) => Object.entries(o ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—';

// ---- university: portfolio ---------------------------------------------------------------------------------------------
export function PortfolioPage() {
  useTitle('Affiliation portfolio');
  const q = useQ(['portfolio'], () => aa.portfolio());
  const p = data(q.data) ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Affiliation portfolio" description="Colleges by type, applications, inspections, deficiencies, dues, submission compliance, results gating and expiring approvals." />
      <Err q={q} />
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Affiliated" value={p.colleges_by_type?.affiliated ?? 0} />
        <Stat label="Autonomous" value={p.colleges_by_type?.autonomous ?? 0} />
        <Stat label="Constituent" value={p.colleges_by_type?.constituent ?? 0} />
        <Stat label="Sanctioned intake" value={p.sanctioned_intake} />
        <Stat label="Inspections due" value={p.inspections_due} />
        <Stat label="Deficiencies open" value={p.deficiencies_open} />
        <Stat label="Dues outstanding" value={rupees(p.dues_outstanding_paise)} />
        <Stat label="Submissions accepted" value={p.submissions_compliance_pct === null || p.submissions_compliance_pct === undefined ? '—' : `${p.submissions_compliance_pct}%`} />
      </div>
      <Section title="Applications"><p className="text-sm">{kv(p.applications_by_status)}</p><p className="text-xs text-muted-foreground">{kv(p.applications_by_type)}</p></Section>
      <Section title="Results gating (central sessions)">
        <SimpleTable head={['Session', 'Ready', 'Gated', 'N/A', '']} rows={(p.results_gating ?? []).map((g: Any) => [g.session, g.ready, g.gated, g.not_applicable, <Link key="l" className="text-primary underline" to={`/university/exams/sessions/${g.session_id}/colleges`}>Colleges</Link>])} />
      </Section>
      <Section title={`Dues by college · expiring approvals ${p.expiring_approvals ?? 0}`}>
        <SimpleTable head={['College', 'Billed', 'Paid', 'Outstanding', 'Overdue']} rows={(p.dues_by_college ?? []).map((r: Any) => [r.college_code, rupees(r.billed_paise), rupees(r.paid_paise), rupees(r.outstanding_paise), rupees(r.overdue_paise)])} />
      </Section>
    </div>
  );
}

// ---- university: colleges ---------------------------------------------------------------------------------------------
export function CollegesPage() {
  useTitle('Affiliated colleges');
  const [type, setType] = useState('');
  const q = useQ(['colleges', type], () => aa.colleges({ type: type || undefined }));
  return (
    <div className="space-y-4">
      <PageHeader title="College registry" description="Affiliation numbers, type, approvals, open applications, dues and compliance score." />
      <select className={sel} value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{['affiliated', 'autonomous', 'constituent', 'campus', 'study_centre'].map((t) => <option key={t}>{t}</option>)}</select>
      <Err q={q} />
      <SimpleTable head={['Code', 'College', 'Type', 'Affiliation no.', 'Since', 'Programmes', 'Intake', 'Open apps', 'Dues', 'Score']} rows={list(q.data).map((c: Any) => [<Link key="c" className="text-primary underline" to={`/university/affiliation/colleges/${c.college_id}`}>{c.code}</Link>, c.name, c.college_type, c.affiliation_number ?? '—', day(c.affiliated_since), c.programmes, c.sanctioned_intake, c.open_applications, rupees(c.dues_paise), <Chip key="s" tone={c.compliance_score >= 80 ? 'ok' : c.compliance_score >= 60 ? 'warn' : 'bad'} label={String(c.compliance_score)} />])} />
    </div>
  );
}

export function CollegeDetailPage({ mine = false }: { mine?: boolean }) {
  const { id = '' } = useParams();
  useTitle('College affiliation');
  const q = useQ(['college', id, mine], () => (mine ? aa.myDashboard() : aa.collegeDashboard(id)));
  const run = useRun();
  const d = data(q.data);
  const [f, setF] = useState<Any>({ college_type: '', reason: '' });
  const [doc, setDoc] = useState<Any>({ key: '', title: '', file_url: '', valid_to: '' });
  if (!d) return <div className="space-y-4"><PageHeader title="College" /><Err q={q} /></div>;
  const pr = d.profile;
  return (
    <div className="space-y-4">
      <PageHeader title={`${pr.code} · ${pr.name}`} description={`${pr.college_type} · affiliation ${pr.affiliation_number ?? '—'} since ${day(pr.affiliated_since)} · AISHE ${pr.aishe_code ?? '—'} · AICTE ${pr.aicte_pid ?? '—'}`} />
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Compliance score" value={d.compliance_score} />
        <Stat label="Programmes approved" value={pr.approvals.programmes} />
        <Stat label="Sanctioned intake" value={pr.approvals.sanctioned_intake} />
        <Stat label="Dues" value={rupees(d.dues?.outstanding_paise ?? 0)} />
      </div>
      {!mine && (
        <Section title="Type transition">
          <div className="flex flex-wrap gap-2">
            <select className={sel} value={f.college_type} onChange={(e) => setF({ ...f, college_type: e.target.value })}><option value="">New type…</option>{['affiliated', 'autonomous', 'constituent'].map((t) => <option key={t}>{t}</option>)}</select>
            <Input className="w-80" placeholder="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
            <Button size="sm" disabled={!f.college_type} onClick={() => run.mutate(() => aa.updateProfile(pr.college_id, { college_type: f.college_type, reason: f.reason }), { onSuccess: done('Type changed; programme exam authority updated'), onError: fail })}>Apply</Button>
          </div>
        </Section>
      )}
      <Section title="Documents vault">
        <SimpleTable head={['Document', 'Valid to', '']} rows={(pr.documents ?? []).map((x: Any) => [<a key="a" className="text-primary underline" href={x.file_url} target="_blank" rel="noreferrer">{x.title}</a>, day(x.valid_to), x.expired ? <Chip key="e" tone="bad" label="expired" /> : <Chip key="e" tone="ok" label="valid" />])} />
        <div className="flex flex-wrap gap-2">
          <Input className="w-32" placeholder="Key" value={doc.key} onChange={(e) => setDoc({ ...doc, key: e.target.value })} />
          <Input className="w-56" placeholder="Title" value={doc.title} onChange={(e) => setDoc({ ...doc, title: e.target.value })} />
          <Input className="w-72" placeholder="File URL" value={doc.file_url} onChange={(e) => setDoc({ ...doc, file_url: e.target.value })} />
          <Input type="date" className="w-40" value={doc.valid_to} onChange={(e) => setDoc({ ...doc, valid_to: e.target.value })} />
          <Button size="sm" disabled={!doc.key || !doc.file_url} onClick={() => run.mutate(() => aa.addDocument(pr.college_id, { ...doc, valid_to: doc.valid_to || null }), { onSuccess: done('Saved'), onError: fail })}>Upload</Button>
        </div>
      </Section>
      <Section title="Programme approvals"><ApprovalTable rows={d.approvals ?? []} /></Section>
      <Section title="Applications"><ApplicationsTable rows={d.applications ?? []} college={mine} /></Section>
      <Section title="Submissions by term"><SimpleTable head={['Term', ...SUB_TYPES]} rows={Object.entries(d.submissions_by_term ?? {}).map(([t, m]: [string, Any]) => [mine ? <Link key="t" className="text-primary underline" to={`/college/submissions/${t}`}>{t.slice(0, 8)}</Link> : t.slice(0, 8), ...SUB_TYPES.map((s) => subChip(m[s]))])} /></Section>
      <Section title="Results release"><SimpleTable head={['Session', 'Status', 'Published', 'Gating', 'Missing']} rows={(d.results_release ?? []).map((r: Any) => [r.session, r.session_status, r.published ? 'yes' : 'no', r.gating ?? '—', (r.missing ?? []).join(', ') || '—'])} /></Section>
    </div>
  );
}

function ApprovalTable({ rows }: { rows: Any[] }) {
  return <SimpleTable head={['College', 'Programme', 'Year', 'Intake', 'Lateral', 'Admitted', 'Status', 'Valid to', 'Validity', 'Order']} rows={rows.map((a: Any) => [a.college_code, `${a.program_code} · ${a.program_name ?? ''}`, a.academic_year, a.sanctioned_intake, a.lateral_intake, a.admitted, <StatusBadge key="s" status={a.approval_status} />, day(a.valid_to), validityChip(a.validity), a.order_no ?? '—'])} />;
}
function ApplicationsTable({ rows, college = false }: { rows: Any[]; college?: boolean }) {
  return <SimpleTable head={['Number', 'College', 'Type', 'Year', 'Status', 'Fee', 'Order']} rows={rows.map((a: Any) => [<Link key="n" className="text-primary underline" to={college ? `/college/affiliation/applications/${a.id}` : `/university/affiliation/applications/${a.id}`}>{a.number ?? a.id.slice(0, 8)}</Link>, a.college_code, a.application_type, a.academic_year, <StatusBadge key="s" status={a.status} />, a.fee_status ?? '—', a.order_no ?? '—'])} />;
}

// ---- university: applications ------------------------------------------------------------------------------------------
export function ApplicationsPage() {
  useTitle('Affiliation applications');
  const [scope, setScope] = useState<string>('all');
  const [status, setStatus] = useState('');
  const [type, setType] = useState('');
  const q = useQ(['apps', scope, status, type], () => aa.applications({ scope, status: status || undefined, type: type || undefined }));
  return (
    <div className="space-y-4">
      <PageHeader title="Affiliation applications" description="Queue by status and type: scrutiny, inspections, deficiencies and decisions." />
      <ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />
      <div className="flex gap-2">
        <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['draft', 'submitted', 'fee_paid', 'scrutiny', 'inspection_scheduled', 'inspected', 'compliance_pending', 'approved', 'conditional', 'rejected', 'withdrawn'].map((s) => <option key={s}>{s}</option>)}</select>
        <select className={sel} value={type} onChange={(e) => setType(e.target.value)}><option value="">Any type</option>{APP_TYPES.map((s) => <option key={s}>{s}</option>)}</select>
      </div>
      <Err q={q} />
      <ApplicationsTable rows={list(q.data)} />
    </div>
  );
}

export function ApplicationPage({ college = false }: { college?: boolean }) {
  const { id = '' } = useParams();
  useTitle('Affiliation application');
  const q = useQ(['app', id], () => aa.application(id));
  const fee = useQ(['fee', id], () => aa.feePreview(id));
  const run = useRun();
  const a = data(q.data);
  const [remarks, setRemarks] = useState('');
  const [missing, setMissing] = useState('');
  const [insp, setInsp] = useState<Any>({ staff_ids: '', committee_id: '', inspection_on: '', mode: 'physical' });
  const [report, setReport] = useState<Any>({ report_url: '', findings: '', recommendation: 'approve' });
  const [dec, setDec] = useState<Any>({ decision: 'approved', conditions: '', resolution_id: '', programs: '' });
  const [docs, setDocs] = useState<Any>({});
  const [resp, setResp] = useState<Any>({});
  if (!a) return <div className="space-y-4"><PageHeader title="Application" /><Err q={q} /></div>;
  const act = (fn: () => Promise<unknown>, msg: string) => run.mutate(fn, { onSuccess: done(msg), onError: fail });
  const findings = () => report.findings.split('\n').filter(Boolean).map((l: string) => { const [area, observation, severity] = l.split('|').map((x) => x.trim()); return { area, observation: observation || area, is_deficiency: !!severity, severity: severity || 'minor' }; });
  const programs = () => (dec.programs ? dec.programs.split('\n').filter(Boolean).map((l: string) => { const [pid, intake, lateral, status, validTo] = l.split('|').map((x) => x.trim()); return { [pid.length > 30 ? 'program_id' : 'new_code']: pid, sanctioned_intake: Number(intake), lateral_intake: Number(lateral || 0), approval_status: status || 'provisional', valid_to: validTo || undefined }; }) : (a.programs ?? []).filter((p: Any) => p.program_id).map((p: Any) => ({ program_id: p.program_id, sanctioned_intake: p.requested_intake ?? p.current_intake ?? 0, lateral_intake: p.lateral_intake ?? 0, approval_status: 'provisional' })));
  return (
    <div className="space-y-4">
      <PageHeader title={`${a.number ?? 'Application'} · ${a.application_type}`} description={`${a.college_code} · ${a.college_name} · ${a.academic_year} · ${a.status}${a.workflow_state ? ` · workflow ${a.workflow_state}` : ''}`} />
      <Err q={q} />
      <Section title="Programmes"><SimpleTable head={['Programme', 'Current', 'Requested', 'Lateral']} rows={(a.programs ?? []).map((p: Any) => [`${p.program_code ?? ''} ${p.program_name ?? ''}`, p.current_intake ?? '—', p.requested_intake ?? '—', p.lateral_intake])} /></Section>
      <Section title={`Checklist ${a.checklist_complete ? '(complete)' : `(missing ${a.missing_documents.length})`}`}>
        <div className="flex flex-wrap gap-2">{a.missing_documents.map((k: string) => <Chip key={k} tone="bad" label={k} />)}</div>
        {a.status === 'draft' && (
          <div className="space-y-2">
            {a.missing_documents.map((k: string) => <Input key={k} placeholder={`${k} file URL`} value={docs[k] ?? ''} onChange={(e) => setDocs({ ...docs, [k]: e.target.value })} />)}
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => act(() => aa.updateApplication(id, { documents: docs }), 'Documents saved')}>Save documents</Button>
              <Button size="sm" onClick={() => act(() => aa.applicationAction(id, 'submit', remarks || undefined), 'Submitted')}>Submit</Button>
            </div>
          </div>
        )}
      </Section>
      <Section title="Fees">
        <SimpleTable head={['Fee', 'Units', 'Rate', 'Amount']} rows={(data(fee.data)?.lines ?? []).map((l: Any) => [l.label, l.units, rupees(l.rate_paise), rupees(l.amount_paise)])} />
        <p className="text-sm">Total {rupees(data(fee.data)?.total_paise)} · invoice {a.fee_status ?? 'not raised'}{college && a.fee_invoice_id ? <> · <Link className="text-primary underline" to="/fees/me">Pay</Link></> : null}</p>
      </Section>
      {!college && (a.status === 'fee_paid' || a.status === 'submitted') && (
        <Section title="Scrutiny">
          <Input placeholder="Missing documents (comma separated, for a return)" value={missing} onChange={(e) => setMissing(e.target.value)} />
          <textarea className={area} placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
          <div className="flex gap-2">
            <Button size="sm" onClick={() => act(() => aa.scrutiny(id, { action: 'proceed', remarks }), 'Scrutiny cleared')}>Proceed</Button>
            <Button size="sm" variant="outline" onClick={() => act(() => aa.scrutiny(id, { action: 'return', remarks, missing_documents: missing.split(',').map((x) => x.trim()).filter(Boolean) }), 'Returned to the college')}>Return</Button>
          </div>
        </Section>
      )}
      {!college && (a.status === 'scrutiny' || a.status === 'inspected') && (
        <Section title="Schedule inspection">
          <div className="flex flex-wrap gap-2">
            <Input className="w-96" placeholder="Committee staff ids (comma separated)" value={insp.staff_ids} onChange={(e) => setInsp({ ...insp, staff_ids: e.target.value })} />
            <Input className="w-72" placeholder="or Phase 33 committee id" value={insp.committee_id} onChange={(e) => setInsp({ ...insp, committee_id: e.target.value })} />
            <Input type="date" className="w-40" value={insp.inspection_on} onChange={(e) => setInsp({ ...insp, inspection_on: e.target.value })} />
            <select className={sel} value={insp.mode} onChange={(e) => setInsp({ ...insp, mode: e.target.value })}>{['physical', 'virtual', 'hybrid'].map((m) => <option key={m}>{m}</option>)}</select>
            <Button size="sm" disabled={!insp.inspection_on} onClick={() => act(() => aa.scheduleInspection(id, { committee: { staff_ids: insp.staff_ids.split(',').map((x: string) => x.trim()).filter(Boolean), committee_id: insp.committee_id || undefined }, inspection_on: insp.inspection_on, mode: insp.mode }), 'Inspection scheduled')}>Schedule</Button>
          </div>
        </Section>
      )}
      {a.status === 'inspection_scheduled' && <InspectionReportForm id={id} report={report} setReport={setReport} onSubmit={() => act(() => aa.inspectionReport(id, { report_url: report.report_url, findings: findings(), recommendation: report.recommendation }), 'Report uploaded')} />}
      <Section title={`Deficiencies (${(a.deficiencies ?? []).filter((x: Any) => x.status !== 'closed').length} open)`} action={!college && a.status === 'inspected' ? <Button size="sm" variant="outline" onClick={() => act(() => aa.reinspect(id, {}), 'Re-inspection scheduled')}>Re-inspect</Button> : undefined}>
        <SimpleTable head={['Id', 'Area', 'Observation', 'Severity', 'Due', 'Status', 'Response', '']} rows={(a.deficiencies ?? []).map((x: Any) => [x.id, x.area, x.observation, <Chip key="sv" tone={x.severity === 'critical' ? 'bad' : x.severity === 'major' ? 'warn' : 'ok'} label={x.severity} />, day(x.due_on), x.status, x.response_text ?? '—',
          college ? (x.status !== 'closed' && <span key="r" className="flex gap-1"><Input className="w-48" placeholder="Response" value={resp[x.id] ?? ''} onChange={(e) => setResp({ ...resp, [x.id]: e.target.value })} /><Button size="sm" onClick={() => act(() => aa.respondDeficiency(id, x.id, { response_text: resp[x.id] ?? '' }), 'Response sent')}>Respond</Button></span>)
            : (x.status !== 'closed' && <span key="c" className="flex gap-1"><Button size="sm" onClick={() => act(() => aa.closeDeficiency(id, x.id, { accept: true }), 'Closed')}>Close</Button><Button size="sm" variant="outline" onClick={() => act(() => aa.closeDeficiency(id, x.id, { accept: false, remarks: 'insufficient evidence' }), 'Sent back')}>Back</Button></span>)])} />
      </Section>
      {!college && ['compliance_pending', 'fee_paid', 'scrutiny'].includes(a.status) && (
        <Section title="Decision (VC)">
          <div className="flex flex-wrap gap-2">
            <select className={sel} value={dec.decision} onChange={(e) => setDec({ ...dec, decision: e.target.value })}>{['approved', 'conditional', 'rejected'].map((x) => <option key={x}>{x}</option>)}</select>
            <Input className="w-80" placeholder="Council resolution id (required with governance.minutes)" value={dec.resolution_id} onChange={(e) => setDec({ ...dec, resolution_id: e.target.value })} />
          </div>
          <textarea className={area} placeholder="Programmes: program_id or new code | intake | lateral | status | valid_to (one per line; empty = requested intakes)" value={dec.programs} onChange={(e) => setDec({ ...dec, programs: e.target.value })} />
          <textarea className={area} placeholder="Conditions (one per line)" value={dec.conditions} onChange={(e) => setDec({ ...dec, conditions: e.target.value })} />
          <Button size="sm" onClick={() => act(() => aa.decide(id, { decision: dec.decision, resolution_id: dec.resolution_id || undefined, conditions: dec.conditions.split('\n').filter(Boolean), programs: dec.decision === 'rejected' ? [] : programs() }), 'Decided — order issued')}>Decide &amp; issue order</Button>
        </Section>
      )}
      {a.decision && <Section title="Decision / order" action={<Button size="sm" variant="outline" onClick={() => aa.orderPdf(id).then(openBlob).catch(fail)}>Order PDF</Button>}><p className="text-sm">{a.decision.decision} · order {a.decision.order_no} ({day(a.decision.order_date)}){a.decision.resolution_number ? ` · resolution ${a.decision.resolution_number}` : ''}</p><ul className="list-disc pl-5 text-sm">{(a.decision.conditions ?? []).map((c: string) => <li key={c}>{c}</li>)}</ul></Section>}
      {college && !['approved', 'conditional', 'rejected', 'withdrawn'].includes(a.status) && <Button size="sm" variant="outline" onClick={() => act(() => aa.applicationAction(id, 'withdraw'), 'Withdrawn')}>Withdraw</Button>}
      <Section title="Timeline"><SimpleTable head={['When', 'Action', 'Details']} rows={(a.timeline ?? []).map((t: Any, i: number) => [day(t.at), t.action, Object.entries(t).filter(([k]) => !['at', 'action', 'by'].includes(k)).map(([k, v]) => `${k}: ${v}`).join(' · ') || String(i)])} /></Section>
    </div>
  );
}

function InspectionReportForm({ report, setReport, onSubmit }: { id: string; report: Any; setReport: (r: Any) => void; onSubmit: () => void }) {
  return (
    <Section title="Inspection report">
      <Input placeholder="Report URL" value={report.report_url} onChange={(e) => setReport({ ...report, report_url: e.target.value })} />
      <textarea className={area} placeholder="Findings: area | observation | severity (minor/major/critical — leave empty when not a deficiency), one per line" value={report.findings} onChange={(e) => setReport({ ...report, findings: e.target.value })} />
      <div className="flex gap-2">
        <select className={sel} value={report.recommendation} onChange={(e) => setReport({ ...report, recommendation: e.target.value })}>{['approve', 'conditional', 'reject', 'reinspect'].map((x) => <option key={x}>{x}</option>)}</select>
        <Button size="sm" disabled={!report.report_url} onClick={onSubmit}>Upload report</Button>
      </div>
    </Section>
  );
}

// ---- inspection committee portal ---------------------------------------------------------------------------------------
export function MyInspectionsPage() {
  useTitle('My inspections');
  const q = useQ(['myinsp'], () => aa.myInspections());
  const [open, setOpen] = useState<string>('');
  const [report, setReport] = useState<Any>({ report_url: '', findings: '', recommendation: 'approve' });
  const run = useRun();
  const findings = () => report.findings.split('\n').filter(Boolean).map((l: string) => { const [area, observation, severity] = l.split('|').map((x) => x.trim()); return { area, observation: observation || area, is_deficiency: !!severity, severity: severity || 'minor' }; });
  return (
    <div className="space-y-4">
      <PageHeader title="My inspections" description="Assigned affiliation inspections: schedule, report upload with findings and deficiencies." />
      <Err q={q} />
      <SimpleTable head={['Application', 'College', 'Type', 'On', 'Mode', 'Status', 'Report', '']} rows={list(q.data).map((r: Any) => [r.number, r.college_name, r.application_type, day(r.inspection_on), r.mode ?? '—', r.status, r.report_submitted ? 'submitted' : 'pending', r.status === 'inspection_scheduled' ? <Button key="o" size="sm" variant="outline" onClick={() => setOpen(r.application_id)}>Report</Button> : null])} />
      {open && <InspectionReportForm id={open} report={report} setReport={setReport} onSubmit={() => run.mutate(() => aa.inspectionReport(open, { report_url: report.report_url, findings: findings(), recommendation: report.recommendation }), { onSuccess: () => { toast.success('Report uploaded'); setOpen(''); }, onError: fail })} />}
    </div>
  );
}

// ---- programme approvals / fee schedules ------------------------------------------------------------------------------
export function ProgramApprovalsPage() {
  useTitle('Programme approvals');
  const [college, setCollege] = useState('');
  const [status, setStatus] = useState('');
  const [year, setYear] = useState('');
  const q = useQ(['approvals', college, status], () => aa.approvals({ college_id: college || undefined, status: status || undefined }));
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Programme approvals" description="College × programme × year with sanctioned / lateral intake, validity chips and carry-forward." />
      <div className="flex flex-wrap gap-2">
        <Input className="w-72" placeholder="College id" value={college} onChange={(e) => setCollege(e.target.value)} />
        <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['provisional', 'permanent', 'conditional', 'withdrawn'].map((s) => <option key={s}>{s}</option>)}</select>
        <Input className="w-72" placeholder="Carry forward to year id" value={year} onChange={(e) => setYear(e.target.value)} />
        <Button size="sm" variant="outline" disabled={!year} onClick={() => run.mutate(() => aa.carryForward(year), { onSuccess: done('Carried forward'), onError: fail })}>Carry forward</Button>
      </div>
      <Err q={q} />
      <ApprovalTable rows={list(q.data)} />
    </div>
  );
}

export function FeeSchedulesPage() {
  useTitle('Affiliation fee schedules');
  const q = useQ(['fees'], () => aa.feeSchedules());
  const dues = useQ(['dues'], () => aa.dues());
  const run = useRun();
  const [f, setF] = useState<Any>({ academic_year_id: '', fee_type: 'affiliation', amount_paise: '', per_unit: 'flat' });
  return (
    <div className="space-y-4">
      <PageHeader title="Fee schedules & dues" description="Affiliation, continuation, inspection, intake increase, exam processing per student, recognition." />
      <SimpleTable head={['Year', 'Fee', 'Per', 'Amount']} rows={list(q.data).map((s: Any) => [s.academic_year, s.fee_type, s.per_unit, rupees(s.amount_paise)])} />
      <div className="flex flex-wrap gap-2">
        <Input className="w-72" placeholder="Academic year id" value={f.academic_year_id} onChange={(e) => setF({ ...f, academic_year_id: e.target.value })} />
        <select className={sel} value={f.fee_type} onChange={(e) => setF({ ...f, fee_type: e.target.value })}>{['affiliation', 'continuation', 'inspection', 'intake_increase', 'exam_processing_per_student', 'recognition'].map((x) => <option key={x}>{x}</option>)}</select>
        <select className={sel} value={f.per_unit} onChange={(e) => setF({ ...f, per_unit: e.target.value })}>{['flat', 'per_program', 'per_student'].map((x) => <option key={x}>{x}</option>)}</select>
        <Input className="w-40" placeholder="Amount (paise)" value={f.amount_paise} onChange={(e) => setF({ ...f, amount_paise: e.target.value })} />
        <Button size="sm" onClick={() => run.mutate(() => aa.createFeeSchedule({ ...f, amount_paise: Number(f.amount_paise) }), { onSuccess: done('Added'), onError: fail })}>Add</Button>
      </div>
      <Section title="Dues by college"><SimpleTable head={['College', 'Invoices', 'Outstanding', 'Overdue', 'Exam processing (est.)']} rows={list(dues.data).map((r: Any) => [r.college_code, r.invoices, rupees(r.outstanding_paise), rupees(r.overdue_paise), rupees(r.exam_processing_estimate_paise)])} /></Section>
    </div>
  );
}

// ---- submissions ------------------------------------------------------------------------------------------------------
export function SubmissionsPage() {
  useTitle('College data submissions');
  const [term, setTerm] = useState('');
  const [scope, setScope] = useState<string>('all');
  const q = useQ(['subs', term, scope], () => aa.submissions({ term_id: term || undefined, scope }), true);
  const comp = useQ(['comp', term], () => aa.compliance({ term_id: term }), !!term);
  const rows = list(q.data);
  const byCollege: Record<string, Any> = {};
  rows.forEach((s: Any) => { (byCollege[s.college_code] ??= {})[s.submission_type] = s; });
  return (
    <div className="space-y-4">
      <PageHeader title="Data submissions" description="College × type matrix for the term: verify / return / accept / lock, versions and compliance." />
      <div className="flex gap-2"><Input className="w-80" placeholder="Term id" value={term} onChange={(e) => setTerm(e.target.value)} /><ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} /></div>
      <Err q={q} />
      <SimpleTable head={['College', ...SUB_TYPES]} rows={Object.entries(byCollege).map(([c, m]) => [c, ...SUB_TYPES.map((t) => (m[t] ? <Link key={t} to={`/university/affiliation/submissions/${m[t].id}`}>{subChip(m[t].status)}</Link> : subChip()))])} />
      {term && <Section title="Compliance"><SimpleTable head={['College', 'On time', 'Returns', 'Accepted', 'Pending']} rows={list(comp.data).map((r: Any) => [r.college_code, r.on_time_pct === null ? '—' : `${r.on_time_pct}%`, r.returns, r.accepted, r.pending])} /></Section>}
    </div>
  );
}

export function SubmissionPage({ college = false }: { college?: boolean }) {
  const { id = '' } = useParams();
  useTitle('Submission');
  const q = useQ(['sub', id], () => aa.submission(id));
  const run = useRun();
  const [remarks, setRemarks] = useState('');
  const [file, setFile] = useState('');
  const s = data(q.data);
  if (!s) return <div className="space-y-4"><PageHeader title="Submission" /><Err q={q} /></div>;
  const act = (action: string) => run.mutate(() => aa.submissionAction(id, action, remarks || undefined), { onSuccess: done(action), onError: fail });
  const v = s.validation;
  return (
    <div className="space-y-4">
      <PageHeader title={`${s.college_code} · ${s.submission_type}`} description={`v${s.version} · ${s.source} · ${s.record_count ?? 0} records · due ${day(s.due_on)}${s.late ? ' (late)' : ''} · ${s.status}`} />
      <div className="flex flex-wrap gap-2">
        {['draft', 'returned'].includes(s.status) && <>
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.extract(id), { onSuccess: done('Extracted'), onError: fail })}>Extract from system</Button>
          <Input className="w-80" placeholder="CSV / XLSX URL" value={file} onChange={(e) => setFile(e.target.value)} />
          <Button size="sm" variant="outline" disabled={!file} onClick={() => run.mutate(() => aa.importFile(id, { file_url: file }), { onSuccess: done('Imported'), onError: fail })}>Import</Button>
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.validate(id), { onSuccess: done('Validated'), onError: fail })}>Validate</Button>
          <Button size="sm" onClick={() => act('submit')}>Submit</Button>
        </>}
        {!college && s.status === 'submitted' && <Button size="sm" onClick={() => act('verify')}>Verify</Button>}
        {!college && ['submitted', 'verified'].includes(s.status) && <Button size="sm" variant="outline" onClick={() => act('return')}>Return</Button>}
        {!college && s.status === 'verified' && <Button size="sm" onClick={() => act('accept')}>Accept</Button>}
        {!college && s.status === 'accepted' && <Button size="sm" onClick={() => act('lock')}>Lock</Button>}
        {!college && s.status === 'locked' && <Button size="sm" variant="outline" onClick={() => act('unlock')}>Unlock (COE)</Button>}
      </div>
      <Input placeholder="Remarks / reason" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <Section title={`Validation ${v ? `· ${v.errors.length} errors · ${v.warnings.length} warnings` : '(not run)'}`}>
        <SimpleTable head={['Level', 'Code', 'Message', 'Row / ref']} rows={[...(v?.errors ?? []).map((e: Any) => ['error', e.code, e.message, e.row ?? e.ref ?? '—']), ...(v?.warnings ?? []).map((e: Any) => ['warning', e.code, e.message, e.row ?? e.ref ?? '—'])]} />
      </Section>
      {s.remarks && <p className="text-sm">Remarks: {s.remarks}</p>}
      <Section title="Versions"><SimpleTable head={['Version', 'Records', 'Submitted', 'Returned remarks']} rows={(s.versions ?? []).map((x: Any) => [x.version, x.record_count, day(x.submitted_at), x.returned_remarks ?? '—'])} /></Section>
      <Section title="Timeline"><SimpleTable head={['When', 'Action', 'Status']} rows={(s.timeline ?? []).map((t: Any) => [day(t.at), t.action, t.status ?? '—'])} /></Section>
    </div>
  );
}

export function SessionCollegesPage() {
  const { id = '' } = useParams();
  useTitle('Session colleges');
  const q = useQ(['gating', id], () => aa.collegeStatus(id));
  return (
    <div className="space-y-4">
      <PageHeader title="Result gating by college" description="Colleges whose required submissions are not accepted / locked are skipped by central result runs." />
      <Err q={q} />
      <SimpleTable head={['College', 'Status', 'Missing', 'Registrations', 'Types']} rows={list(q.data).map((r: Any) => [r.college_code, <Chip key="s" tone={r.status === 'ready' ? 'ok' : r.status === 'gated' ? 'bad' : 'warn'} label={r.status} />, (r.missing ?? []).join(', ') || '—', r.registrations, kv(r.by_type)])} />
    </div>
  );
}

// ---- exam centres -----------------------------------------------------------------------------------------------------
export function ExamCentresPage() {
  useTitle('Exam centres');
  const [session, setSession] = useState('');
  const q = useQ(['centres', session], () => aa.centres({ exam_session_id: session || undefined }));
  const run = useRun();
  const [strategy, setStrategy] = useState('nearest');
  const [f, setF] = useState<Any>({ college_id: '', centre_code: '', capacity: '', chief_superintendent_staff_id: '' });
  const [summary, setSummary] = useState<Any>(null);
  return (
    <div className="space-y-4">
      <PageHeader title="Exam centres" description="Centres per central session, allocation run (nearest / capacity / manual), appointment letters and centre dashboards." />
      <div className="flex flex-wrap gap-2">
        <Input className="w-80" placeholder="Exam session id" value={session} onChange={(e) => setSession(e.target.value)} />
        <select className={sel} value={strategy} onChange={(e) => setStrategy(e.target.value)}>{['nearest', 'capacity'].map((x) => <option key={x}>{x}</option>)}</select>
        <Button size="sm" disabled={!session} onClick={() => run.mutate(() => aa.allocate({ exam_session_id: session, strategy }).then((r: Any) => setSummary(r.data)), { onSuccess: done('Allocated'), onError: fail })}>Run allocation</Button>
      </div>
      {summary && <p className="text-sm">{summary.colleges_assigned} colleges to {summary.centres} centres · unassigned {(summary.unassigned ?? []).join(', ') || 'none'} · over capacity {(summary.over_capacity ?? []).join(', ') || 'none'}</p>}
      <Err q={q} />
      <SimpleTable head={['Code', 'College', 'Chief superintendent', 'Capacity', 'Routed', 'Seating', 'Assigned', '']} rows={list(q.data).map((c: Any) => [c.centre_code, c.college_code, c.chief_superintendent_name ?? '—', `${c.capacity ?? '—'} (${c.effective_capacity ?? '—'})`, c.registrations_routed, c.seating_status ?? '—', c.assigned_colleges.length, <Button key="a" size="sm" variant="outline" onClick={() => run.mutate(() => aa.appointment(c.id), { onSuccess: done('Appointment letter issued'), onError: fail })}>Appointment</Button>])} />
      <Section title="Add centre">
        <div className="flex flex-wrap gap-2">
          <Input className="w-72" placeholder="College id" value={f.college_id} onChange={(e) => setF({ ...f, college_id: e.target.value })} />
          <Input className="w-28" placeholder="Code" value={f.centre_code} onChange={(e) => setF({ ...f, centre_code: e.target.value })} />
          <Input className="w-28" placeholder="Capacity" value={f.capacity} onChange={(e) => setF({ ...f, capacity: e.target.value })} />
          <Input className="w-72" placeholder="Chief superintendent staff id" value={f.chief_superintendent_staff_id} onChange={(e) => setF({ ...f, chief_superintendent_staff_id: e.target.value })} />
          <Button size="sm" disabled={!session || !f.college_id || !f.centre_code} onClick={() => run.mutate(() => aa.createCentre({ exam_session_id: session, college_id: f.college_id, centre_code: f.centre_code, capacity: f.capacity ? Number(f.capacity) : undefined, chief_superintendent_staff_id: f.chief_superintendent_staff_id || undefined }), { onSuccess: done('Centre added'), onError: fail })}>Add</Button>
        </div>
      </Section>
    </div>
  );
}

export function CollegeExamCentrePage() {
  useTitle('Exam centre');
  const q = useQ(['mycentres'], () => aa.myCentres());
  return (
    <div className="space-y-4">
      <PageHeader title="Exam centre" description="Registrations routed to your centre, seating and answer-script bundles." />
      <Err q={q} />
      {list(q.data).map((d: Any) => (
        <Section key={d.centre.id} title={`${d.centre.centre_code} · ${d.centre.college_name}`}>
          <div className="grid gap-3 md:grid-cols-4"><Stat label="Routed" value={d.centre.registrations_routed} /><Stat label="Capacity" value={d.centre.effective_capacity} /><Stat label="Seated" value={d.seating_allocated} /><Stat label="Bundles" value={kv(d.bundles)} /></div>
          <p className="text-sm">{kv(d.registrations_by_college)}</p>
        </Section>
      ))}
    </div>
  );
}

// ---- returns ----------------------------------------------------------------------------------------------------------
export function ReturnsPage() {
  useTitle('Affiliation returns');
  const [kind, setKind] = useState('colleges_list');
  const q = useQ(['returns', kind], () => aa.returns(kind));
  const rows = data(q.data)?.rows ?? [];
  const head = rows.length ? Object.keys(rows[0]) : [];
  return (
    <div className="space-y-4">
      <PageHeader title="Statutory returns" description="Affiliated colleges list, intake and results by college (UGC / state returns, website list)." />
      <select className={sel} value={kind} onChange={(e) => setKind(e.target.value)}>{['colleges_list', 'intake', 'results_by_college'].map((x) => <option key={x}>{x}</option>)}</select>
      <Err q={q} />
      <SimpleTable head={head} rows={rows.map((r: Any) => head.map((h) => String(r[h] ?? '—')))} />
    </div>
  );
}

// ---- college portal ---------------------------------------------------------------------------------------------------
export function CollegeAffiliationPage() {
  useTitle('Affiliation');
  const dash = useQ(['mydash'], () => aa.myDashboard());
  const run = useRun();
  const d = data(dash.data);
  const [f, setF] = useState<Any>({ application_type: 'renewal', academic_year_id: '', program_id: '', requested_intake: '' });
  return (
    <div className="space-y-4">
      <CollegeDetailPage mine />
      {d && (
        <Section title="New application">
          <div className="flex flex-wrap gap-2">
            <select className={sel} value={f.application_type} onChange={(e) => setF({ ...f, application_type: e.target.value })}>{APP_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
            <Input className="w-72" placeholder="Academic year id" value={f.academic_year_id} onChange={(e) => setF({ ...f, academic_year_id: e.target.value })} />
            <Input className="w-72" placeholder="Programme id (intake increase / closure)" value={f.program_id} onChange={(e) => setF({ ...f, program_id: e.target.value })} />
            <Input className="w-32" placeholder="Requested intake" value={f.requested_intake} onChange={(e) => setF({ ...f, requested_intake: e.target.value })} />
            <Button size="sm" disabled={!f.academic_year_id} onClick={() => run.mutate(() => aa.createApplication({ college_id: d.profile.college_id, academic_year_id: f.academic_year_id, application_type: f.application_type, programs: f.program_id ? [{ program_id: f.program_id, requested_intake: f.requested_intake ? Number(f.requested_intake) : undefined }] : [] }), { onSuccess: done('Draft created — complete the checklist'), onError: fail })}>Create draft</Button>
          </div>
        </Section>
      )}
    </div>
  );
}

export function CollegeSubmissionsPage() {
  const params = useParams();
  const [termId, setTermId] = useState(params.termId ?? '');
  useTitle('Submissions');
  const dash = useQ(['mydash'], () => aa.myDashboard());
  const collegeId = data(dash.data)?.profile?.college_id;
  const q = useQ(['windows', termId, collegeId], () => aa.windows({ term_id: termId, college_id: collegeId }), !!termId && !!collegeId);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Submissions to the university" description="Windows with due chips; prepare from system data or upload, validate, submit; returns with remarks; locked indicators." />
      <Input className="w-80" placeholder="Term id" value={termId} onChange={(e) => setTermId(e.target.value)} />
      <Err q={q} />
      <SimpleTable head={['Type', 'Due', 'Window', 'Submission', '']} rows={list(q.data).filter((w: Any) => w.applies).map((w: Any) => [w.submission_type, day(w.due_on), <Chip key="w" tone={w.status === 'overdue' ? 'bad' : w.status === 'due' ? 'warn' : 'ok'} label={w.status} />, subChip(w.submission_status),
        w.submission_id ? <Link key="o" className="text-primary underline" to={`/college/submissions/view/${w.submission_id}`}>Open</Link> : <Button key="c" size="sm" variant="outline" onClick={() => run.mutate(() => aa.createSubmission({ college_id: collegeId, term_id: termId, submission_type: w.submission_type }), { onSuccess: done('Prepared'), onError: fail })}>Prepare</Button>])} />
    </div>
  );
}
