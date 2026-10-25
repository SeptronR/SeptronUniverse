import { useEffect, useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BadgeCheck, ShieldX } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { docApi as da } from '../api';

// Phase 26 web screens (Prompts/26 §26.9). Visibility, role type limits, lint and rules live in the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['docs', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['docs'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');
const rupees = (p?: number | null) => `₹${((p ?? 0) / 100).toLocaleString()}`;
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const TYPES = ['bonafide', 'character', 'conduct', 'noc', 'tc', 'migration', 'course_completion', 'provisional', 'degree', 'grade_card', 'transcript', 'hall_ticket', 'receipt', 'experience', 'service', 'internship_noc', 'hostel_allotment', 'event_certificate', 'undertaking', 'medical_certificate', 'fee_structure_letter', 'offer_letter', 'id_card', 'custom'];
const BLOCKS = ['header', 'meta', 'title', 'paragraph', 'table', 'photo', 'qr', 'barcode', 'signatures', 'seal', 'footer', 'watermark', 'secondary'];
const REGISTERS = ['degree', 'provisional', 'transcript', 'tc', 'migration', 'bonafide'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value}</p></CardContent></Card>;
}
async function openLink(id: string) {
  try {
    const r: Any = await da.signedLink(id, {});
    window.open(`/api/v1${String(r.data.url).replace(/^\/api\/v1/, '')}`, '_blank');
  } catch (e) {
    fail(e);
  }
}

