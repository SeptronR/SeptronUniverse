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
import { alApi as aa } from '../api';

// Phase 29 web screens (Prompts/29 §29.9). Consent projection, verification and scopes are enforced by the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['alumni', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['alumni'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const inr = (p?: number | null) => `₹${((p ?? 0) / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[80px] w-full rounded-md border bg-background p-2 text-sm';
const FIELDS = ['name', 'batch', 'program', 'city', 'country', 'company', 'designation', 'linkedin_url', 'email', 'phone'];
const currentFy = () => {
  const d = new Date();
  const s = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${s}-${String((s + 1) % 100).padStart(2, '0')}`;
};

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function Progress({ pct }: { pct: number }) {
  return <div className="h-2 w-full rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${Math.min(100, pct)}%` }} /></div>;
}
function Bars({ data }: { data?: Record<string, number> }) {
  const rows = Object.entries(data ?? {});
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return <div className="space-y-1">{rows.map(([k, v]) => <div key={k} className="flex items-center gap-2 text-sm"><span className="w-32 truncate text-muted-foreground">{k}</span><div className="h-3 rounded bg-primary/70" style={{ width: `${Math.max(2, (100 * v) / max)}%` }} /><span>{v}</span></div>)}</div>;
}

// ---- coordinator: profiles ------------------------------------------------------------------------------------------------
export function ProfilesPage() {
  useTitle('Alumni profiles');
  const [f, setF] = useState<Any>({ batch: '', status: '', q: '' });
  const [scope, setScope] = useState<string | undefined>();
  const [merge, setMerge] = useState({ keep_id: '', merge_id: '' });
  const [csv, setCsv] = useState('');
  const res = useQ(['profiles', f, scope], () => aa.profiles({ batch: f.batch || undefined, status: f.status || undefined, q: f.q || undefined, scope }));
  const run = useRun();
  const importCsv = () => {
    const rows = csv.split('\n').map((l) => l.split(',').map((c) => c.trim())).filter((c) => c.length >= 3 && c[0]).map(([registration_number, name, year, program_code, email, phone]) => ({ registration_number, name, graduation_year: Number(year), program_code: program_code || undefined, email: email || undefined, phone: phone || undefined }));
    run.mutate(() => aa.importRows({ rows }), { onSuccess: (r: Any) => { toast.success(`Imported: ${r.data.created} new, ${r.data.linked} linked, ${r.data.skipped} skipped`); setCsv(''); }, onError: fail });
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Alumni profiles" description="Claim / verification status, batches and programmes; consents are read-only." actions={<div className="flex gap-2"><ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} /><Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.exportJob({ scope }), { onSuccess: () => toast.success('Export queued (Jobs)'), onError: fail })}>Export</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.claimLinks(), { onSuccess: () => toast.success('Claim links queued'), onError: fail })}>Send claim links</Button></div>} />
      <Section title="Filters">
        <div className="flex flex-wrap gap-2">
          <Input className="w-28" placeholder="Batch" value={f.batch} onChange={(e) => setF({ ...f, batch: e.target.value })} />
          <select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{['verified', 'unverified', 'unclaimed', 'claimed', 'rejected'].map((s) => <option key={s}>{s}</option>)}</select>
          <Input className="w-64" placeholder="Name, reg. no. or company" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        </div>
      </Section>
      <Section title={`Profiles (${(res.data as Any)?.meta?.pagination?.total ?? list(res.data).length})`}>
        <SimpleTable head={['Name', 'Reg. no.', 'Batch', 'Programme', 'City', 'Company', 'Status', 'Mentor', 'Engagement']} rows={list(res.data).map((p: Any) => [<Link key="l" className="text-primary underline" to={`/admin/alumni/profiles/${p.id}`}>{p.name}</Link>, p.registration_number, p.graduation_year, p.program, p.city, p.current_company, <StatusBadge key="s" status={p.claim_status} />, p.willing_to_mentor ? 'yes' : '', p.engagement_score])} />
      </Section>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Merge duplicates">
          <div className="flex flex-wrap gap-2"><Input placeholder="Keep profile id" value={merge.keep_id} onChange={(e) => setMerge({ ...merge, keep_id: e.target.value })} /><Input placeholder="Merge profile id" value={merge.merge_id} onChange={(e) => setMerge({ ...merge, merge_id: e.target.value })} /><Button size="sm" disabled={!merge.keep_id || !merge.merge_id} onClick={() => run.mutate(() => aa.merge(merge), { onSuccess: () => toast.success('Merged'), onError: fail })}>Merge</Button></div>
        </Section>
        <Section title="Import legacy alumni (CSV: reg no, name, year, programme code, email, phone)">
          <textarea className={area} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder="2015CS001, Asha Rao, 2015, BTECH-CSE, asha@example.com, +919800000000" />
          <Button size="sm" disabled={!csv.trim()} onClick={importCsv}>Import</Button>
        </Section>
      </div>
    </div>
  );
}

