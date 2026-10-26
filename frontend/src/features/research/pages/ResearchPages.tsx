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
import { rsApi as ra } from '../api';

// Phase 30 web screens (Prompts/30 §30.9). Ownership, scopes, verification locks and workflows are enforced by the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['research', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['research'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const inr = (p?: number | null) => `₹${((p ?? 0) / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[80px] w-full rounded-md border bg-background p-2 text-sm';
const YEAR = new Date().getFullYear();
const INDEXING = ['sci', 'scie', 'scopus', 'wos', 'ugc_care', 'other', 'none'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function Bar({ pct }: { pct: number }) {
  return <div className="h-2 w-full rounded bg-muted"><div className={`h-2 rounded ${pct > 90 ? 'bg-destructive' : 'bg-primary'}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>;
}
function Bars({ data }: { data?: Record<string, number> }) {
  const rows = Object.entries(data ?? {});
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return <div className="space-y-1">{rows.map(([k, v]) => <div key={k} className="flex items-center gap-2 text-sm"><span className="w-28 truncate text-muted-foreground">{k}</span><div className="h-3 rounded bg-primary/70" style={{ width: `${Math.max(2, (100 * v) / max)}%` }} /><span>{v}</span></div>)}</div>;
}
const Chip = ({ text }: { text?: string | null }) => (text ? <span className="rounded bg-muted px-1.5 py-0.5 text-xs uppercase">{text}</span> : null);

// ---- publications ----------------------------------------------------------------------------------------------------------
function PublicationForm({ onDone }: { onDone?: () => void }) {
  const [f, setF] = useState<Any>({ title: '', venue: '', year: YEAR, doi: '', indexing: 'scopus', pub_type: 'journal' });
  const run = useRun();
  const save = () =>
    run.mutate(() => ra.addPublication({ ...f, year: Number(f.year) || undefined, doi: f.doi || undefined, venue: f.venue || undefined }), {
      onSuccess: () => { toast.success('Added'); onDone?.(); },
      onError: (e: Any) => {
        const d = e?.response?.data?.error?.details;
        if (d?.code === 'DUPLICATE_DOI' && d.existing_id && window.confirm(`Already recorded: “${d.existing_title}”. Claim co-authorship?`)) {
          run.mutate(() => ra.claim(d.existing_id), { onSuccess: () => toast.success('Claimed as co-author'), onError: fail });
        } else fail(e);
      },
    });
  return (
    <div className="flex flex-wrap gap-2">
      <Input className="w-80" placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
      <Input className="w-56" placeholder="Venue" value={f.venue} onChange={(e) => setF({ ...f, venue: e.target.value })} />
      <Input className="w-24" placeholder="Year" value={f.year} onChange={(e) => setF({ ...f, year: e.target.value })} />
      <Input className="w-56" placeholder="DOI" value={f.doi} onChange={(e) => setF({ ...f, doi: e.target.value })} />
      <select className={sel} value={f.indexing} onChange={(e) => setF({ ...f, indexing: e.target.value })}>{INDEXING.map((i) => <option key={i}>{i}</option>)}</select>
      <select className={sel} value={f.pub_type} onChange={(e) => setF({ ...f, pub_type: e.target.value })}>{['journal', 'conference', 'book', 'chapter'].map((i) => <option key={i}>{i}</option>)}</select>
      <Button size="sm" disabled={f.title.length < 3} onClick={save}>Add</Button>
    </div>
  );
}

function ImportWizard() {
  const [f, setF] = useState<Any>({ source: 'crossref', identifier: '', content: '' });
  const [prev, setPrev] = useState<Any>(null);
  const run = useRun();
  const preview = () => run.mutate(() => ra.importPreview({ source: f.source, identifier: f.identifier || undefined, content: f.content || undefined }), { onSuccess: (r: Any) => setPrev(r.data), onError: fail });
  const apply = () => run.mutate(() => ra.importApply({ token: prev.token }), { onSuccess: (r: Any) => { toast.success(`${r.data.created} imported, ${r.data.claimed} claimed`); setPrev(null); }, onError: fail });
  const file = f.source === 'bibtex' || f.source === 'csv';
  return (
    <Section title="Import (DOI / ORCID / Scopus / BibTeX / CSV → preview → apply)">
      <div className="flex flex-wrap gap-2">
        <select className={sel} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>{['crossref', 'orcid', 'scopus', 'bibtex', 'csv'].map((s) => <option key={s}>{s}</option>)}</select>
        {!file && <Input className="w-72" placeholder="DOI / ORCID iD / Scopus author id (blank = my profile id)" value={f.identifier} onChange={(e) => setF({ ...f, identifier: e.target.value })} />}
        <Button size="sm" onClick={preview}>Preview</Button>
      </div>
      {file && <textarea className={area} placeholder={f.source === 'csv' ? 'title,venue,year,doi,indexing,authors' : '@article{…}'} value={f.content} onChange={(e) => setF({ ...f, content: e.target.value })} />}
      {prev && (
        <div className="space-y-2">
          <p className="text-sm">{prev.matches.length} matches (claim) · {prev.duplicates.length} duplicates (skip) · {prev.new.length} new</p>
          <SimpleTable head={['Kind', 'Title', 'Venue', 'Year', 'DOI', 'Indexing']} rows={[...prev.new.map((c: Any) => ['new', c]), ...prev.matches.map((c: Any) => ['match', c]), ...prev.duplicates.map((c: Any) => ['duplicate', c])].map(([k, c]: Any) => [<StatusBadge key="k" status={k} />, c.title, c.venue, c.year, c.doi, <Chip key="i" text={c.indexing} />])} />
          <Button size="sm" onClick={apply}>Apply</Button>
        </div>
      )}
    </Section>
  );
}

export function PublicationsPage({ verification = false }: { verification?: boolean }) {
  useTitle(verification ? 'Verification queue' : 'Publications');
  const [f, setF] = useState<Any>({ indexing: '', year: '', verified: verification ? 'false' : '', q: '' });
  const [scope, setScope] = useState<string | undefined>(verification ? 'department' : undefined);
  const [picked, setPicked] = useState<string[]>([]);
  const [remarks, setRemarks] = useState('');
  const res = useQ(['pubs', f, scope], () => ra.publications({ indexing: f.indexing || undefined, year: f.year || undefined, verified: f.verified === '' ? undefined : f.verified === 'true', q: f.q || undefined, scope, per_page: 200 }));
  const run = useRun();
  const rows = list(res.data);
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const verify = (approve: boolean) => run.mutate(() => ra.verify({ ids: picked, approve, remarks: remarks || undefined }), { onSuccess: (r: Any) => { toast.success(`${r.data.verified} final · ${r.data.department_level} department · ${r.data.rejected} rejected`); setPicked([]); }, onError: fail });
  const dups = rows.filter((p: Any) => p.duplicates?.length);
  return (
    <div className="space-y-4">
      <PageHeader title={verification ? 'Publication verification' : 'Publications'} description="Indexing, author tags, two-level verification (HOD → research cell); verified rows are locked for authors." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      {!verification && <Section title="Add publication"><PublicationForm /></Section>}
      {!verification && <ImportWizard />}
      <Section title={`Records (${(res.data as Any)?.meta?.pagination?.total ?? rows.length})`} action={<div className="flex gap-2"><Input className="w-48" placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} /><Button size="sm" disabled={!picked.length} onClick={() => verify(true)}>Verify ({picked.length})</Button><Button size="sm" variant="outline" disabled={!picked.length} onClick={() => verify(false)}>Reject</Button></div>}>
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.indexing} onChange={(e) => setF({ ...f, indexing: e.target.value })}><option value="">All indexing</option>{INDEXING.map((i) => <option key={i}>{i}</option>)}</select>
          <Input className="w-24" placeholder="Year" value={f.year} onChange={(e) => setF({ ...f, year: e.target.value })} />
          <select className={sel} value={f.verified} onChange={(e) => setF({ ...f, verified: e.target.value })}><option value="">Any state</option><option value="true">Verified</option><option value="false">Unverified</option></select>
          <Input className="w-64" placeholder="Title or DOI" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        </div>
        <SimpleTable head={['', 'Title', 'Faculty', 'Venue', 'Year', 'Indexing', 'IF', 'Citations', 'State']} rows={rows.map((p: Any) => [<input key="c" type="checkbox" checked={picked.includes(p.id)} onChange={() => toggle(p.id)} />, p.title, p.staff_name, p.venue, p.year, <Chip key="i" text={p.indexing} />, p.impact_factor ?? '', p.citations ?? 0, <StatusBadge key="s" status={p.is_verified ? 'verified' : p.verification_level} />])} />
      </Section>
      {dups.length > 0 && <Section title="Duplicate DOIs"><SimpleTable head={['Title', 'DOI', 'Other rows']} rows={dups.map((p: Any) => [p.title, p.doi, p.duplicates.length])} /></Section>}
    </div>
  );
}

// ---- patents -------------------------------------------------------------------------------------------------------------------
export function PatentsPage() {
  useTitle('Patents');
  const [scope, setScope] = useState<string | undefined>();
  const res = useQ(['patents', scope], () => ra.patents({ scope }));
  const [f, setF] = useState<Any>({ title: '', application_no: '' });
  const run = useRun();
  const next: Record<string, string> = { filed: 'published', published: 'granted', granted: 'commercialised' };
  return (
    <div className="space-y-4">
      <PageHeader title="Patents" description="Filed → published → granted → commercialised (forward only)." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <Section title="Record a patent"><div className="flex flex-wrap gap-2"><Input className="w-80" placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /><Input className="w-48" placeholder="Application no." value={f.application_no} onChange={(e) => setF({ ...f, application_no: e.target.value })} /><Button size="sm" disabled={f.title.length < 3} onClick={() => run.mutate(() => ra.addPatent(f), { onSuccess: () => toast.success('Recorded'), onError: fail })}>Add</Button></div></Section>
      <Section title="Register"><SimpleTable head={['Title', 'Inventor', 'Application', 'Filed', 'Published', 'Granted', 'Status', '']} rows={list(res.data).map((p: Any) => [p.title, p.staff_name, p.application_no, day(p.filed_on), day(p.published_on), day(p.granted_on), <StatusBadge key="s" status={p.status} />, next[p.status] ? <Button key="b" size="sm" variant="outline" onClick={() => run.mutate(() => ra.updatePatent(p.id, { status: next[p.status] }), { onError: fail })}>→ {next[p.status]}</Button> : null])} /></Section>
    </div>
  );
}

// ---- projects ------------------------------------------------------------------------------------------------------------------
export function ProjectsPage() {
  useTitle('Projects & grants');
  const [f, setF] = useState<Any>({ status: '', agency: '' });
  const [scope, setScope] = useState<string | undefined>();
  const res = useQ(['projects', f, scope], () => ra.projects({ status: f.status || undefined, agency: f.agency || undefined, scope, per_page: 200 }));
  const [n, setN] = useState<Any>({ title: '', funding_agency: 'DST', sanctioned_paise: '', scheme: '' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Projects & grants" description="Applied → sanctioned (research cell → principal) → ongoing → completed → closed; ledgers from Phase 23." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <Section title="Apply"><div className="flex flex-wrap gap-2"><Input className="w-80" placeholder="Title" value={n.title} onChange={(e) => setN({ ...n, title: e.target.value })} /><Input className="w-32" placeholder="Agency" value={n.funding_agency} onChange={(e) => setN({ ...n, funding_agency: e.target.value })} /><Input className="w-40" placeholder="Scheme" value={n.scheme} onChange={(e) => setN({ ...n, scheme: e.target.value })} /><Input className="w-40" placeholder="Amount (₹)" value={n.sanctioned_paise} onChange={(e) => setN({ ...n, sanctioned_paise: e.target.value })} /><Button size="sm" disabled={n.title.length < 3} onClick={() => run.mutate(() => ra.addProject({ ...n, sanctioned_paise: n.sanctioned_paise ? Math.round(Number(n.sanctioned_paise) * 100) : undefined, scheme: n.scheme || undefined }), { onSuccess: () => toast.success('Applied'), onError: fail })}>Apply</Button></div></Section>
      <Section title="Projects">
        <div className="flex gap-2"><select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{['applied', 'sanctioned', 'ongoing', 'completed', 'closed'].map((s) => <option key={s}>{s}</option>)}</select><Input className="w-40" placeholder="Agency" value={f.agency} onChange={(e) => setF({ ...f, agency: e.target.value })} /></div>
        <SimpleTable head={['Title', 'PI', 'Agency', 'Sanctioned', 'Utilisation', 'Status']} rows={list(res.data).map((p: Any) => [<Link key="l" className="text-primary underline" to={`/admin/research/projects/${p.id}`}>{p.title}</Link>, p.pi_name, p.funding_agency, inr(p.sanctioned_paise), <div key="u" className="w-32"><Bar pct={p.utilisation_pct} /></div>, <StatusBadge key="s" status={p.status} />])} />
      </Section>
    </div>
  );
}

export function ProjectPage() {
  const { id = '' } = useParams();
  const res = useQ(['project', id], () => ra.project(id));
  const [x, setX] = useState<Any>({ head: '', amount: '', description: '', via: 'direct' });
  const [rep, setRep] = useState<Any>({ period: '', report_url: '', summary: '' });
  const [stf, setStf] = useState<Any>({ name: '', role: 'JRF' });
  const [sanction, setSanction] = useState<Any>({ amount: '', letter: '' });
  const run = useRun();
  const p: Any = res.data?.data;
  useTitle(p?.title ?? 'Project');
  if (!p) return <PageHeader title="Project" />;
  const act = (action: string, extra: Any = {}) => run.mutate(() => ra.projectAction(id, { action, ...extra }), { onSuccess: () => toast.success(action), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title={p.title} description={`${p.funding_agency ?? ''} ${p.scheme ? `· ${p.scheme}` : ''} · PI ${p.pi_name ?? ''}`} actions={<StatusBadge status={p.status} />} />
      <div className="grid gap-4 md:grid-cols-4"><Stat label="Sanctioned" value={inr(p.sanctioned_paise)} /><Stat label="Received" value={inr(p.received_paise)} /><Stat label="Utilised" value={inr(p.utilised_paise)} /><Stat label="Utilisation" value={`${p.utilisation_pct}%`} /></div>
      <Section title="Lifecycle" action={<div className="flex gap-2">
        {p.status === 'applied' && <><Input className="w-36" placeholder="Sanction ₹" value={sanction.amount} onChange={(e) => setSanction({ ...sanction, amount: e.target.value })} /><Input className="w-48" placeholder="Letter URL" value={sanction.letter} onChange={(e) => setSanction({ ...sanction, letter: e.target.value })} /><Button size="sm" onClick={() => act('sanction', { sanctioned_paise: sanction.amount ? Math.round(Number(sanction.amount) * 100) : undefined, sanction_letter_url: sanction.letter || undefined })}>Sanction</Button></>}
        {p.status === 'sanctioned' && <Button size="sm" onClick={() => act('start')}>Start</Button>}
        {p.status === 'ongoing' && <Button size="sm" onClick={() => act('complete')}>Complete</Button>}
        {p.status === 'completed' && <Button size="sm" onClick={() => act('close')}>Close (UC)</Button>}
      </div>}>
        <p className="text-sm text-muted-foreground">Grant ledger: {p.grant_ledger_id ? <Link className="text-primary underline" to={`/admin/accounting/grants`}>linked</Link> : 'pending sanction'}{p.workflow_instance_id ? ' · sanction workflow running / done' : ''}</p>
      </Section>
      <Section title="Budget heads (ledger)"><SimpleTable head={['Head', 'Allocated', 'Utilised', 'Available', '']} rows={(p.budget_heads ?? []).map((h: Any) => [h.name, inr(h.allocated_paise), inr(h.utilised_paise), inr(h.available_paise), <div key="b" className="w-32"><Bar pct={h.allocated_paise ? (100 * (h.utilised_paise ?? 0)) / h.allocated_paise : 0} /></div>])} /></Section>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Expense request">
          <div className="flex flex-wrap gap-2"><select className={sel} value={x.head} onChange={(e) => setX({ ...x, head: e.target.value })}><option value="">Head</option>{(p.budget_heads ?? []).map((h: Any) => <option key={h.name}>{h.name}</option>)}</select><Input className="w-28" placeholder="₹" value={x.amount} onChange={(e) => setX({ ...x, amount: e.target.value })} /><Input className="w-56" placeholder="Description" value={x.description} onChange={(e) => setX({ ...x, description: e.target.value })} /><select className={sel} value={x.via} onChange={(e) => setX({ ...x, via: e.target.value })}><option value="direct">direct (grant expense)</option><option value="indent">indent (procurement)</option></select><Button size="sm" disabled={!x.head || !x.amount} onClick={() => run.mutate(() => ra.expense(id, { head: x.head, amount_paise: Math.round(Number(x.amount) * 100), description: x.description, via: x.via }), { onSuccess: () => toast.success('Requested'), onError: fail })}>Request</Button></div>
          <SimpleTable head={['Head', 'Amount', 'Via', 'Status']} rows={(p.expense_requests ?? []).map((e: Any) => [e.head, inr(e.amount_paise), e.via, <StatusBadge key="s" status={e.status} />])} />
        </Section>
        <Section title="Reports due">
          <SimpleTable head={['Period', 'Due', '']} rows={(p.reports_due ?? []).map((r: Any) => [r.period, day(r.due_on), r.overdue ? <StatusBadge key="o" status="overdue" /> : ''])} />
          <div className="flex flex-wrap gap-2"><Input className="w-24" placeholder="Period" value={rep.period} onChange={(e) => setRep({ ...rep, period: e.target.value })} /><Input className="w-48" placeholder="Report URL" value={rep.report_url} onChange={(e) => setRep({ ...rep, report_url: e.target.value })} /><Button size="sm" disabled={!rep.period} onClick={() => run.mutate(() => ra.addReport(id, rep), { onSuccess: () => toast.success('Uploaded'), onError: fail })}>Upload</Button></div>
          <SimpleTable head={['Period', 'Summary', 'Submitted']} rows={(p.reports ?? []).map((r: Any) => [r.period, r.summary, day(r.submitted_at)])} />
        </Section>
      </div>
      <Section title="Project staff"><div className="flex gap-2"><Input placeholder="Name" value={stf.name} onChange={(e) => setStf({ ...stf, name: e.target.value })} /><select className={sel} value={stf.role} onChange={(e) => setStf({ ...stf, role: e.target.value })}>{['JRF', 'SRF', 'RA', 'Project Assistant'].map((r) => <option key={r}>{r}</option>)}</select><Button size="sm" disabled={stf.name.length < 2} onClick={() => run.mutate(() => ra.addStaff(id, stf), { onError: fail })}>Add</Button></div><SimpleTable head={['Name', 'Role']} rows={(p.staff ?? []).map((s: Any) => [s.name, s.role])} /></Section>
    </div>
  );
}

// ---- consultancy ---------------------------------------------------------------------------------------------------------------
export function ConsultancyPage() {
  useTitle('Consultancy');
  const res = useQ(['consultancy'], () => ra.consultancies());
  const [f, setF] = useState<Any>({ client: '', title: '', amount: '' });
  const [rc, setRc] = useState<Record<string, string>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Consultancy" description="Institution share from the configured split; receipts through fee invoices; faculty share to payroll." />
      <Section title="Record"><div className="flex flex-wrap gap-2"><Input placeholder="Client" value={f.client} onChange={(e) => setF({ ...f, client: e.target.value })} /><Input className="w-64" placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /><Input className="w-32" placeholder="Value ₹" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /><Button size="sm" disabled={!f.client || !f.amount} onClick={() => run.mutate(() => ra.addConsultancy({ client: f.client, title: f.title || undefined, amount_paise: Math.round(Number(f.amount) * 100) }), { onSuccess: () => toast.success('Recorded'), onError: fail })}>Add</Button></div></Section>
      <Section title="Agreements"><SimpleTable head={['Client', 'Faculty', 'Value', 'Institution', 'Faculty share', 'Received', 'Status', 'Receipt']} rows={list(res.data).map((c: Any) => [c.client, c.staff_name, inr(c.amount_paise), inr(c.institution_share_paise), inr(c.faculty_share_paise), inr(c.received_paise), <StatusBadge key="s" status={c.status} />, <div key="r" className="flex gap-1"><Input className="w-24" placeholder="₹" value={rc[c.id] ?? ''} onChange={(e) => setRc({ ...rc, [c.id]: e.target.value })} /><Button size="sm" variant="outline" disabled={!rc[c.id]} onClick={() => run.mutate(() => ra.receipt(c.id, { amount_paise: Math.round(Number(rc[c.id]) * 100), mode: 'bank_transfer' }), { onSuccess: () => toast.success('Invoiced'), onError: fail })}>Invoice</Button></div>])} /></Section>
    </div>
  );
}

// ---- ethics ----------------------------------------------------------------------------------------------------------------------
export function EthicsPage() {
  useTitle('Ethics committees');
  const com = useQ(['committees'], () => ra.committees());
  const apps = useQ(['ethics-apps'], () => ra.applications());
  const [a, setA] = useState<Any>({ committee_id: '', project_title: '', category: 'expedited' });
  const [dec, setDec] = useState<Record<string, string>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Ethics committees" description="IEC / IAEC / IBSC — member review → chair decision; approvals with validity, renewals and adverse events." />
      <Section title="Committees"><SimpleTable head={['Type', 'Registration', 'Members', 'Applications']} rows={list(com.data).map((c: Any) => [<Chip key="t" text={c.committee_type} />, c.registration_no, (c.members ?? []).map((m: Any) => `${m.name}${m.role === 'chair' ? ' (chair)' : ''}`).join(', '), c.applications])} /></Section>
      <Section title="Submit a protocol"><div className="flex flex-wrap gap-2"><select className={sel} value={a.committee_id} onChange={(e) => setA({ ...a, committee_id: e.target.value })}><option value="">Committee</option>{list(com.data).map((c: Any) => <option key={c.id} value={c.id}>{c.committee_type.toUpperCase()}</option>)}</select><Input className="w-80" placeholder="Project title" value={a.project_title} onChange={(e) => setA({ ...a, project_title: e.target.value })} /><select className={sel} value={a.category} onChange={(e) => setA({ ...a, category: e.target.value })}>{['exempt', 'expedited', 'full_review'].map((c) => <option key={c}>{c}</option>)}</select><Button size="sm" disabled={!a.committee_id || a.project_title.length < 3} onClick={() => run.mutate(() => ra.apply(a), { onSuccess: () => toast.success('Submitted'), onError: fail })}>Submit</Button></div></Section>
      <Section title="Applications & approvals"><SimpleTable head={['Title', 'PI', 'Category', 'Status', 'Approval', 'Valid to', 'Action']} rows={list(apps.data).map((x: Any) => [x.project_title, x.pi_name, x.category, <StatusBadge key="s" status={x.status} />, x.approval_no, day(x.valid_to), x.decision ? (x.decision === 'approved' ? <Button key="r" size="sm" variant="outline" onClick={() => run.mutate(() => ra.amend(x.id, 'renew', { description: 'Renewal' }), { onError: fail })}>Renew</Button> : null) : <div key="d" className="flex gap-1"><select className={sel} value={dec[x.id] ?? 'approved'} onChange={(e) => setDec({ ...dec, [x.id]: e.target.value })}>{['approved', 'revise', 'rejected'].map((d) => <option key={d}>{d}</option>)}</select><Button size="sm" variant="outline" onClick={() => run.mutate(() => ra.review(x.id, { decision: dec[x.id] ?? 'approved' }), { onError: fail })}>Review</Button><Button size="sm" onClick={() => run.mutate(() => ra.decide(x.id, { decision: dec[x.id] ?? 'approved' }), { onError: fail })}>Decide</Button></div>])} /></Section>
    </div>
  );
}

// ---- incentives ------------------------------------------------------------------------------------------------------------------
export function IncentivesPage({ mine = false }: { mine?: boolean }) {
  useTitle('Incentives');
  const slabs = useQ(['slabs'], () => ra.slabs());
  const res = useQ(['incentives', mine], () => (mine ? ra.myIncentives() : ra.incentives()));
  const [f, setF] = useState<Any>({ incentive_type: 'publication_incentive', entity_id: '', amount: '', justification: '' });
  const run = useRun();
  const s: Any = slabs.data?.data;
  const submit = () => run.mutate(() => ra.requestIncentive({ incentive_type: f.incentive_type, linked_entity: f.entity_id ? { type: f.incentive_type === 'publication_incentive' ? 'publication' : f.incentive_type === 'patent_filing_support' ? 'patent' : 'conference', id: f.entity_id } : undefined, amount_paise: f.amount ? Math.round(Number(f.amount) * 100) : undefined, justification: f.justification || undefined }), { onSuccess: () => toast.success('Requested'), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title={mine ? 'My incentives' : 'Incentives'} description="Seed grants, publication incentives (slab by indexing / author position), travel grants, patent support — HOD → research cell → dean above the threshold." />
      {s && <Section title="Slabs & caps"><SimpleTable head={['Indexing', 'First / corresponding author', 'Co-author']} rows={(s.slabs ?? []).map((x: Any) => [x.indexing, `₹${x.first_author}`, `₹${x.co_author}`])} /><p className="text-xs text-muted-foreground">Seed grant ≤ {inr(s.seed_grant_max_paise)} · travel ≤ {inr(s.travel_grant_max_paise)} · annual cap {inr(s.annual_cap_paise)} · dean step above {inr(s.dean_threshold_paise)}</p></Section>}
      <Section title="Request"><div className="flex flex-wrap gap-2"><select className={sel} value={f.incentive_type} onChange={(e) => setF({ ...f, incentive_type: e.target.value })}>{['publication_incentive', 'travel_grant', 'seed_grant', 'patent_filing_support'].map((t) => <option key={t}>{t}</option>)}</select><Input className="w-72" placeholder="Linked publication / patent id" value={f.entity_id} onChange={(e) => setF({ ...f, entity_id: e.target.value })} />{f.incentive_type !== 'publication_incentive' && <Input className="w-32" placeholder="Amount ₹" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />}<Input className="w-64" placeholder="Justification" value={f.justification} onChange={(e) => setF({ ...f, justification: e.target.value })} /><Button size="sm" onClick={submit}>Request</Button></div></Section>
      <Section title="Requests"><SimpleTable head={['Type', 'Faculty', 'Amount', 'Eligible', 'Status', 'Step', 'Action']} rows={list(res.data).map((r: Any) => [r.incentive_type, r.staff_name, inr(r.amount_paise), r.eligible_paise != null ? inr(r.eligible_paise) : '—', <StatusBadge key="s" status={r.status} />, r.current_step ?? '—', <div key="a" className="flex gap-1">{r.can_act && <><Button size="sm" onClick={() => run.mutate(() => ra.decideIncentive(r.id, { decision: 'approve' }), { onError: fail })}>Approve</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => ra.decideIncentive(r.id, { decision: 'reject' }), { onError: fail })}>Reject</Button></>}{!mine && r.status === 'approved' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ra.disburse(r.id, { via: 'payroll' }), { onSuccess: () => toast.success('Disbursed'), onError: fail })}>Disburse</Button>}</div>])} /></Section>
    </div>
  );
}

// ---- FDP & awards ------------------------------------------------------------------------------------------------------------------
export function FdpPage() {
  useTitle('FDP & awards');
  const [year, setYear] = useState(YEAR);
  const res = useQ(['fdp', year], () => ra.fdp({ year }));
  const comp = useQ(['compliance', year], () => ra.compliance({ year }));
  const aw = useQ(['awards'], () => ra.awards());
  const [f, setF] = useState<Any>({ title: '', event_type: 'fdp', role: 'attended', hours: '', from_on: '', to_on: '', certificate_url: '' });
  const [a, setA] = useState<Any>({ title: '', agency: '', level: 'national' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="FDP & awards" description="Attended / organised / resource person with hours; in-house FDP events create records automatically; compliance against the annual target." actions={<Input className="w-24" value={year} onChange={(e) => setYear(Number(e.target.value) || YEAR)} />} />
      <Section title="Add FDP record"><div className="flex flex-wrap gap-2"><Input className="w-72" placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /><select className={sel} value={f.event_type} onChange={(e) => setF({ ...f, event_type: e.target.value })}>{['fdp', 'workshop', 'conference', 'certification', 'mooc', 'industry_training'].map((t) => <option key={t}>{t}</option>)}</select><select className={sel} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{['attended', 'organised', 'resource_person'].map((t) => <option key={t}>{t}</option>)}</select><Input className="w-20" placeholder="Hours" value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} /><Input type="date" className="w-40" value={f.from_on} onChange={(e) => setF({ ...f, from_on: e.target.value })} /><Input type="date" className="w-40" value={f.to_on} onChange={(e) => setF({ ...f, to_on: e.target.value })} /><Input className="w-56" placeholder="Certificate URL" value={f.certificate_url} onChange={(e) => setF({ ...f, certificate_url: e.target.value })} /><Button size="sm" disabled={f.title.length < 3} onClick={() => run.mutate(() => ra.addFdp({ ...f, hours: f.hours ? Number(f.hours) : undefined, from_on: f.from_on || undefined, to_on: f.to_on || undefined, certificate_url: f.certificate_url || undefined }), { onSuccess: () => toast.success('Recorded'), onError: fail })}>Add</Button></div></Section>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Records"><SimpleTable head={['Faculty', 'Title', 'Role', 'Hours', 'From', 'Auto']} rows={list(res.data).map((r: Any) => [r.staff_name, r.title, r.role, r.hours, day(r.from_on), r.auto_created ? 'event' : ''])} /></Section>
        <Section title="Compliance"><SimpleTable head={['Faculty', 'Hours', 'Target', 'Records', '']} rows={list(comp.data).map((r: Any) => [r.name, r.hours, r.target, r.records, <StatusBadge key="c" status={r.compliant ? 'compliant' : 'short'} />])} /></Section>
      </div>
      <Section title="Awards"><div className="flex flex-wrap gap-2"><Input className="w-64" placeholder="Award" value={a.title} onChange={(e) => setA({ ...a, title: e.target.value })} /><Input placeholder="Agency" value={a.agency} onChange={(e) => setA({ ...a, agency: e.target.value })} /><select className={sel} value={a.level} onChange={(e) => setA({ ...a, level: e.target.value })}>{['institution', 'state', 'national', 'international'].map((l) => <option key={l}>{l}</option>)}</select><Button size="sm" disabled={a.title.length < 3} onClick={() => run.mutate(() => ra.addAward(a), { onSuccess: () => toast.success('Recorded'), onError: fail })}>Add</Button></div><SimpleTable head={['Faculty', 'Award', 'Agency', 'Year', 'Level', 'Verified']} rows={list(aw.data).map((r: Any) => [r.staff_name, r.title, r.agency, r.year, r.level, r.is_verified ? 'yes' : ''])} /></Section>
    </div>
  );
}

// ---- MoUs --------------------------------------------------------------------------------------------------------------------------
export function MousPage() {
  useTitle('MoUs & collaborations');
  const [f, setF] = useState<Any>({ status: '', expiring: false, q: '' });
  const res = useQ(['mous', f], () => ra.mous({ status: f.status || undefined, expiring: f.expiring || undefined, q: f.q || undefined }));
  const report = useQ(['mou-activity'], () => ra.activityReport(YEAR));
  const [n, setN] = useState<Any>({ partner: '', partner_type: 'industry', mou_type: 'research', country: 'India' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="MoUs & collaborations" description="Research cell → legal (when enabled) → principal; expiry chips; renewals create a new version." />
      <Section title="Draft an MoU"><div className="flex flex-wrap gap-2"><Input className="w-64" placeholder="Partner" value={n.partner} onChange={(e) => setN({ ...n, partner: e.target.value })} /><select className={sel} value={n.partner_type} onChange={(e) => setN({ ...n, partner_type: e.target.value })}>{['industry', 'university', 'government', 'ngo'].map((t) => <option key={t}>{t}</option>)}</select><select className={sel} value={n.mou_type} onChange={(e) => setN({ ...n, mou_type: e.target.value })}>{['academic', 'research', 'placement', 'exchange'].map((t) => <option key={t}>{t}</option>)}</select><Input className="w-32" placeholder="Country" value={n.country} onChange={(e) => setN({ ...n, country: e.target.value })} /><Button size="sm" disabled={n.partner.length < 2} onClick={() => run.mutate(() => ra.addMou(n), { onSuccess: () => toast.success('Drafted'), onError: fail })}>Draft</Button></div></Section>
      <Section title="Register">
        <div className="flex flex-wrap items-center gap-2"><select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{['draft', 'submitted', 'approved', 'active', 'expired', 'renewed'].map((s) => <option key={s}>{s}</option>)}</select><label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.expiring} onChange={(e) => setF({ ...f, expiring: e.target.checked })} />Expiring</label><Input className="w-56" placeholder="Partner" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /></div>
        <SimpleTable head={['Partner', 'Type', 'MoU', 'Valid to', 'Expiry', 'Collaborations', 'Status', 'v']} rows={list(res.data).map((m: Any) => [<Link key="l" className="text-primary underline" to={`/admin/research/mous/${m.id}`}>{m.partner}</Link>, m.partner_type, m.mou_type, day(m.valid_to), <StatusBadge key="e" status={m.expiry} />, m.collaborations, <StatusBadge key="s" status={m.status} />, m.version])} />
      </Section>
      <Section title={`Activity report ${YEAR}`}><SimpleTable head={['Partner', 'Type', 'Status', 'Collaborations', 'Functional']} rows={list(report.data).map((r: Any) => [r.partner, r.mou_type, r.status, r.collaborations, r.functional ? 'yes' : 'no'])} /></Section>
    </div>
  );
}

export function MouPage() {
  const { id = '' } = useParams();
  const res = useQ(['mou', id], () => ra.mou(id));
  const collabs = useQ(['mou-collabs', id], () => ra.mouCollabs(id));
  const [sign, setSign] = useState<Any>({ signed_on: '', valid_to: '', document_url: '' });
  const [c, setC] = useState<Any>({ title: '', collaboration_type: 'joint_research' });
  const run = useRun();
  const m: Any = res.data?.data;
  useTitle(m?.partner ?? 'MoU');
  if (!m) return <PageHeader title="MoU" />;
  return (
    <div className="space-y-4">
      <PageHeader title={m.partner} description={`${m.partner_type} · ${m.mou_type} · v${m.version}`} actions={<div className="flex gap-2"><StatusBadge status={m.status} />{['draft', 'rejected'].includes(m.status) && <Button size="sm" onClick={() => run.mutate(() => ra.submitMou(id), { onSuccess: () => toast.success('Submitted'), onError: fail })}>Submit</Button>}{['active', 'expired'].includes(m.status) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ra.renewMou(id), { onSuccess: () => toast.success('Renewal drafted'), onError: fail })}>Renew</Button>}</div>} />
      {m.status === 'approved' && <Section title="Record signing"><div className="flex flex-wrap gap-2"><Input type="date" value={sign.signed_on} onChange={(e) => setSign({ ...sign, signed_on: e.target.value })} /><Input type="date" value={sign.valid_to} onChange={(e) => setSign({ ...sign, valid_to: e.target.value })} /><Input className="w-64" placeholder="Signed copy URL" value={sign.document_url} onChange={(e) => setSign({ ...sign, document_url: e.target.value })} /><Button size="sm" disabled={!sign.signed_on || !sign.valid_to} onClick={() => run.mutate(() => ra.signMou(id, { ...sign, document_url: sign.document_url || undefined }), { onSuccess: () => toast.success('Signed'), onError: fail })}>Sign</Button></div></Section>}
      <div className="grid gap-4 md:grid-cols-3"><Stat label="Signed" value={day(m.signed_on)} /><Stat label="Valid to" value={day(m.valid_to)} /><Stat label="Coordinator" value={m.coordinator_name} /></div>
      <Section title="Activities plan"><SimpleTable head={['Activity', 'Planned']} rows={(m.activities ?? []).map((a: Any) => [a.title, a.planned])} />{m.document_url && <a className="text-sm text-primary underline" href={m.document_url} target="_blank" rel="noreferrer">MoU document</a>}</Section>
      <Section title="Collaborations"><div className="flex gap-2"><Input className="w-72" placeholder="Title" value={c.title} onChange={(e) => setC({ ...c, title: e.target.value })} /><select className={sel} value={c.collaboration_type} onChange={(e) => setC({ ...c, collaboration_type: e.target.value })}>{['joint_research', 'exchange', 'joint_degree', 'internship'].map((t) => <option key={t}>{t}</option>)}</select><Button size="sm" disabled={c.title.length < 3} onClick={() => run.mutate(() => ra.addCollab(id, c), { onSuccess: () => toast.success('Recorded'), onError: fail })}>Add</Button></div><SimpleTable head={['Title', 'Type', 'From', 'To', 'Outcomes']} rows={list(collabs.data).map((x: Any) => [x.title, x.collaboration_type, day(x.from_on), day(x.to_on), (x.outcomes ?? []).join('; ')])} /></Section>
    </div>
  );
}

// ---- start-ups -------------------------------------------------------------------------------------------------------------------
export function StartupsPage() {
  useTitle('Incubation');
  const res = useQ(['startups'], () => ra.startups());
  const [n, setN] = useState<Any>({ name: '', sector: '', founder: '', founder_type: 'student' });
  const run = useRun();
  const next: Record<string, string> = { idea: 'prototype', prototype: 'incubated', incubated: 'funded', funded: 'graduated' };
  return (
    <div className="space-y-4">
      <PageHeader title="Incubation & start-ups" description="Founders (students / alumni / faculty), stage progression, funding, mentors." />
      <Section title="Register"><div className="flex flex-wrap gap-2"><Input placeholder="Name" value={n.name} onChange={(e) => setN({ ...n, name: e.target.value })} /><Input placeholder="Sector" value={n.sector} onChange={(e) => setN({ ...n, sector: e.target.value })} /><Input placeholder="Founder" value={n.founder} onChange={(e) => setN({ ...n, founder: e.target.value })} /><select className={sel} value={n.founder_type} onChange={(e) => setN({ ...n, founder_type: e.target.value })}>{['student', 'alumni', 'faculty'].map((t) => <option key={t}>{t}</option>)}</select><Button size="sm" disabled={n.name.length < 2} onClick={() => run.mutate(() => ra.addStartup({ name: n.name, sector: n.sector || undefined, founders: n.founder ? [{ name: n.founder, type: n.founder_type }] : [] }), { onSuccess: () => toast.success('Registered'), onError: fail })}>Add</Button></div></Section>
      <Section title="Register"><SimpleTable head={['Name', 'Sector', 'Founders', 'Stage', 'Funding', 'Mentor', '']} rows={list(res.data).map((s: Any) => [s.name, s.sector, (s.founders ?? []).map((f: Any) => `${f.name} (${f.type})`).join(', '), <StatusBadge key="s" status={s.stage} />, inr(s.funding_paise), s.mentor_name, next[s.stage] ? <Button key="b" size="sm" variant="outline" onClick={() => run.mutate(() => ra.stage(s.id, { stage: next[s.stage] }), { onError: fail })}>→ {next[s.stage]}</Button> : null])} /></Section>
    </div>
  );
}

// ---- API score -------------------------------------------------------------------------------------------------------------------
function Breakdown({ score }: { score: Any }) {
  if (!score) return <p className="text-sm text-muted-foreground">Not computed yet.</p>;
  return (
    <div className="space-y-2">
      <p className="text-sm">Total <b>{score.total}</b> · {score.scheme} · {score.period}</p>
      <SimpleTable head={['Category', 'Items', 'Points']} rows={Object.entries(score.breakdown ?? {}).map(([k, v]: Any) => [v.label ?? k, (v.items ?? []).length, v.points])} />
    </div>
  );
}

export function ApiScorePage() {
  useTitle('API score');
  const [f, setF] = useState<Any>({ period_from: `${YEAR - 1}-04-01`, period_to: `${YEAR}-03-31`, department_id: '' });
  const rank = useQ(['rankings'], () => ra.rankings());
  const [staff, setStaff] = useState('');
  const sc = useQ(['api', staff], () => ra.apiScore({ staff_id: staff }), !!staff);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="API / CAS score" description="UGC CAS 2018 categories with indexing / author-position weights and caps; feeds Phase 06 appraisals and CAS." />
      <Section title="Compute"><div className="flex flex-wrap gap-2"><Input type="date" value={f.period_from} onChange={(e) => setF({ ...f, period_from: e.target.value })} /><Input type="date" value={f.period_to} onChange={(e) => setF({ ...f, period_to: e.target.value })} /><Input className="w-72" placeholder="Department id (blank = all in scope)" value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })} /><Button size="sm" onClick={() => run.mutate(() => ra.computeApi({ ...f, department_id: f.department_id || undefined }), { onSuccess: (r: Any) => toast.success(`${(r.data ?? []).length} computed`), onError: fail })}>Compute</Button></div></Section>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Rankings"><SimpleTable head={['#', 'Faculty', 'Score', '']} rows={list(rank.data).map((r: Any) => [r.rank, r.name, r.total, <Button key="v" size="sm" variant="outline" onClick={() => setStaff(r.staff_id)}>Breakdown</Button>])} /></Section>
        <Section title="Breakdown"><Breakdown score={sc.data?.data} /></Section>
      </div>
    </div>
  );
}

// ---- stats -------------------------------------------------------------------------------------------------------------------------
export function StatsPage() {
  useTitle('Research stats');
  const [year, setYear] = useState<number | ''>('');
  const res = useQ(['stats', year], () => ra.stats({ year: year || undefined }));
  const [criterion, setCriterion] = useState('3.3');
  const run = useRun();
  const s: Any = res.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Research stats" description="Verified records only · NAAC 3.x and NIRF RP (PU, QP, IPR, FPPP)." actions={<div className="flex gap-2"><Input className="w-24" placeholder="Year" value={year} onChange={(e) => setYear(Number(e.target.value) || '')} />{year && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ra.stats({ year, publish: true }), { onSuccess: () => toast.success('Metrics published'), onError: fail })}>Publish metrics</Button>}</div>} />
      {s && (
        <>
          <div className="grid gap-4 md:grid-cols-5"><Stat label="Publications" value={s.publications} /><Stat label="Per teacher" value={s.per_teacher} /><Stat label="Grants" value={inr(s.grants_amount_paise)} /><Stat label="Consultancy" value={inr(s.consultancy_revenue_paise)} /><Stat label="Start-ups" value={s.startups} /></div>
          <div className="grid gap-4 md:grid-cols-3">
            <Section title="By indexing"><Bars data={s.publications_by_indexing} /></Section>
            <Section title="Patents"><Bars data={s.patents} /></Section>
            <Section title="Projects"><Bars data={s.projects_by_status} /></Section>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Section title="NIRF RP"><SimpleTable head={['Parameter', 'Value']} rows={[['PU (per faculty)', s.nirf_rp?.PU], ['QP indexed', s.nirf_rp?.QP?.indexed_publications], ['QP citations / paper', s.nirf_rp?.QP?.citations_per_paper], ['IPR granted', s.nirf_rp?.IPR?.granted], ['FPPP research', inr(s.nirf_rp?.FPPP?.sponsored_research_paise)], ['FPPP consultancy', inr(s.nirf_rp?.FPPP?.consultancy_paise)]]} /></Section>
            <Section title="FDP & MoUs"><SimpleTable head={['Metric', 'Value']} rows={[['FDP participants', s.fdp?.participants], ['FDP participation %', s.fdp?.participation_pct], ['FDP hours', s.fdp?.hours], ['MoUs active', s.mous?.active], ['MoUs functional', s.mous?.functional]]} /></Section>
          </div>
          <Section title="By department"><SimpleTable head={['Department', 'Teachers', 'Publications', 'Grants']} rows={(s.by_department ?? []).map((d: Any) => [d.department_id, d.teachers, d.publications, inr(d.grants_paise)])} /></Section>
        </>
      )}
      <Section title="Reports & evidence"><div className="flex flex-wrap gap-2">{['publications', 'projects', 'consultancy', 'patents', 'fdp', 'mous', 'nirf_rp'].map((k) => <Button key={k} size="sm" variant="outline" onClick={() => run.mutate(() => ra.report(k), { onSuccess: () => toast.success('Report queued (Jobs)'), onError: fail })}>{k}</Button>)}<Input className="w-20" value={criterion} onChange={(e) => setCriterion(e.target.value)} /><Button size="sm" onClick={() => run.mutate(() => ra.evidencePack(criterion, year || undefined), { onSuccess: () => toast.success('Evidence pack queued (Jobs)'), onError: fail })}>Evidence pack</Button></div></Section>
    </div>
  );
}

// ---- faculty portal ------------------------------------------------------------------------------------------------------------------
const TABS = ['profile', 'publications', 'patents', 'projects', 'incentives', 'fdp', 'api'] as const;
export function FacultyResearchPage() {
  useTitle('My research');
  const [tab, setTab] = useState<(typeof TABS)[number]>('profile');
  const prof = useQ(['my-profile'], () => ra.myProfile());
  const pubs = useQ(['my-pubs'], () => ra.publications({ scope: 'self', per_page: 200 }), tab === 'publications');
  const projects = useQ(['my-projects'], () => ra.myProjects(), tab === 'projects');
  const api = useQ(['my-api'], () => ra.apiScore({ staff_id: 'self' }), tab === 'api');
  const p: Any = prof.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="My research" description="Publications, patents, projects, incentives, FDP and the API score breakdown." />
      <div className="flex flex-wrap gap-1">{TABS.map((t) => <Button key={t} size="sm" variant={t === tab ? 'default' : 'outline'} onClick={() => setTab(t)}>{t}</Button>)}</div>
      {tab === 'profile' && p && <div className="grid gap-4 md:grid-cols-4"><Stat label="Publications" value={`${p.verified_publications}/${p.publications}`} /><Stat label="Citations / h-index" value={`${p.citations} / ${p.h_index}`} /><Stat label="Projects (ongoing)" value={`${p.projects} (${p.ongoing_projects})`} /><Stat label="Funding" value={inr(p.funding_paise)} /><Stat label="Consultancy" value={inr(p.consultancy_paise)} /><Stat label="Patents (granted)" value={`${p.patents} (${p.patents_granted})`} /><Stat label="FDP hours" value={p.fdp_hours} /><Stat label="API score" value={p.api_score ?? '—'} /></div>}
      {tab === 'publications' && <><Section title="Add"><PublicationForm /></Section><ImportWizard /><Section title="My publications"><SimpleTable head={['Title', 'Venue', 'Year', 'Indexing', 'State']} rows={list(pubs.data).map((x: Any) => [x.title, x.venue, x.year, <Chip key="i" text={x.indexing} />, <StatusBadge key="s" status={x.is_verified ? 'verified' : x.verification_level} />])} /></Section></>}
      {tab === 'patents' && <PatentsPage />}
      {tab === 'projects' && <Section title="My projects (PI dashboard)"><SimpleTable head={['Title', 'Agency', 'Sanctioned', 'Balance', 'Utilisation', 'Status']} rows={list(projects.data).map((x: Any) => [<Link key="l" className="text-primary underline" to={`/faculty/research/projects/${x.id}`}>{x.title}</Link>, x.funding_agency, inr(x.sanctioned_paise), inr(x.received_paise - x.utilised_paise), <div key="u" className="w-32"><Bar pct={x.utilisation_pct} /></div>, <StatusBadge key="s" status={x.status} />])} /></Section>}
      {tab === 'incentives' && <IncentivesPage mine />}
      {tab === 'fdp' && <FdpPage />}
      {tab === 'api' && <Section title="API score"><Breakdown score={api.data?.data} /></Section>}
    </div>
  );
}