// ---- templates + builder --------------------------------------------------------------------------------------------------
export function TemplatesPage() {
  useTitle('Document templates');
  const [type, setType] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const q = useQ(['tpl', type], () => da.templates({ template_type: type || undefined }));
  const run = useRun();
  const rows = list(q.data);
  return (
    <div className="space-y-4">
      <PageHeader title="Document templates" description="Platform defaults and institution overrides; clone → edit → preview → publish." actions={<select className={sel} value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>} />
      <Section title={`${rows.length} templates`}>
        <SimpleTable
          head={['Type', 'Name', 'Source', 'Version', 'Status', '']}
          rows={rows.map((t: Any) => [
            t.template_type,
            t.name,
            <StatusBadge key="s" status={t.source === 'platform' ? 'platform' : 'institution'} />,
            `v${t.version}`,
            <StatusBadge key="st" status={t.status} />,
            t.source === 'platform'
              ? <Button key="c" size="sm" variant="outline" onClick={() => run.mutate(() => da.createTemplate({ template_type: t.template_type, name: `${t.name} (override)`, from_template_id: t.id }), { onSuccess: (r: Any) => setOpen(r.data.id), onError: fail })}>Clone</Button>
              : <Button key="e" size="sm" variant="outline" onClick={() => setOpen(t.id)}>Edit</Button>,
          ])}
        />
      </Section>
      {open && <TemplateBuilder id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function TemplateBuilder({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQ(['tpl1', id], () => da.template(id));
  const t: Any = q.data?.data;
  const vars = useQ(['vars', t?.template_type], () => da.variables(t.template_type), !!t);
  const lint = useQ(['lint', id], () => da.lint(id), !!t);
  const versions = useQ(['ver', id], () => da.versions(id), !!t);
  const usage = useQ(['use', id], () => da.usage(id), !!t);
  const run = useRun();
  const [blocks, setBlocks] = useState<Any[]>([]);
  const [html, setHtml] = useState('');
  const [css, setCss] = useState('');
  const [mode, setMode] = useState<'blocks' | 'html'>('blocks');
  const [tab, setTab] = useState('builder');
  const [note, setNote] = useState('');
  const [pdf, setPdf] = useState<string | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  useEffect(() => {
    if (!t) return;
    setBlocks((t.layout?.blocks ?? []) as Any[]);
    setHtml(t.html_template ?? '');
    setCss(t.css ?? '');
    setMode(t.layout?.mode === 'html' ? 'html' : 'blocks');
  }, [t]);
  if (!t) return null;
  const readOnly = t.source === 'platform';
  const save = () => run.mutate(() => da.updateTemplate(id, mode === 'html' ? { html_template: html, css, layout: { mode: 'html', blocks } } : { layout: { blocks }, css }), { onSuccess: () => toast.success('Draft saved'), onError: fail });
  const preview = async () => {
    try {
      const b = await da.preview(id, { draft: mode === 'html' ? { html_template: html, css, layout: { mode: 'html' } } : { layout: { blocks }, css } });
      setPdf(URL.createObjectURL(b));
    } catch (e) {
      fail(e);
    }
  };
  const chip = (k: string) => {
    if (focus === null) return toast.info('Pick a paragraph block first');
    setBlocks(blocks.map((b, i) => (i === focus ? { ...b, text: `${b.text ?? ''} {{ ${k} }}` } : b)));
  };
  return (
    <Section title={`${t.name} · v${t.version} · ${t.status}`} action={<Button size="sm" variant="outline" onClick={onClose}>Close</Button>}>
      <div className="flex flex-wrap gap-2">{['builder', 'versions', 'usage'].map((x) => <Button key={x} size="sm" variant={tab === x ? 'default' : 'outline'} onClick={() => setTab(x)}>{x}</Button>)}</div>
      {tab === 'versions' && <SimpleTable head={['Version', 'Status', 'Change note', 'Updated']} rows={list(versions.data).map((v: Any) => [`v${v.version}`, v.status, v.change_note ?? '—', when(v.updated_at)])} />}
      {tab === 'usage' && <div className="text-sm">Issued: {usage.data?.data?.issued_count ?? 0} · Flows: {(usage.data?.data?.flows ?? []).join(', ')}</div>}
      {tab === 'builder' && (
        <div className="grid gap-4 lg:grid-cols-[200px_1fr_260px]">
          <div className="space-y-2">
            <p className="text-xs font-semibold">Blocks</p>
            {BLOCKS.map((b) => <Button key={b} size="sm" variant="outline" className="w-full justify-start" disabled={readOnly || mode === 'html'} onClick={() => setBlocks([...blocks, { type: b, text: b === 'paragraph' || b === 'secondary' ? '' : undefined, props: {} }])}>+ {b}</Button>)}
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={mode === 'html'} disabled={readOnly} onChange={(e) => setMode(e.target.checked ? 'html' : 'blocks')} /> HTML / CSS mode</label>
          </div>
          <div className="space-y-2">
            {mode === 'blocks'
              ? blocks.map((b, i) => (
                  <div key={i} className={`rounded border p-2 text-sm ${focus === i ? 'border-primary' : ''}`} onClick={() => setFocus(i)}>
                    <div className="flex justify-between"><b>{b.type}</b>{!readOnly && <button className="text-xs text-muted-foreground" onClick={() => setBlocks(blocks.filter((_, j) => j !== i))}>remove</button>}</div>
                    {(b.type === 'paragraph' || b.type === 'title' || b.type === 'footer' || b.type === 'secondary') && <textarea className="mt-1 w-full rounded border bg-background p-1 text-xs" rows={3} disabled={readOnly} value={b.text ?? ''} onChange={(e) => setBlocks(blocks.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />}
                  </div>
                ))
              : <textarea className="h-72 w-full rounded border bg-background p-2 font-mono text-xs" value={html} disabled={readOnly} onChange={(e) => setHtml(e.target.value)} />}
            <textarea className="h-20 w-full rounded border bg-background p-2 font-mono text-xs" placeholder="CSS" value={css} disabled={readOnly} onChange={(e) => setCss(e.target.value)} />
            <div className="flex flex-wrap gap-2">
              {!readOnly && <Button size="sm" onClick={save}>Save draft</Button>}
              <Button size="sm" variant="outline" onClick={preview}>Preview</Button>
              {!readOnly && <><Input placeholder="Change note" value={note} onChange={(e) => setNote(e.target.value)} /><Button size="sm" onClick={() => run.mutate(() => da.publish(id, note), { onSuccess: () => toast.success('Published'), onError: fail })}>Publish</Button></>}
            </div>
            {pdf && <iframe title="preview" src={pdf} className="h-[480px] w-full rounded border" />}
          </div>
          <div className="space-y-2">
            <p className="text-xs font-semibold">Variables (click to insert)</p>
            <div className="flex flex-wrap gap-1">{(vars.data?.data?.variables ?? []).map((v: Any) => <button key={v.key} title={v.example} className="rounded bg-muted px-1.5 py-0.5 text-[11px]" onClick={() => chip(v.key)}>{v.key}</button>)}</div>
            <p className="text-xs font-semibold">Lint</p>
            {(lint.data?.data?.issues ?? []).length === 0 ? <p className="text-xs text-muted-foreground">No issues</p> : (lint.data?.data?.issues ?? []).map((i: Any, n: number) => <p key={n} className={`text-xs ${i.level === 'error' ? 'text-status-rejected' : ''}`}>{i.level}: {i.message}</p>)}
          </div>
        </div>
      )}
    </Section>
  );
}

// ---- issued register -----------------------------------------------------------------------------------------------------
export function IssuedRegisterPage() {
  useTitle('Issued documents');
  const [scope, setScope] = useState<string | undefined>();
  const [type, setType] = useState('');
  const [qtext, setQ] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const q = useQ(['issued', scope, type, qtext], () => da.issued({ scope, template_type: type || undefined, q: qtext || undefined }));
  const stats = useQ(['stats'], () => da.stats());
  const s: Any = stats.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Issued documents" description="Register of every certificate and letter (number, serial, hash, verification token)." />
      {s && <div className="grid gap-3 sm:grid-cols-4"><Stat label="Issued" value={Object.values(s.issued_by_type ?? {}).reduce((a: number, b: Any) => a + Number(b), 0)} /><Stat label="Revoked" value={s.revoked} /><Stat label="Pending pickups" value={s.pending_pickups} /><Stat label="Certificate fees" value={rupees(s.fee_revenue_paise)} /></div>}
      <ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={(v) => setScope(v)} />
      <div className="flex flex-wrap gap-2"><select className={sel} value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{TYPES.map((t) => <option key={t}>{t}</option>)}</select><Input placeholder="Number / serial" value={qtext} onChange={(e) => setQ(e.target.value)} /></div>
      <Section title={`${list(q.data).length} documents`}>
        <SimpleTable head={['Number', 'Type', 'Holder', 'Serial', 'Issued', 'State', '']} rows={list(q.data).map((d: Any) => [d.document_number, d.template_type, d.person_name ?? '—', d.serial_no ?? '—', when(d.issued_at), <StatusBadge key="s" status={d.revoked ? 'revoked' : 'valid'} />, <Button key="o" size="sm" variant="outline" onClick={() => setOpen(d.id)}>Open</Button>])} />
      </Section>
      {open && <DocumentPanel id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function DocumentPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQ(['doc', id], () => da.document(id));
  const run = useRun();
  const [reason, setReason] = useState('');
  const d: Any = q.data?.data;
  if (!d) return null;
  return (
    <Section title={`${d.document_number} · ${d.template_type}`} action={<Button size="sm" variant="outline" onClick={onClose}>Close</Button>}>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <dt className="text-muted-foreground">Holder</dt><dd>{d.person_name ?? '—'}</dd>
        <dt className="text-muted-foreground">Template version</dt><dd>v{d.template_version ?? '—'}</dd>
        <dt className="text-muted-foreground">SHA-256</dt><dd className="break-all font-mono text-xs">{d.content_hash}</dd>
        <dt className="text-muted-foreground">Verification</dt><dd className="break-all font-mono text-xs">{d.verification_token ? <a className="underline" href={`/verify/${d.verification_token}`} target="_blank" rel="noreferrer">/verify/{d.verification_token.slice(0, 16)}…</a> : '—'}</dd>
        <dt className="text-muted-foreground">Downloads</dt><dd>{d.downloads}</dd>
        {d.revoked && <><dt className="text-muted-foreground">Revoked</dt><dd>{d.revoke_reason}</dd></>}
      </dl>
      {(d.download_log ?? []).length > 0 && <SimpleTable head={['When', 'By', 'Purpose']} rows={d.download_log.map((l: Any) => [when(l.at), l.by, l.purpose ?? '—'])} />}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => openLink(d.id)}>Signed download</Button>
        <Input placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        <Button size="sm" variant="outline" disabled={d.revoked} onClick={() => run.mutate(() => da.revoke(d.id, reason), { onSuccess: () => toast.success('Revoked'), onError: fail })}>Revoke</Button>
        <Button size="sm" variant="outline" onClick={() => run.mutate(() => da.reissue(d.id, reason), { onSuccess: () => toast.success('Reissued'), onError: fail })}>Reissue</Button>
      </div>
    </Section>
  );
}

// ---- bulk -----------------------------------------------------------------------------------------------------------------
export function BulkGenerationPage() {
  useTitle('Bulk generation');
  const [form, setForm] = useState({ template_type: 'id_card', batch_id: '', staff_ids: '', purpose: '', print_order: 'roll', register: '' });
  const [job, setJob] = useState<string | null>(null);
  const j = useQuery({ queryKey: ['docs', 'bulk', job], queryFn: () => da.bulkJob(job as string), enabled: !!job, refetchInterval: (qq) => ((qq.state.data as Any)?.data?.status === 'running' || (qq.state.data as Any)?.data?.status === 'queued' ? 3000 : false) });
  const run = useRun();
  const r: Any = j.data?.data;
  const submit = () => {
    const scope = form.staff_ids ? { staff_ids: form.staff_ids.split(',').map((s) => s.trim()) } : { batch_id: form.batch_id };
    run.mutate(() => da.bulk({ template_type: form.template_type, scope, print_order: form.print_order, register: form.register || undefined, variables_override: form.purpose ? { purpose: form.purpose } : undefined, zip: true }), { onSuccess: (x: Any) => setJob(x.data.job_id), onError: fail });
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Bulk generation" description="Type → scope → variables → run; progress, failures and ZIP." />
      <Section title="New job">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={form.template_type} onChange={(e) => setForm({ ...form, template_type: e.target.value })}>{['id_card', 'bonafide', 'course_completion', 'experience', 'service'].map((t) => <option key={t}>{t}</option>)}</select>
          <Input placeholder="Batch id" value={form.batch_id} onChange={(e) => setForm({ ...form, batch_id: e.target.value })} />
          <Input placeholder="or staff ids (comma)" value={form.staff_ids} onChange={(e) => setForm({ ...form, staff_ids: e.target.value })} />
          <Input placeholder="Purpose" value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
          <select className={sel} value={form.register} onChange={(e) => setForm({ ...form, register: e.target.value })}><option value="">No register</option>{REGISTERS.map((x) => <option key={x}>{x}</option>)}</select>
          <select className={sel} value={form.print_order} onChange={(e) => setForm({ ...form, print_order: e.target.value })}>{['roll', 'serial', 'name'].map((x) => <option key={x}>{x}</option>)}</select>
          <Button onClick={submit}>Run</Button>
        </div>
      </Section>
      {r && (
        <Section title={`Job ${r.status} · ${r.progress}%`} action={r.zip_url ? <a className="text-sm underline" href={r.zip_url}>Download ZIP</a> : undefined}>
          <p className="text-sm">{r.result ? `${r.result.ok} generated, ${(r.result.failed ?? []).length} failed` : r.message}</p>
          {(r.result?.failed ?? []).length > 0 && <SimpleTable head={['Who', 'Reason']} rows={r.result.failed.map((f: Any) => [f.label, f.reason])} />}
        </Section>
      )}
    </div>
  );
}

// ---- serial registers ----------------------------------------------------------------------------------------------------
export function SerialRegistersPage() {
  useTitle('Serial registers');
  const [reg, setReg] = useState('provisional');
  const regs = useQ(['regs'], () => da.registers());
  const rows = useQ(['reg', reg], () => da.register(reg));
  const rec = useQ(['rec', reg], () => da.reconcile(reg));
  const run = useRun();
  const [count, setCount] = useState('5');
  const [v, setV] = useState({ serial_no: '', reason: '' });
  return (
    <div className="space-y-4">
      <PageHeader title="Serial registers" description="Statutory books: reserve, use, void (with reason), reconcile and export." />
      <SimpleTable head={['Register', 'Next', 'Reserved', 'Used', 'Void', '']} rows={list(regs.data).map((r: Any) => [r.register, r.next ?? '—', r.reserved, r.used, r.void, <Button key="o" size="sm" variant="outline" onClick={() => setReg(r.register)}>Open</Button>])} />
      <Section title={`Register · ${reg}`} action={<Button size="sm" variant="outline" onClick={() => run.mutate(() => da.exportRegister(reg), { onSuccess: () => toast.success('Export queued'), onError: fail })}>Export</Button>}>
        <div className="flex flex-wrap gap-2">
          <Input className="w-20" value={count} onChange={(e) => setCount(e.target.value)} /><Button size="sm" onClick={() => run.mutate(() => da.reserve(reg, Number(count)), { onSuccess: () => toast.success('Reserved'), onError: fail })}>Reserve</Button>
          <Input placeholder="Serial" value={v.serial_no} onChange={(e) => setV({ ...v, serial_no: e.target.value })} /><Input placeholder="Reason" value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => da.voidSerial(reg, v.serial_no, v.reason), { onSuccess: () => toast.success('Voided'), onError: fail })}>Void</Button>
        </div>
        {rec.data?.data && <p className="text-sm">Issued {rec.data.data.issued} · used {rec.data.data.used} · reserved {rec.data.data.reserved} · void {rec.data.data.void} · gaps {(rec.data.data.gaps ?? []).length}</p>}
        <SimpleTable head={['Serial', 'Status', 'Document', 'Reason']} rows={list(rows.data).map((s: Any) => [s.serial_no, <StatusBadge key="s" status={s.status} />, s.document_number ?? '—', s.reason ?? '—'])} />
      </Section>
    </div>
  );
}

// ---- requests queue -----------------------------------------------------------------------------------------------------
const TABS: [string, string][] = [['requested', 'Pending approval'], ['fee_pending', 'Fee pending'], ['approved', 'Approved'], ['generated', 'Generated'], ['issued', 'Issued'], ['rejected', 'Rejected']];
export function RequestsQueuePage() {
  useTitle('Certificate requests');
  const [status, setStatus] = useState('requested');
  const [scope, setScope] = useState<string | undefined>();
  const [open, setOpen] = useState<string | null>(null);
  const q = useQ(['reqs', status, scope], () => da.requests({ status, scope }));
  return (
    <div className="space-y-4">
      <PageHeader title="Certificate requests" description="Queue with SLA; checks (holds / no-dues), decide, generate, issue and pickup." />
      <ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={(v) => setScope(v)} />
      <div className="flex flex-wrap gap-2">{TABS.map(([k, l]) => <Button key={k} size="sm" variant={status === k ? 'default' : 'outline'} onClick={() => setStatus(k)}>{l}</Button>)}</div>
      <Section title={`${list(q.data).length} requests`}>
        <SimpleTable head={['Type', 'Person', 'Copies', 'Delivery', 'Stage', 'SLA', '']} rows={list(q.data).map((r: Any) => [r.template_type, r.person_name ?? '—', r.copies, r.delivery, r.stage ?? r.status, <StatusBadge key="sla" status={r.sla_breached ? 'overdue' : 'on_time'} />, <Button key="o" size="sm" variant="outline" onClick={() => setOpen(r.id)}>Open</Button>])} />
      </Section>
      {open && <RequestPanel id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function RequestPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQ(['req', id], () => da.request(id));
  const run = useRun();
  const [remarks, setRemarks] = useState('');
  const [courier, setCourier] = useState('');
  const [collector, setCollector] = useState('');
  const r: Any = q.data?.data;
  if (!r) return null;
  const go = (fn: () => Promise<unknown>, msg: string) => run.mutate(fn, { onSuccess: () => toast.success(msg), onError: fail });
  return (
    <Section title={`${r.template_type} · ${r.person_name ?? ''}`} action={<Button size="sm" variant="outline" onClick={onClose}>Close</Button>}>
      <p className="text-sm">Status {r.status} {r.stage ? `(${r.stage})` : ''} · fee {rupees(r.fee_paise)} {r.fee_status ?? ''} · SLA due {r.sla_due_on}</p>
      {r.checks && <p className="text-sm">Holds: {(r.checks.holds ?? []).map((h: Any) => h.hold_type).join(', ') || 'none'} · No-dues: {r.checks.no_dues ?? 'n/a'}</p>}
      <div className="flex flex-wrap gap-2">
        <Input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
        <Button size="sm" onClick={() => go(() => da.decide(id, 'approve', remarks), 'Approved')}>Approve</Button>
        <Button size="sm" variant="outline" onClick={() => go(() => da.decide(id, 'reject', remarks), 'Rejected')}>Reject</Button>
        <Button size="sm" variant="outline" onClick={() => go(() => da.decide(id, 'recommend', remarks), 'Recommended')}>Recommend (HOD)</Button>
        <Button size="sm" variant="outline" onClick={() => go(() => da.generate(id), 'Generated')}>Generate</Button>
        {r.delivery === 'post' && <Input placeholder="Courier ref" value={courier} onChange={(e) => setCourier(e.target.value)} />}
        <Button size="sm" variant="outline" onClick={() => go(() => da.issue(id, { courier_ref: courier || undefined }), 'Issued')}>Issue</Button>
        {r.stage === 'pickup_ready' && <><Input placeholder="Collected by" value={collector} onChange={(e) => setCollector(e.target.value)} /><Button size="sm" onClick={() => go(() => da.collected(id, collector), 'Collected')}>Collected</Button></>}
      </div>
      <SimpleTable head={['When', 'Step']} rows={(r.timeline ?? []).map((t: Any) => [when(t.at), t.action])} />
    </Section>
  );
}

export function DocumentSettingsPage() {
  useTitle('Document settings');
  const q = useQ(['settings'], () => da.settings());
  const s: Any = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Document settings" description="Request rules, signatories, watermark and verification options (edit under Settings › documents)." />
      {s && (
        <>
          <Section title="Request rules"><SimpleTable head={['Type', 'Fee', 'Approver', 'SLA days', 'No-dues', 'For']} rows={Object.entries(s.request_rules ?? {}).map(([k, v]: [string, Any]) => [k, rupees(v.fee_paise), v.approver, v.sla_days, v.requires_no_dues ? 'yes' : '—', (v.allowed_for ?? []).join(', ')])} /></Section>
          <Section title="Signatories"><SimpleTable head={['Role', 'Name', 'Designation']} rows={Object.entries(s.signatories ?? {}).map(([k, v]: [string, Any]) => [k, v.name, v.designation])} /></Section>
          <Section title="Verification & links"><p className="text-sm">Verify shows PDF: {String(s.verify_shows_pdf)} · Parent requests: {String(s.allow_parent_requests)} · College overrides: {String(s.college_overrides)} · Link TTL: {s.signed_link_ttl_minutes} min</p></Section>
        </>
      )}
    </div>
  );
}

// ---- portals ---------------------------------------------------------------------------------------------------------------
export function MyDocumentsPage({ wards = false }: { wards?: boolean }) {
  useTitle('My documents');
  const docs = useQ(['mine', wards], () => (wards ? da.wards() : da.mine()));
  const reqs = useQ(['myreqs', wards], () => (wards ? da.wardRequests() : da.myRequests()));
  const types = useQ(['types'], () => da.requestTypes());
  const run = useRun();
  const [form, setForm] = useState({ template_type: '', copies: '1', delivery: 'digital', purpose: '', address: '', registration_number: '', person_id: '' });
  const allowed = list(types.data).filter((t: Any) => t.allowed);
  const fee = allowed.find((t: Any) => t.template_type === form.template_type);
  return (
    <div className="space-y-4">
      <PageHeader title={wards ? 'Ward documents' : 'My documents'} description="Certificates and letters issued to you; downloads use time-limited signed links." />
      <Section title="Documents">
        <SimpleTable head={['Number', 'Type', 'Issued', 'State', '']} rows={list(docs.data).map((d: Any) => [d.document_number, d.template_type, when(d.issued_at), <StatusBadge key="s" status={d.revoked ? 'revoked' : 'valid'} />, <Button key="d" size="sm" variant="outline" disabled={d.revoked} onClick={() => openLink(d.id)}>Download</Button>])} />
      </Section>
      <Section title="Request a certificate">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={form.template_type} onChange={(e) => setForm({ ...form, template_type: e.target.value })}><option value="">Type…</option>{allowed.map((t: Any) => <option key={t.template_type} value={t.template_type}>{t.label} ({rupees(t.fee_paise)})</option>)}</select>
          <Input className="w-20" type="number" min={1} max={10} value={form.copies} onChange={(e) => setForm({ ...form, copies: e.target.value })} />
          <select className={sel} value={form.delivery} onChange={(e) => setForm({ ...form, delivery: e.target.value })}>{['digital', 'pickup', 'post'].map((d) => <option key={d}>{d}</option>)}</select>
          <Input placeholder="Purpose" value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
          {form.delivery === 'post' && <Input placeholder="Postal address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />}
          {wards && <Input placeholder="Ward student id" value={form.person_id} onChange={(e) => setForm({ ...form, person_id: e.target.value })} />}
          <Input placeholder="Reg. no (alumni)" value={form.registration_number} onChange={(e) => setForm({ ...form, registration_number: e.target.value })} />
          <Button disabled={!form.template_type} onClick={() => run.mutate(() => da.createRequest({ template_type: form.template_type, copies: Number(form.copies), delivery: form.delivery, purpose: form.purpose || undefined, address: form.address || undefined, registration_number: form.registration_number || undefined, person_id: form.person_id || undefined }), { onSuccess: () => toast.success('Requested'), onError: fail })}>Request</Button>
        </div>
        {fee && <p className="text-xs text-muted-foreground">Fee {rupees(fee.fee_paise + fee.copies_fee_paise * (Number(form.copies) - 1))} · SLA {fee.sla_days} days{fee.requires_no_dues ? ' · needs no-dues clearance' : ''}</p>}
      </Section>
      <Section title="My requests">
        <SimpleTable head={['Type', 'Status', 'Delivery', 'Fee', 'Timeline', '']} rows={list(reqs.data).map((r: Any) => [r.template_type, <StatusBadge key="s" status={r.stage === 'pickup_ready' ? 'pickup_ready' : r.status} />, r.pickup?.on ? `pickup ${r.pickup.on}` : r.delivery, r.fee_paise ? `${rupees(r.fee_paise)} ${r.fee_status ?? ''}` : '—', (r.timeline ?? []).map((t: Any) => t.action).join(' → '), ['requested', 'fee_pending'].includes(r.status) ? <Button key="c" size="sm" variant="outline" onClick={() => run.mutate(() => da.cancelRequest(r.id), { onSuccess: () => toast.success('Cancelled'), onError: fail })}>Cancel</Button> : ''])} />
      </Section>
    </div>
  );
}
export function WardDocumentsPage() {
  return <MyDocumentsPage wards />;
}

// ---- public verification --------------------------------------------------------------------------------------------------
export function DocVerifyPage() {
  const { token = '' } = useParams();
  const q = useQuery({ queryKey: ['verify-doc', token], queryFn: () => da.verify(token), retry: false });
  const r: Any = q.data?.data;
  if (q.isLoading) return <div className="p-8 text-center text-sm">Verifying…</div>;
  const valid = !!r?.valid;
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md"><CardContent className="space-y-3 pt-6 text-center">
        {valid ? <BadgeCheck className="mx-auto h-12 w-12 text-status-approved" /> : <ShieldX className="mx-auto h-12 w-12 text-status-rejected" />}
        <h1 className="text-lg font-semibold">{valid ? 'Valid document' : r?.revoked ? 'Revoked' : 'Not valid'}</h1>
        {r && (
          <dl className="grid grid-cols-2 gap-2 text-left text-sm">
            {[['Type', r.template_type ?? r.document_type ?? r.entity_type], ['Number', r.document_number], ['Issued', r.issued_at ? new Date(r.issued_at).toLocaleDateString() : null], ['Holder', r.holder_masked], ['Institution', r.institution], ['Superseded by', r.superseded_by], ['Reason', r.revoke_reason], ['SHA-256', r.content_hash]].filter(([, v]) => v).map(([k, v]) => <><dt key={`k${k}`} className="text-muted-foreground">{k}</dt><dd key={`v${k}`} className="break-all">{String(v)}</dd></>)}
          </dl>
        )}
        {!r && <p className="text-sm text-muted-foreground">Unknown or tampered token.</p>}
        {r?.pdf_url && <a className="text-sm underline" href={r.pdf_url}>View document</a>}
      </CardContent></Card>
    </div>
  );
}

export function VerifyLandingPage() {
  const [token, setToken] = useState('');
  const [res, setRes] = useState<Any>(null);
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md"><CardContent className="space-y-3 pt-6">
        <h1 className="text-lg font-semibold">Verify a document</h1>
        <div className="flex gap-2"><Input placeholder="Verification token" value={token} onChange={(e) => setToken(e.target.value)} /><Button onClick={() => (window.location.href = `/verify/${token.trim()}`)}>Verify</Button></div>
        <p className="text-sm text-muted-foreground">or upload the original PDF to check its fingerprint:</p>
        <input type="file" accept="application/pdf" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; try { setRes((await da.verifyHash(f)).data); } catch (err) { fail(err); } }} />
        {res && <p className="text-sm">{res.valid ? `Valid — ${res.template_type} ${res.document_number} (${res.institution})` : res.hint ?? 'Not valid'}</p>}
        <a className="text-sm underline" href="/verify/bulk">Employer bulk verification</a>
      </CardContent></Card>
    </div>
  );
}