export function ProfilePage() {
  const { id = '' } = useParams();
  const res = useQ(['profile', id], () => aa.profile(id));
  const donations = useQ(['profile-donations', id], () => aa.donor(`alumni:${id}`), !!id);
  const [remarks, setRemarks] = useState('');
  const run = useRun();
  const p: Any = res.data?.data;
  useTitle(p?.name ?? 'Alumni profile');
  if (!p) return <PageHeader title="Alumni profile" />;
  return (
    <div className="space-y-4">
      <PageHeader title={p.name} description={`${p.registration_number ?? ''} · ${p.program ?? ''} · ${p.graduation_year ?? ''}`} actions={<StatusBadge status={p.claim_status} />} />
      <div className="grid gap-4 md:grid-cols-4"><Stat label="Completeness" value={`${p.completeness}%`} /><Stat label="Engagement" value={p.engagement_score} /><Stat label="Company" value={p.current_company} /><Stat label="City" value={[p.city, p.country].filter(Boolean).join(', ')} /></div>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Contacts & consents (read-only)">
          <SimpleTable head={['Field', 'Value']} rows={[['Email', p.email], ['Phone', p.phone], ['LinkedIn', p.linkedin_url], ['Contact consent', p.consent_contact ? 'yes' : 'no'], ['Directory fields', (p.consent_directory_fields ?? []).join(', ') || 'none'], ['Mentor / recruiter', `${p.willing_to_mentor ? 'mentor' : '—'} / ${p.willing_to_recruit ? 'recruiter' : '—'}`], ['Chapter', p.chapter]]} />
        </Section>
        <Section title="Verification">
          <Input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
          <div className="flex gap-2"><Button size="sm" onClick={() => run.mutate(() => aa.verify(id, { approve: true, remarks }), { onSuccess: () => toast.success('Verified'), onError: fail })}>Verify</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.verify(id, { approve: false, remarks }), { onSuccess: () => toast.success('Rejected'), onError: fail })}>Reject</Button></div>
        </Section>
      </div>
      <Section title="Employment"><SimpleTable head={['Company', 'Designation', 'From', 'To', 'Current']} rows={(p.employment ?? []).map((j: Any) => [j.company, j.designation, day(j.from_on), day(j.to_on), j.is_current ? 'yes' : ''])} /></Section>
      <Section title="Donations"><SimpleTable head={['Date', 'Campaign', 'Amount', 'Mode', 'Receipt']} rows={(donations.data?.data?.donations ?? []).map((d: Any) => [day(d.on_date), d.campaign, inr(d.amount_paise), d.mode, d.receipt_no ?? '—'])} /></Section>
    </div>
  );
}

// ---- directory ------------------------------------------------------------------------------------------------------------------
export function DirectoryPage({ portal = false }: { portal?: boolean }) {
  useTitle('Alumni directory');
  const [f, setF] = useState<Any>({ q: '', city: '', company: '', batch: '', willing_to_mentor: false, willing_to_recruit: false });
  const res = useQ(['directory', f], () => aa.directory({ q: f.q || undefined, city: f.city || undefined, company: f.company || undefined, batch: f.batch || undefined, willing_to_mentor: f.willing_to_mentor || undefined, willing_to_recruit: f.willing_to_recruit || undefined }));
  const [msg, setMsg] = useState<Record<string, string>>({});
  const run = useRun();
  const page: Any = res.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Alumni directory" description={portal ? 'Find classmates — only what each alumnus chose to share is shown.' : 'Consented fields only · mentor and recruiter finder.'} />
      <Section title="Search">
        <div className="flex flex-wrap items-center gap-2">
          <Input className="w-56" placeholder="Search" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
          <Input className="w-40" placeholder="City" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} />
          <Input className="w-40" placeholder="Company" value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} />
          <Input className="w-24" placeholder="Batch" value={f.batch} onChange={(e) => setF({ ...f, batch: e.target.value })} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.willing_to_mentor} onChange={(e) => setF({ ...f, willing_to_mentor: e.target.checked })} />Mentors</label>
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.willing_to_recruit} onChange={(e) => setF({ ...f, willing_to_recruit: e.target.checked })} />Recruiters</label>
        </div>
        <div className="grid gap-4 md:grid-cols-2"><Bars data={page.facets?.city} /><Bars data={page.facets?.company} /></div>
      </Section>
      <Section title={`Alumni (${page.total ?? 0})`}>
        <SimpleTable head={['Name', 'Batch', 'Programme', 'City', 'Company', 'Contact', '']} rows={(page.items ?? []).map((e: Any) => [e.fields.name ?? '—', e.fields.batch, e.fields.program, e.fields.city, [e.fields.designation, e.fields.company].filter(Boolean).join(' @ '), e.fields.email ?? (e.contactable ? 'via request' : '—'), e.contactable ? <div key="c" className="flex gap-1"><Input className="w-48" placeholder="Message" value={msg[e.id] ?? ''} onChange={(ev) => setMsg({ ...msg, [e.id]: ev.target.value })} /><Button size="sm" disabled={(msg[e.id] ?? '').length < 5} onClick={() => run.mutate(() => aa.contact(e.id, msg[e.id]), { onSuccess: () => { toast.success('Request relayed'); setMsg({ ...msg, [e.id]: '' }); }, onError: fail })}>Send</Button></div> : ''])} />
      </Section>
    </div>
  );
}

// ---- events ----------------------------------------------------------------------------------------------------------------------
export function EventsPage() {
  useTitle('Alumni events');
  const res = useQ(['events'], () => aa.events());
  const [form, setForm] = useState<Any>({ title: '', event_type: 'reunion', held_on: '', venue: '', registration_fee_paise: 0 });
  const [invite, setInvite] = useState<Record<string, string>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Alumni events" description="Reunions, chapter meets, webinars and mentorship on the Events engine; registrations and fees via Events." />
      <Section title="Create event">
        <div className="flex flex-wrap items-end gap-2">
          <Input className="w-64" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <select className={sel} value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })}>{['meet', 'webinar', 'reunion', 'mentorship'].map((t) => <option key={t}>{t}</option>)}</select>
          <Input type="date" className="w-40" value={form.held_on} onChange={(e) => setForm({ ...form, held_on: e.target.value })} />
          <Input className="w-48" placeholder="Venue" value={form.venue} onChange={(e) => setForm({ ...form, venue: e.target.value })} />
          <Input className="w-32" type="number" placeholder="Fee (₹)" value={form.registration_fee_paise / 100 || ''} onChange={(e) => setForm({ ...form, registration_fee_paise: Math.round(Number(e.target.value) * 100) })} />
          <Button size="sm" disabled={!form.title || !form.held_on} onClick={() => run.mutate(() => aa.createEvent({ ...form, venue: form.venue || undefined }), { onSuccess: () => toast.success('Event created'), onError: fail })}>Create</Button>
        </div>
      </Section>
      <Section title={`Events (${list(res.data).length})`}>
        <SimpleTable head={['Title', 'Type', 'Date', 'Fee', 'Registered', 'Attended', 'Invite batches']} rows={list(res.data).map((e: Any) => [e.title, e.event_type, day(e.held_on), e.registration_fee_paise ? inr(e.registration_fee_paise) : 'free', e.registrations_count, e.attended_count, <div key="i" className="flex gap-1"><Input className="w-32" placeholder="2018, 2019" value={invite[e.id] ?? ''} onChange={(ev) => setInvite({ ...invite, [e.id]: ev.target.value })} /><Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.invite(e.id, { graduation_years: (invite[e.id] ?? '').split(/[\s,]+/).filter(Boolean).map(Number) }), { onSuccess: (r: Any) => toast.success(`${r.data.invited} invited`), onError: fail })}>Invite</Button></div>])} />
      </Section>
    </div>
  );
}

// ---- jobs ----------------------------------------------------------------------------------------------------------------------------
export function JobsAdminPage() {
  useTitle('Alumni jobs');
  const [status, setStatus] = useState('pending');
  const res = useQ(['jobs', status], () => aa.jobs({ status: status || undefined }));
  const [reason, setReason] = useState<Record<string, string>>({});
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Alumni jobs board" description="Moderation queue, expiry and placement lead conversion." actions={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['pending', 'approved', 'rejected', 'expired'].map((s) => <option key={s}>{s}</option>)}</select>} />
      <Section title={`Posts (${list(res.data).length})`}>
        <SimpleTable head={['Title', 'Company', 'Location', 'Posted by', 'Expires', 'Clicks', 'Status', '']} rows={list(res.data).map((j: Any) => [j.title, j.company, j.location, j.posted_by, day(j.expires_on), j.clicks, <StatusBadge key="s" status={j.status} />, <div key="a" className="flex flex-wrap gap-1">{j.status === 'pending' && <><Button size="sm" onClick={() => run.mutate(() => aa.moderate(j.id, { approve: true }), { onSuccess: () => toast.success('Approved'), onError: fail })}>Approve</Button><Input className="w-36" placeholder="Reason" value={reason[j.id] ?? ''} onChange={(e) => setReason({ ...reason, [j.id]: e.target.value })} /><Button size="sm" variant="outline" disabled={!reason[j.id]} onClick={() => run.mutate(() => aa.moderate(j.id, { approve: false, reason: reason[j.id] }), { onSuccess: () => toast.success('Rejected'), onError: fail })}>Reject</Button></>}{j.status === 'approved' && !j.lead_company_id && <Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.lead(j.id), { onSuccess: () => toast.success('Company lead created'), onError: fail })}>To lead</Button>}</div>])} />
      </Section>
    </div>
  );
}

// ---- fundraising --------------------------------------------------------------------------------------------------------------------
export function FundraisingPage() {
  useTitle('Fundraising');
  const camps = useQ(['campaigns'], () => aa.campaigns());
  const [form, setForm] = useState<Any>({ title: '', goal: '', is_restricted_fund: false });
  const [don, setDon] = useState<Any>({ donor_type: 'individual', name: '', email: '', pan: '', amount: '', mode: 'bank_transfer', reference: '', campaign_id: '', wants_80g: false, on_date: new Date().toISOString().slice(0, 10) });
  const [fy, setFy] = useState(currentFy());
  const donations = useQ(['donations', fy], () => aa.donations({ fy }));
  const reg = useQ(['80g', fy], () => aa.register80g(fy));
  const run = useRun();
  const record = () => run.mutate(() => aa.recordDonation({ donor_type: don.donor_type, donor_ref: { name: don.name, email: don.email || undefined, pan: don.pan || undefined }, campaign_id: don.campaign_id || undefined, amount_paise: Math.round(Number(don.amount) * 100), mode: don.mode, on_date: don.on_date, reference: don.reference || undefined, wants_80g: don.wants_80g }), { onSuccess: () => toast.success('Donation recorded'), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Fundraising" description="Campaigns, donations, receipts, the 80G register and the Form 10BD statement." />
      <div className="grid gap-4 md:grid-cols-2">
        {list(camps.data).map((c: Any) => (
          <Section key={c.id} title={c.title} action={<div className="flex gap-1">{c.is_restricted_fund && <StatusBadge status="restricted" />}<StatusBadge status={c.status} /></div>}>
            <Progress pct={c.progress_pct} />
            <p className="text-sm">{inr(c.raised_paise)} of {inr(c.goal_paise)} · {c.donors_count} donations · milestones {c.milestones_reached.join(', ') || '—'}</p>
            <p className="text-xs text-muted-foreground">{Object.entries(c.donor_mix ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
            {c.status === 'active' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.closeCampaign(c.id), { onSuccess: () => toast.success('Closed'), onError: fail })}>Close</Button>}
          </Section>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="New campaign">
          <div className="flex flex-wrap gap-2"><Input className="w-64" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /><Input className="w-36" type="number" placeholder="Goal (₹)" value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })} /><label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={form.is_restricted_fund} onChange={(e) => setForm({ ...form, is_restricted_fund: e.target.checked })} />Restricted / endowment</label></div>
          <Button size="sm" disabled={!form.title || !form.goal} onClick={() => run.mutate(() => aa.createCampaign({ title: form.title, goal_paise: Math.round(Number(form.goal) * 100), is_restricted_fund: form.is_restricted_fund }), { onSuccess: () => toast.success('Campaign created'), onError: fail })}>Create</Button>
        </Section>
        <Section title="Record offline donation">
          <div className="flex flex-wrap gap-2">
            <select className={sel} value={don.donor_type} onChange={(e) => setDon({ ...don, donor_type: e.target.value })}>{['individual', 'corporate', 'alumni'].map((t) => <option key={t}>{t}</option>)}</select>
            <Input className="w-48" placeholder="Donor name" value={don.name} onChange={(e) => setDon({ ...don, name: e.target.value })} />
            <Input className="w-48" placeholder="Email" value={don.email} onChange={(e) => setDon({ ...don, email: e.target.value })} />
            <Input className="w-32" placeholder="PAN" value={don.pan} onChange={(e) => setDon({ ...don, pan: e.target.value.toUpperCase() })} />
            <Input className="w-28" type="number" placeholder="Amount ₹" value={don.amount} onChange={(e) => setDon({ ...don, amount: e.target.value })} />
            <select className={sel} value={don.mode} onChange={(e) => setDon({ ...don, mode: e.target.value })}>{['bank_transfer', 'cheque', 'cash', 'upi'].map((t) => <option key={t}>{t}</option>)}</select>
            <Input className="w-40" placeholder="UTR / cheque no." value={don.reference} onChange={(e) => setDon({ ...don, reference: e.target.value })} />
            <select className={sel} value={don.campaign_id} onChange={(e) => setDon({ ...don, campaign_id: e.target.value })}><option value="">General fund</option>{list(camps.data).filter((c: Any) => c.status === 'active').map((c: Any) => <option key={c.id} value={c.id}>{c.title}</option>)}</select>
            <Input type="date" className="w-40" value={don.on_date} onChange={(e) => setDon({ ...don, on_date: e.target.value })} />
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={don.wants_80g} onChange={(e) => setDon({ ...don, wants_80g: e.target.checked })} />80G receipt</label>
          </div>
          <Button size="sm" disabled={!don.name || !don.amount} onClick={record}>Record</Button>
        </Section>
      </div>
      <Section title={`Donations · FY ${fy}`} action={<div className="flex gap-2"><Input className="w-28" value={fy} onChange={(e) => setFy(e.target.value)} /><Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.tenBd(fy), { onSuccess: () => toast.success('10BD statement queued (Jobs)'), onError: fail })}>10BD export</Button></div>}>
        <SimpleTable head={['Date', 'Donor', 'Type', 'Campaign', 'Amount', 'Mode', 'PAN', 'Receipt', '']} rows={list(donations.data).map((d: Any) => [day(d.on_date), d.donor_name, d.donor_type, d.campaign, inr(d.amount_paise), d.mode, d.pan_masked ?? '—', d.receipt_no ?? '—', <div key="a" className="flex gap-1">{!d.receipt_no && !d.refunded && <Button size="sm" variant="outline" onClick={() => run.mutate(() => aa.receipt(d.id), { onSuccess: () => toast.success('Receipt issued'), onError: fail })}>80G</Button>}{!d.refunded && <Button size="sm" variant="ghost" onClick={() => { const reason = window.prompt('Refund reason'); if (reason) run.mutate(() => aa.refund(d.id, { reason }), { onSuccess: () => toast.success('Refunded'), onError: fail }); }}>Refund</Button>}{d.refunded && <StatusBadge status="refunded" />}</div>])} />
      </Section>
      <Section title={`80G register · FY ${fy} (${list(reg.data).length})`}>
        <SimpleTable head={['Receipt', 'Date', 'Donor', 'PAN', 'Mode', 'Amount']} rows={list(reg.data).map((r: Any) => [r.receipt_no, day(r.on_date), r.donor_name, r.pan_masked ?? '—', r.mode, inr(r.amount_paise)])} />
      </Section>
    </div>
  );
}

export function StatsPage() {
  useTitle('Alumni stats');
  const res = useQ(['stats'], () => aa.stats());
  const s: Any = res.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Alumni stats" description="NAAC 5.4 — verified, employed, higher studies, geography, giving and participation." />
      <div className="grid gap-4 md:grid-cols-4"><Stat label="Alumni" value={s.total} /><Stat label="Verified" value={`${s.verified_pct ?? 0}%`} /><Stat label="Employed" value={`${s.employed_pct ?? 0}%`} /><Stat label="Higher studies" value={`${s.higher_studies_pct ?? 0}%`} /><Stat label="Mentors" value={s.mentors} /><Stat label="Events" value={s.events} /><Stat label="Participation" value={s.event_participation} /><Stat label="Donations" value={inr(s.donations_total_paise)} /></div>
      <div className="grid gap-4 md:grid-cols-2"><Section title="By batch"><Bars data={s.by_batch} /></Section><Section title="By city"><Bars data={s.by_city} /></Section><Section title="Donations by campaign (₹)"><Bars data={Object.fromEntries(Object.entries(s.donations_by_campaign ?? {}).map(([k, v]) => [k, Math.round(Number(v) / 100)]))} /></Section><Section title="By country"><Bars data={s.by_country} /></Section></div>
    </div>
  );
}

// ---- alumni portal ------------------------------------------------------------------------------------------------------------------
export function AlumniHomePage() {
  useTitle('Alumni');
  const me = useQ(['me'], () => aa.me());
  const eng = useQ(['engagement'], () => aa.engagement(), !!me.data);
  const events = useQ(['events-upcoming'], () => aa.events({ upcoming: true }));
  const camps = useQ(['campaigns'], () => aa.campaigns({ status: 'active' }));
  const p: Any = me.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title={p ? `Welcome back, ${p.name}` : 'Alumni'} description={p ? `${p.program ?? ''} · ${p.graduation_year ?? ''}` : 'Your alumni network'} actions={p?.is_verified ? <a className="text-sm text-primary underline" href={aa.cardUrl} target="_blank" rel="noreferrer">Membership card</a> : <StatusBadge status={p?.claim_status ?? 'unverified'} />} />
      <div className="grid gap-4 md:grid-cols-3"><Stat label="Profile completeness" value={`${p?.completeness ?? 0}%`} /><Stat label="Engagement score" value={eng.data?.data?.score ?? p?.engagement_score} /><Stat label="Current role" value={[p?.designation, p?.current_company].filter(Boolean).join(' @ ') || '—'} /></div>
      <Section title="Upcoming events"><SimpleTable head={['Event', 'Date', 'Venue', 'Fee']} rows={list(events.data).map((e: Any) => [e.title, day(e.held_on), e.venue ?? 'Online', e.registration_fee_paise ? inr(e.registration_fee_paise) : 'free'])} /></Section>
      <Section title="Campaign spotlight">{list(camps.data).slice(0, 2).map((c: Any) => <div key={c.id} className="space-y-1"><p className="text-sm font-medium">{c.title}</p><Progress pct={c.progress_pct} /><p className="text-xs text-muted-foreground">{inr(c.raised_paise)} raised of {inr(c.goal_paise)}</p></div>)}<Link className="text-sm text-primary underline" to="/alumni/give">Give</Link></Section>
    </div>
  );
}

export function AlumniProfileSelfPage() {
  useTitle('My alumni profile');
  const me = useQ(['me'], () => aa.me());
  const p: Any = me.data?.data;
  const [form, setForm] = useState<Any>(null);
  const [job, setJob] = useState<Any>({ company: '', designation: '', from_on: '', is_current: true });
  const run = useRun();
  useEffect(() => { if (p && !form) setForm({ current_company: p.current_company ?? '', designation: p.designation ?? '', city: p.city ?? '', country: p.country ?? '', linkedin_url: p.linkedin_url ?? '', email: p.email ?? '', phone: p.phone ?? '', willing_to_mentor: p.willing_to_mentor, willing_to_recruit: p.willing_to_recruit, consent_contact: p.consent_contact, consent_directory_fields: p.consent_directory_fields ?? [] }); }, [p, form]);
  if (!p || !form) return <PageHeader title="My alumni profile" />;
  const toggle = (f: string) => setForm({ ...form, consent_directory_fields: form.consent_directory_fields.includes(f) ? form.consent_directory_fields.filter((x: string) => x !== f) : [...form.consent_directory_fields, f] });
  const save = () => run.mutate(() => aa.updateMe(Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === '' ? null : v]))), { onSuccess: () => toast.success('Saved'), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="My alumni profile" description="Your details, privacy and directory consent (DPDP)." />
      <Section title="Details">
        <div className="grid gap-2 md:grid-cols-3">{['current_company', 'designation', 'city', 'country', 'linkedin_url', 'email', 'phone'].map((k) => <Input key={k} placeholder={k.replace('_', ' ')} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />)}</div>
      </Section>
      <Section title="Privacy & consent">
        <div className="flex flex-wrap gap-3 text-sm">
          <label className="flex items-center gap-1"><input type="checkbox" checked={form.consent_contact} onChange={(e) => setForm({ ...form, consent_contact: e.target.checked })} />Others may contact me</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={form.willing_to_mentor} onChange={(e) => setForm({ ...form, willing_to_mentor: e.target.checked })} />Willing to mentor</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={form.willing_to_recruit} onChange={(e) => setForm({ ...form, willing_to_recruit: e.target.checked })} />Willing to recruit</label>
        </div>
        <p className="text-xs text-muted-foreground">Show in the directory (nothing ticked = not listed):</p>
        <div className="flex flex-wrap gap-3 text-sm">{FIELDS.map((f) => <label key={f} className="flex items-center gap-1"><input type="checkbox" checked={form.consent_directory_fields.includes(f)} onChange={() => toggle(f)} />{f.replace('_', ' ')}</label>)}</div>
        <Button size="sm" onClick={save}>Save</Button>
      </Section>
      <Section title="Employment history">
        <SimpleTable head={['Company', 'Designation', 'From', 'To', 'Current', '']} rows={(p.employment ?? []).map((j: Any) => [j.company, j.designation, day(j.from_on), day(j.to_on), j.is_current ? 'yes' : '', <Button key="d" size="sm" variant="ghost" onClick={() => run.mutate(() => aa.deleteEmployment(j.id), { onError: fail })}>Remove</Button>])} />
        <div className="flex flex-wrap items-end gap-2"><Input className="w-48" placeholder="Company" value={job.company} onChange={(e) => setJob({ ...job, company: e.target.value })} /><Input className="w-48" placeholder="Designation" value={job.designation} onChange={(e) => setJob({ ...job, designation: e.target.value })} /><Input type="date" className="w-40" value={job.from_on} onChange={(e) => setJob({ ...job, from_on: e.target.value })} /><label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={job.is_current} onChange={(e) => setJob({ ...job, is_current: e.target.checked })} />Current</label><Button size="sm" disabled={!job.company} onClick={() => run.mutate(() => aa.addEmployment({ ...job, from_on: job.from_on || undefined, designation: job.designation || undefined }), { onSuccess: () => { toast.success('Added'); setJob({ company: '', designation: '', from_on: '', is_current: true }); }, onError: fail })}>Add</Button></div>
      </Section>
    </div>
  );
}

export function AlumniEventsPortalPage() {
  useTitle('Alumni events');
  const res = useQ(['events'], () => aa.events());
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Events" description="Reunions, chapter meets and webinars — register (and pay) here." />
      <Section title="Events"><SimpleTable head={['Event', 'Type', 'Date', 'Venue', 'Fee', '']} rows={list(res.data).map((e: Any) => [e.title, e.event_type, day(e.held_on), e.webinar_url ? <a key="w" className="text-primary underline" href={e.webinar_url} target="_blank" rel="noreferrer">Join link</a> : e.venue, e.registration_fee_paise ? inr(e.registration_fee_paise) : 'free', e.my_registration_id ? <StatusBadge key="r" status="registered" /> : e.event_id && e.event_status === 'scheduled' ? <Button key="b" size="sm" onClick={() => run.mutate(() => aa.register(e.event_id), { onSuccess: () => toast.success(e.registration_fee_paise ? 'Registered — pay the invoice under Fees' : 'Registered'), onError: fail })}>Register</Button> : ''])} /></Section>
    </div>
  );
}

export function AlumniJobsPortalPage() {
  useTitle('Alumni jobs');
  const res = useQ(['jobs-board'], () => aa.jobs());
  const mine = useQ(['jobs-mine'], () => aa.myJobs());
  const [form, setForm] = useState<Any>({ title: '', company: '', location: '', apply_url: '', description: '' });
  const run = useRun();
  const open = (j: Any) => aa.click(j.id).then((r: Any) => { if (r.data?.apply_url) window.open(r.data.apply_url, '_blank', 'noopener'); }).catch(fail);
  return (
    <div className="space-y-4">
      <PageHeader title="Jobs board" description="Openings shared by alumni — posts are moderated before they appear." />
      <Section title="Openings"><SimpleTable head={['Role', 'Company', 'Location', 'Posted by', 'Expires', '']} rows={list(res.data).map((j: Any) => [j.title, j.company, j.location, j.posted_by, day(j.expires_on), j.apply_url ? <Button key="a" size="sm" variant="outline" onClick={() => open(j)}>Apply</Button> : ''])} /></Section>
      <Section title="Post an opening">
        <div className="flex flex-wrap gap-2">{['title', 'company', 'location', 'apply_url'].map((k) => <Input key={k} className="w-48" placeholder={k.replace('_', ' ')} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />)}</div>
        <textarea className={area} placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <Button size="sm" disabled={!form.title} onClick={() => run.mutate(() => aa.postJob(Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v || undefined]))), { onSuccess: () => toast.success('Submitted for moderation'), onError: fail })}>Post</Button>
      </Section>
      <Section title="My posts"><SimpleTable head={['Role', 'Company', 'Status', 'Clicks', 'Reason']} rows={list(mine.data).map((j: Any) => [j.title, j.company, <StatusBadge key="s" status={j.status} />, j.clicks, j.reason ?? ''])} /></Section>
    </div>
  );
}

export function AlumniGivePage() {
  useTitle('Give');
  const camps = useQ(['campaigns'], () => aa.campaigns({ status: 'active' }));
  const mine = useQ(['donations-mine'], () => aa.myDonations());
  const [g, setG] = useState<Any>({ campaign_id: '', amount: 1000, wants_80g: false, pan: '', address: '', anonymous: false });
  const run = useRun();
  const give = () => run.mutate(() => aa.donate({ campaign_id: g.campaign_id || undefined, amount_paise: Math.round(Number(g.amount) * 100), wants_80g: g.wants_80g, donor: { pan: g.pan || undefined, address: g.address || undefined, anonymous: g.anonymous } }), {
    onSuccess: (r: Any) => { const url = r.data?.checkout?.url ?? r.data?.checkout?.redirect_url; if (url) window.location.assign(url); else toast.success(`Order ${r.data?.order?.order_id} created — complete the payment`); },
    onError: fail,
  });
  return (
    <div className="space-y-4">
      <PageHeader title="Give" description="Support a campaign — 80G receipts for eligible donations (PAN required above ₹2,000)." />
      <div className="grid gap-4 md:grid-cols-2">{list(camps.data).map((c: Any) => <Section key={c.id} title={c.title} action={<Button size="sm" variant={g.campaign_id === c.id ? 'default' : 'outline'} onClick={() => setG({ ...g, campaign_id: c.id })}>Choose</Button>}><p className="text-sm text-muted-foreground">{c.purpose}</p><Progress pct={c.progress_pct} /><p className="text-xs">{inr(c.raised_paise)} of {inr(c.goal_paise)}</p></Section>)}</div>
      <Section title="Donate">
        <div className="flex flex-wrap items-center gap-2">
          {[500, 1000, 5000, 10000].map((v) => <Button key={v} size="sm" variant={Number(g.amount) === v ? 'default' : 'outline'} onClick={() => setG({ ...g, amount: v })}>₹{v.toLocaleString('en-IN')}</Button>)}
          <Input className="w-32" type="number" value={g.amount} onChange={(e) => setG({ ...g, amount: e.target.value })} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={g.wants_80g} onChange={(e) => setG({ ...g, wants_80g: e.target.checked })} />80G receipt</label>
          {g.wants_80g && <><Input className="w-36" placeholder="PAN" value={g.pan} onChange={(e) => setG({ ...g, pan: e.target.value.toUpperCase() })} /><Input className="w-64" placeholder="Address for the receipt" value={g.address} onChange={(e) => setG({ ...g, address: e.target.value })} /></>}
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={g.anonymous} onChange={(e) => setG({ ...g, anonymous: e.target.checked })} />Anonymous</label>
          <Button size="sm" disabled={!g.amount} onClick={give}>Donate {g.campaign_id ? '' : 'to the general fund'}</Button>
        </div>
      </Section>
      <Section title="My donations & receipts"><SimpleTable head={['Date', 'Campaign', 'Amount', 'Mode', 'Receipt']} rows={list(mine.data).map((d: Any) => [day(d.on_date), d.campaign, inr(d.amount_paise), d.mode, d.receipt_url ? <a key="r" className="text-primary underline" href={`/api/v1${d.receipt_url}`} target="_blank" rel="noreferrer">{d.receipt_no}</a> : d.receipt_no ?? '—'])} /></Section>
    </div>
  );
}

// ---- public: claim + website campaigns ---------------------------------------------------------------------------------------------
export function AlumniClaimPage() {
  useTitle('Claim your alumni profile');
  const [inst, setInst] = useState(new URLSearchParams(window.location.search).get('institution') ?? '');
  const [f, setF] = useState<Any>({ registration_number: '', graduation_year: '', email: '' });
  const [token, setToken] = useState('');
  const [otp, setOtp] = useState('');
  const [done, setDone] = useState<Any>(null);
  const send = () => aa.claim(inst, { ...f, graduation_year: Number(f.graduation_year) }).then((r: Any) => { setToken(r.data.claim_token); toast.success(r.data.message); }).catch(fail);
  const verify = () => aa.claimVerify(inst, { claim_token: token, otp }).then((r: Any) => setDone(r.data)).catch(fail);
  return (
    <div className="mx-auto max-w-lg space-y-4 p-6">
      <PageHeader title="Claim your alumni profile" description="Registration number + graduation year + the email on our records." />
      {done ? <Section title="Claimed"><p className="text-sm">{done.message}</p>{done.username && <p className="text-sm">Username: <b>{done.username}</b></p>}<Link className="text-sm text-primary underline" to="/login">Sign in</Link></Section> : !token ? (
        <Section title="Your details">
          <Input placeholder="Institution code" value={inst} onChange={(e) => setInst(e.target.value)} />
          <Input placeholder="Registration number" value={f.registration_number} onChange={(e) => setF({ ...f, registration_number: e.target.value })} />
          <Input placeholder="Graduation year" value={f.graduation_year} onChange={(e) => setF({ ...f, graduation_year: e.target.value })} />
          <Input placeholder="Email on record" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          <Button size="sm" disabled={!inst || !f.registration_number || !f.graduation_year || !f.email} onClick={send}>Send code</Button>
        </Section>
      ) : (
        <Section title="Enter the code"><Input placeholder="6-digit code" value={otp} onChange={(e) => setOtp(e.target.value)} /><Button size="sm" disabled={otp.length < 4} onClick={verify}>Verify</Button></Section>
      )}
    </div>
  );
}

export function PublicCampaignsPage() {
  useTitle('Support us');
  const inst = new URLSearchParams(window.location.search).get('institution') ?? '';
  const res = useQ(['public-campaigns', inst], () => aa.publicCampaigns(inst), !!inst);
  const [g, setG] = useState<Any>({ campaign_id: '', amount: 1000, name: '', email: '', pan: '', wants_80g: false });
  const give = () => aa.donatePublic(inst, { campaign_id: g.campaign_id || undefined, amount_paise: Math.round(Number(g.amount) * 100), donor_type: 'individual', wants_80g: g.wants_80g, donor: { name: g.name, email: g.email || undefined, pan: g.pan || undefined } }).then((r: Any) => { const url = r.data?.checkout?.url; if (url) window.location.assign(url); else toast.success('Order created — complete the payment'); }).catch(fail);
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <PageHeader title="Support our campaigns" description="Every gift helps — 80G receipts for eligible donations." />
      <div className="grid gap-4 md:grid-cols-2">{list(res.data).map((c: Any) => <Section key={c.id} title={c.title} action={<Button size="sm" variant={g.campaign_id === c.id ? 'default' : 'outline'} onClick={() => setG({ ...g, campaign_id: c.id })}>Choose</Button>}><Progress pct={c.progress_pct} /><p className="text-xs">{inr(c.raised_paise)} of {inr(c.goal_paise)}</p></Section>)}</div>
      <Section title="Donate">
        <div className="flex flex-wrap gap-2"><Input className="w-48" placeholder="Your name" value={g.name} onChange={(e) => setG({ ...g, name: e.target.value })} /><Input className="w-48" placeholder="Email" value={g.email} onChange={(e) => setG({ ...g, email: e.target.value })} /><Input className="w-28" type="number" value={g.amount} onChange={(e) => setG({ ...g, amount: e.target.value })} /><label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={g.wants_80g} onChange={(e) => setG({ ...g, wants_80g: e.target.checked })} />80G</label>{g.wants_80g && <Input className="w-32" placeholder="PAN" value={g.pan} onChange={(e) => setG({ ...g, pan: e.target.value.toUpperCase() })} />}</div>
        <Button size="sm" disabled={!g.name || !g.amount} onClick={give}>Donate</Button>
      </Section>
    </div>
  );
}
