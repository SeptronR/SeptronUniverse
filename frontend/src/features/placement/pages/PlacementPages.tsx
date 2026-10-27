import { useEffect, useState, type ReactNode } from 'react';
import { InsightsPanel } from '@/features/analytics/components/InsightsPanel';
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
import { plApi as pa } from '../api';

// Phase 28 web screens (Prompts/28 §28.9). Eligibility, policy, consent and scopes are enforced by the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['placement', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['placement'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');
const lpa = (p?: number | null) => (p ? `₹${(p / 10_000_000).toFixed(2)} LPA` : '—');
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[80px] w-full rounded-md border bg-background p-2 text-sm';
const TIERS = ['super_dream', 'dream', 'core', 'mass'];
const REASONS: Record<string, string> = {
  CGPA: 'CGPA below minimum', ACTIVE_BACKLOGS: 'Active backlogs', HISTORY_BACKLOGS: 'Backlog history', PCT_10: '10th %', PCT_12: '12th %',
  GAP_YEARS: 'Gap years', PROGRAM: 'Programme / college not in drive', BATCH: 'Batch not in drive', ATTENDANCE: 'Attendance', SKILLS: 'Skills',
  ALREADY_PLACED: 'Already placed (dream upgrades only)', OPTED_OUT: 'Opted out', BLACKLISTED: 'Blacklisted', DEBARRED: 'Debarred (discipline)', HOLD: 'Active hold', INACTIVE: 'Enrolment not active',
};
const regsToRows = (text: string) => text.split(/[\s,]+/).map((r) => r.trim()).filter(Boolean).map((registration_number) => ({ registration_number }));

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function Reasons({ reasons }: { reasons?: string[] }) {
  if (!reasons?.length) return <span className="text-emerald-700">Eligible</span>;
  return <span className="text-xs text-red-700">{reasons.map((r) => REASONS[r] ?? r).join(' · ')}</span>;
}
function Tabs({ tabs, value, onChange }: { tabs: string[]; value: string; onChange: (t: string) => void }) {
  return <div className="flex flex-wrap gap-1">{tabs.map((t) => <Button key={t} size="sm" variant={t === value ? 'default' : 'outline'} onClick={() => onChange(t)}>{t}</Button>)}</div>;
}
function Funnel({ f }: { f: Any }) {
  if (!f) return null;
  const steps: [string, number][] = [['Applied', f.applied], ['Shortlisted', f.shortlisted], ...(f.rounds ?? []).map((r: Any) => [`R${r.round_no} cleared`, r.cleared] as [string, number]), ['Selected', f.selected], ['Offers', f.offers], ['Accepted', f.accepted]];
  const max = Math.max(1, ...steps.map((s) => s[1] ?? 0));
  return <div className="space-y-1">{steps.map(([k, v]) => <div key={k} className="flex items-center gap-2 text-sm"><span className="w-28 text-muted-foreground">{k}</span><div className="h-4 rounded bg-primary/70" style={{ width: `${Math.max(2, (100 * (v ?? 0)) / max)}%` }} /><span>{v ?? 0}</span></div>)}</div>;
}

// ---- companies ----------------------------------------------------------------------------------------------------------
export function CompaniesPage() {
  useTitle('Companies');
  const [q, setQ] = useState('');
  const [form, setForm] = useState<Any>({ name: '', tier: 'core', sector: '' });
  const res = useQ(['companies', q], () => pa.companies({ q: q || undefined }));
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Companies" description="Company master with tiers, recruiters, history and blacklist." />
      <Section title="Add company">
        <div className="flex flex-wrap items-end gap-2">
          <Input className="w-64" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input className="w-48" placeholder="Sector" value={form.sector} onChange={(e) => setForm({ ...form, sector: e.target.value })} />
          <select className={sel} value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })}>{TIERS.map((t) => <option key={t}>{t}</option>)}</select>
          <Button size="sm" disabled={!form.name} onClick={() => run.mutate(() => pa.createCompany(form), { onSuccess: () => { toast.success('Company added'); setForm({ name: '', tier: 'core', sector: '' }); }, onError: fail })}>Add</Button>
        </div>
      </Section>
      <Section title={`Companies (${list(res.data).length})`} action={<Input className="w-56" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />}>
        <SimpleTable head={['Company', 'Tier', 'Sector', 'Drives', 'Hires', 'Feedback', 'Status']} rows={list(res.data).map((c: Any) => [<Link key="l" className="text-primary underline" to={`/admin/placement/companies/${c.id}`}>{c.name}</Link>, c.tier, c.sector, c.drives, c.hires, c.feedback_avg ?? '—', c.is_blacklisted ? <StatusBadge key="b" status="blacklisted" /> : <StatusBadge key="a" status="active" />])} />
      </Section>
    </div>
  );
}

export function CompanyPage() {
  const { id = '' } = useParams();
  const res = useQ(['company', id], () => pa.company(id));
  const fb = useQ(['company-fb', id], () => pa.companyFeedback(id));
  const [inv, setInv] = useState<Any>({ email: '', name: '' });
  const [reason, setReason] = useState('');
  const run = useRun();
  const c: Any = res.data?.data ?? {};
  useTitle(c.name ?? 'Company');
  return (
    <div className="space-y-4">
      <PageHeader title={c.name ?? 'Company'} description={`${c.tier ?? ''} · ${c.sector ?? ''} · ${c.hq_city ?? ''}`} />
      <div className="grid gap-3 md:grid-cols-3"><Stat label="Drives" value={c.drives} /><Stat label="Hires" value={c.hires} /><Stat label="Feedback avg" value={c.feedback_avg} /></div>
      <Section title="Contacts"><SimpleTable head={['Name', 'Designation', 'Email', 'Phone']} rows={(c.contacts ?? []).map((x: Any) => [x.name, x.designation, x.email, x.phone])} /></Section>
      <Section title="Recruiter portal">
        <p className="text-xs text-muted-foreground">{(c.recruiter_user_ids ?? []).length} recruiter user(s) bound.</p>
        <div className="flex flex-wrap gap-2">
          <Input className="w-64" placeholder="Recruiter email" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} />
          <Input className="w-48" placeholder="Name" value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} />
          <Button size="sm" disabled={!inv.email || !inv.name} onClick={() => run.mutate(() => pa.inviteRecruiter(id, inv), { onSuccess: () => toast.success('Invitation sent'), onError: fail })}>Invite</Button>
        </div>
      </Section>
      <Section title="Blacklist">
        <div className="flex flex-wrap gap-2">
          <Input className="w-96" placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button size="sm" variant={c.is_blacklisted ? 'outline' : 'destructive'} disabled={reason.length < 3} onClick={() => run.mutate(() => pa.blacklistCompany(id, { blacklisted: !c.is_blacklisted, reason }), { onSuccess: () => toast.success('Updated'), onError: fail })}>{c.is_blacklisted ? 'Restore' : 'Blacklist'}</Button>
        </div>
      </Section>
      <Section title="Drive history"><SimpleTable head={['Drive', 'Status', 'Date', 'Applications', 'Hires', 'CTC']} rows={(c.history ?? []).map((h: Any) => [<Link key="d" className="text-primary underline" to={`/admin/placement/drives/${h.drive_id}`}>{h.title}</Link>, <StatusBadge key="s" status={h.status} />, day(h.drive_on), h.applications, h.hires, lpa(h.ctc_min_paise)])} /></Section>
      <Section title="Feedback"><SimpleTable head={['Drive', 'Ratings', 'Remarks', 'At']} rows={list(fb.data).map((f: Any) => [f.drive_title, Object.entries(f.ratings ?? {}).map(([k, v]) => `${k}: ${v}`).join(', '), f.remarks, day(f.submitted_at)])} /></Section>
    </div>
  );
}

// ---- policies -----------------------------------------------------------------------------------------------------------
export function PoliciesPage() {
  useTitle('Placement policies');
  const res = useQ(['policies'], () => pa.policies());
  const [form, setForm] = useState<Any>({ batch_id: '', program_id: '', max_offers: 1, dream_ctc_threshold_paise: 100000000, allow_upgrade_if_dream: true, opt_out_allowed: true });
  const run = useRun();
  const body = () => ({ ...form, batch_id: form.batch_id || null, program_id: form.program_id || null, max_offers: Number(form.max_offers), dream_ctc_threshold_paise: Number(form.dream_ctc_threshold_paise) || null });
  return (
    <div className="space-y-4">
      <PageHeader title="Placement policies" description="Per batch / programme: max offers, dream threshold and upgrade, opt-out. Unset values fall back to the defaults." />
      <Section title="New policy">
        <div className="flex flex-wrap items-end gap-2">
          <Input className="w-72" placeholder="Batch id (optional)" value={form.batch_id} onChange={(e) => setForm({ ...form, batch_id: e.target.value })} />
          <Input className="w-72" placeholder="Programme id (optional)" value={form.program_id} onChange={(e) => setForm({ ...form, program_id: e.target.value })} />
          <label className="text-xs">Max offers <Input className="w-20" type="number" value={form.max_offers} onChange={(e) => setForm({ ...form, max_offers: e.target.value })} /></label>
          <label className="text-xs">Dream threshold (paise) <Input className="w-40" type="number" value={form.dream_ctc_threshold_paise} onChange={(e) => setForm({ ...form, dream_ctc_threshold_paise: e.target.value })} /></label>
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={form.allow_upgrade_if_dream} onChange={(e) => setForm({ ...form, allow_upgrade_if_dream: e.target.checked })} />Dream upgrade</label>
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={form.opt_out_allowed} onChange={(e) => setForm({ ...form, opt_out_allowed: e.target.checked })} />Opt-out allowed</label>
          <Button size="sm" onClick={() => run.mutate(() => pa.createPolicy(body()), { onSuccess: () => toast.success('Policy saved'), onError: fail })}>Save</Button>
        </div>
      </Section>
      <Section title="Policies">
        <SimpleTable head={['Batch', 'Programme', 'Max offers', 'Dream threshold', 'Upgrade', 'Opt-out', '']} rows={list(res.data).map((p: Any) => [p.batch_id ?? 'all', p.program_id ?? 'all', p.max_offers, lpa(p.dream_ctc_threshold_paise), p.allow_upgrade_if_dream ? 'yes' : 'no', p.opt_out_allowed ? 'yes' : 'no', <Button key="e" size="sm" variant="outline" onClick={() => run.mutate(() => pa.updatePolicy(p.id, { ...p, max_offers: p.max_offers === 1 ? 2 : 1, id: undefined, source: undefined }), { onError: fail })}>Toggle 1↔2 offers</Button>])} />
      </Section>
    </div>
  );
}

// ---- drives -------------------------------------------------------------------------------------------------------------
export function DrivesPage() {
  useTitle('Drives');
  const [status, setStatus] = useState('all');
  const res = useQ(['drives', status], () => pa.drives({ status: status === 'all' ? undefined : status }));
  const cos = useQ(['companies-all'], () => pa.companies());
  const [w, setW] = useState<Any>({ company_id: '', title: '', ctc_lpa: 6, min_cgpa: 6, max_active_backlogs: 0, programs: '', deadline: '', drive_on: '' });
  const [created, setCreated] = useState<Any>(null);
  const [preview, setPreview] = useState<Any>(null);
  const run = useRun();
  const body = () => ({
    company_id: w.company_id, title: w.title, ctc_min_paise: Math.round(Number(w.ctc_lpa) * 10_000_000),
    eligibility_rules: { min_cgpa: Number(w.min_cgpa), max_active_backlogs: Number(w.max_active_backlogs), programs: w.programs ? w.programs.split(',').map((x: string) => x.trim()) : [] },
    registration_deadline: w.deadline ? new Date(w.deadline).toISOString() : null, drive_on: w.drive_on || null,
  });
  return (
    <div className="space-y-4">
      <PageHeader title="Drives" description="Drive wizard with rule builder and live eligibility preview; lifecycle draft → open → closed → in progress → completed." />
      <InsightsPanel module="placement" />
      <Section title="Drive wizard">
        <div className="flex flex-wrap items-end gap-2">
          <select className={sel} value={w.company_id} onChange={(e) => setW({ ...w, company_id: e.target.value })}><option value="">Company…</option>{list(cos.data).filter((c: Any) => !c.is_blacklisted).map((c: Any) => <option key={c.id} value={c.id}>{c.name} ({c.tier})</option>)}</select>
          <Input className="w-64" placeholder="Title / role" value={w.title} onChange={(e) => setW({ ...w, title: e.target.value })} />
          <label className="text-xs">CTC (LPA) <Input className="w-20" type="number" value={w.ctc_lpa} onChange={(e) => setW({ ...w, ctc_lpa: e.target.value })} /></label>
          <label className="text-xs">Min CGPA <Input className="w-20" type="number" step="0.1" value={w.min_cgpa} onChange={(e) => setW({ ...w, min_cgpa: e.target.value })} /></label>
          <label className="text-xs">Max active backlogs <Input className="w-20" type="number" value={w.max_active_backlogs} onChange={(e) => setW({ ...w, max_active_backlogs: e.target.value })} /></label>
          <Input className="w-72" placeholder="Programme ids (comma separated)" value={w.programs} onChange={(e) => setW({ ...w, programs: e.target.value })} />
          <label className="text-xs">Deadline <Input type="datetime-local" value={w.deadline} onChange={(e) => setW({ ...w, deadline: e.target.value })} /></label>
          <label className="text-xs">Drive date <Input type="date" value={w.drive_on} onChange={(e) => setW({ ...w, drive_on: e.target.value })} /></label>
          <Button size="sm" disabled={!w.company_id || !w.title} onClick={() => run.mutate(async () => {
            const r: Any = created ? await pa.updateDrive(created.id, { ...body(), company_id: undefined }) : await pa.createDrive(body());
            setCreated(r.data);
            const p: Any = await pa.preview(r.data.id);
            setPreview(p.data);
          }, { onError: fail })}>{created ? 'Update & preview' : 'Save draft & preview'}</Button>
          {created && <Button size="sm" onClick={() => run.mutate(() => pa.driveAction(created.id, 'publish'), { onSuccess: () => { toast.success('Published — eligible students notified'); setCreated(null); setPreview(null); }, onError: fail })}>Publish</Button>}
        </div>
        {preview && (
          <div className="text-sm">
            <p>{preview.eligible_count} eligible of {preview.total} candidates.</p>
            <p className="text-xs text-muted-foreground">Ineligible: {Object.entries(preview.ineligible_by_reason ?? {}).map(([k, v]) => `${REASONS[k] ?? k} ${v}`).join(' · ') || 'none'}</p>
          </div>
        )}
      </Section>
      <Tabs tabs={['all', 'draft', 'open', 'closed', 'in_progress', 'completed', 'cancelled']} value={status} onChange={setStatus} />
      <Section title={`Drives (${list(res.data).length})`}>
        <SimpleTable head={['Drive', 'Company', 'Tier', 'CTC', 'Deadline', 'Date', 'Applications', 'Status']} rows={list(res.data).map((d: Any) => [<Link key="l" className="text-primary underline" to={`/admin/placement/drives/${d.id}`}>{d.title}</Link>, d.company_name, d.company_tier, lpa(d.ctc_min_paise), when(d.registration_deadline), day(d.drive_on), d.applications, <StatusBadge key="s" status={d.status} />])} />
      </Section>
    </div>
  );
}

export function DrivePage() {
  const { id = '' } = useParams();
  const [tab, setTab] = useState('applications');
  const [scope, setScope] = useState<string>();
  const [status, setStatus] = useState('');
  const [drawer, setDrawer] = useState<Any>(null);
  const [regs, setRegs] = useState('');
  const [round, setRound] = useState<Any>({ round_no: 1, name: '', round_type: 'aptitude', scheduled_at: '', venue: '' });
  const [results, setResults] = useState<Any>({ round_id: '', text: '', status: 'cleared' });
  const [offer, setOffer] = useState<Any>({ application_id: '', ctc_lpa: 6, joining_on: '' });
  const [fbk, setFbk] = useState<Any>({ candidates: 4, process: 4, remarks: '' });
  const d: Any = useQ(['drive', id], () => pa.drive(id)).data?.data ?? {};
  const apps = useQ(['apps', id, scope, status], () => pa.applications(id, { scope, status: status || undefined }));
  const rounds = useQ(['rounds', id], () => pa.rounds(id));
  const funnel = useQ(['funnel', id], () => pa.funnel(id));
  const offers = useQ(['drive-offers', id], () => pa.offers({ drive_id: id }));
  const run = useRun();
  useTitle(d.title ?? 'Drive');
  const act = (a: string) => run.mutate(() => pa.driveAction(id, a), { onSuccess: () => toast.success(`Drive ${a}`), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title={d.title ?? 'Drive'} description={`${d.company_name ?? ''} · ${lpa(d.ctc_min_paise)} · ${d.status ?? ''}`} actions={<div className="flex gap-1">{['publish', 'close', 'start', 'complete', 'cancel'].map((a) => <Button key={a} size="sm" variant="outline" onClick={() => act(a)}>{a}</Button>)}<Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.reEvaluate(id), { onSuccess: (r: Any) => toast.success(`${r.data.succeeded} re-evaluated`), onError: fail })}>Re-evaluate</Button></div>} />
      <Section title="Funnel"><Funnel f={funnel.data?.data} /></Section>
      <Tabs tabs={['applications', 'rounds', 'offers', 'feedback']} value={tab} onChange={setTab} />
      {tab === 'applications' && (
        <Section title={`Applications (${list(apps.data).length})`} action={<div className="flex gap-2"><select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{['applied', 'shortlisted', 'in_process', 'selected', 'rejected', 'absent', 'withdrawn', 'ineligible'].map((s) => <option key={s}>{s}</option>)}</select><ScopeTabs visibility={(apps.data as Any)?.meta?.visibility} value={scope} onChange={setScope} /></div>}>
          <div className="flex flex-wrap items-end gap-2">
            <textarea className={area} placeholder="Shortlist: registration numbers (comma / newline separated)" value={regs} onChange={(e) => setRegs(e.target.value)} />
            <Button size="sm" disabled={!regs} onClick={() => run.mutate(() => pa.shortlist(id, regsToRows(regs)), { onSuccess: (r: Any) => toast.success(`${r.data.succeeded} shortlisted, ${r.data.failed.length} failed`), onError: fail })}>Import shortlist</Button>
          </div>
          <SimpleTable head={['Student', 'Reg. no', 'Dept', 'CGPA', 'Status', 'Override', '']} rows={list(apps.data).map((a: Any) => [a.student_name, a.registration_number, a.department_code, a.eligibility_snapshot?.cgpa ?? '—', <StatusBadge key="s" status={a.status} />, a.override_reason ?? '', <Button key="v" size="sm" variant="outline" onClick={() => setDrawer(a)}>Snapshot</Button>])} />
          {drawer && (
            <Card><CardContent className="space-y-2 p-4 text-sm">
              <div className="flex justify-between"><p className="font-medium">{drawer.student_name} — eligibility snapshot</p><Button size="sm" variant="ghost" onClick={() => setDrawer(null)}>Close</Button></div>
              <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{JSON.stringify(drawer.eligibility_snapshot, null, 2)}</pre>
              <p>Rounds: {(drawer.rounds ?? []).map((r: Any) => `R${r.round_no} ${r.status}`).join(' · ') || '—'}</p>
              <Button size="sm" variant="outline" onClick={() => { const reason = window.prompt('Override reason (min 5 chars)'); if (reason) run.mutate(() => pa.override({ application_id: drawer.id, reason }), { onSuccess: () => toast.success('Eligibility overridden'), onError: fail }); }}>Override eligibility</Button>
            </CardContent></Card>
          )}
        </Section>
      )}
      {tab === 'rounds' && (
        <Section title="Rounds">
          <div className="flex flex-wrap items-end gap-2">
            <Input className="w-16" type="number" value={round.round_no} onChange={(e) => setRound({ ...round, round_no: Number(e.target.value) })} />
            <Input className="w-48" placeholder="Name" value={round.name} onChange={(e) => setRound({ ...round, name: e.target.value })} />
            <select className={sel} value={round.round_type} onChange={(e) => setRound({ ...round, round_type: e.target.value })}>{['pre_placement_talk', 'aptitude', 'coding', 'gd', 'technical', 'hr', 'final'].map((t) => <option key={t}>{t}</option>)}</select>
            <Input type="datetime-local" value={round.scheduled_at} onChange={(e) => setRound({ ...round, scheduled_at: e.target.value })} />
            <Input className="w-40" placeholder="Venue" value={round.venue} onChange={(e) => setRound({ ...round, venue: e.target.value })} />
            <Button size="sm" disabled={!round.name} onClick={() => run.mutate(() => pa.addRound(id, { ...round, scheduled_at: round.scheduled_at ? new Date(round.scheduled_at).toISOString() : null }), { onSuccess: () => toast.success('Round added'), onError: fail })}>Add round</Button>
          </div>
          <SimpleTable head={['#', 'Round', 'Type', 'At', 'Venue', 'Results']} rows={list(rounds.data).map((r: Any) => [r.round_no, r.name, r.round_type, when(r.scheduled_at), r.venue, Object.entries(r.results ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ')])} />
          <div className="flex flex-wrap items-end gap-2">
            <select className={sel} value={results.round_id} onChange={(e) => setResults({ ...results, round_id: e.target.value })}><option value="">Round…</option>{list(rounds.data).map((r: Any) => <option key={r.id} value={r.id}>R{r.round_no} {r.name}</option>)}</select>
            <select className={sel} value={results.status} onChange={(e) => setResults({ ...results, status: e.target.value })}>{['cleared', 'not_cleared', 'absent'].map((s) => <option key={s}>{s}</option>)}</select>
            <textarea className={area} placeholder="Registration numbers for this result" value={results.text} onChange={(e) => setResults({ ...results, text: e.target.value })} />
            <Button size="sm" disabled={!results.round_id || !results.text} onClick={() => run.mutate(() => pa.roundResults(results.round_id, { rows: regsToRows(results.text).map((r) => ({ ...r, status: results.status })) }), { onSuccess: (r: Any) => toast.success(`${r.data.succeeded} recorded${r.data.blacklisted?.length ? `, ${r.data.blacklisted.length} auto-blacklisted` : ''}`), onError: fail })}>Upload results</Button>
          </div>
        </Section>
      )}
      {tab === 'offers' && (
        <Section title="Offers">
          <div className="flex flex-wrap items-end gap-2">
            <select className={sel} value={offer.application_id} onChange={(e) => setOffer({ ...offer, application_id: e.target.value })}><option value="">Selected candidate…</option>{list(apps.data).filter((a: Any) => a.status === 'selected' && !a.offer).map((a: Any) => <option key={a.id} value={a.id}>{a.student_name} ({a.registration_number})</option>)}</select>
            <label className="text-xs">CTC (LPA) <Input className="w-20" type="number" value={offer.ctc_lpa} onChange={(e) => setOffer({ ...offer, ctc_lpa: e.target.value })} /></label>
            <label className="text-xs">Joining <Input type="date" value={offer.joining_on} onChange={(e) => setOffer({ ...offer, joining_on: e.target.value })} /></label>
            <Button size="sm" disabled={!offer.application_id} onClick={() => run.mutate(() => pa.createOffer({ application_id: offer.application_id, ctc_paise: Math.round(Number(offer.ctc_lpa) * 10_000_000), joining_on: offer.joining_on || null }), { onSuccess: () => toast.success('Offer created'), onError: fail })}>Create offer</Button>
          </div>
          <SimpleTable head={['Student', 'CTC', 'PPO', 'Joining', 'Status']} rows={list(offers.data).map((o: Any) => [o.student_name, lpa(o.ctc_paise), o.is_ppo ? 'yes' : '', day(o.joining_on), <StatusBadge key="s" status={o.status} />])} />
        </Section>
      )}
      {tab === 'feedback' && (
        <Section title="Company feedback">
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs">Candidates <Input className="w-16" type="number" min={1} max={5} value={fbk.candidates} onChange={(e) => setFbk({ ...fbk, candidates: Number(e.target.value) })} /></label>
            <label className="text-xs">Process <Input className="w-16" type="number" min={1} max={5} value={fbk.process} onChange={(e) => setFbk({ ...fbk, process: Number(e.target.value) })} /></label>
            <Input className="w-96" placeholder="Remarks" value={fbk.remarks} onChange={(e) => setFbk({ ...fbk, remarks: e.target.value })} />
            <Button size="sm" onClick={() => run.mutate(() => pa.driveFeedback(id, { ratings: { candidates: fbk.candidates, process: fbk.process }, remarks: fbk.remarks }), { onSuccess: () => toast.success('Feedback saved'), onError: fail })}>Save</Button>
          </div>
        </Section>
      )}
    </div>
  );
}

// ---- offers / profiles / blacklist ----------------------------------------------------------------------------------------
export function OffersPage() {
  useTitle('Offers');
  const [status, setStatus] = useState('');
  const [scope, setScope] = useState<string>();
  const res = useQ(['offers', status, scope], () => pa.offers({ status: status || undefined, scope }));
  const pending = useQ(['pending'], () => pa.pendingOffers());
  const run = useRun();
  const today = new Date().toISOString().slice(0, 10);
  const follow = list(res.data).filter((o: Any) => o.status === 'accepted' && o.joining_on && o.joining_on < today);
  return (
    <div className="space-y-4">
      <PageHeader title="Offers" description="All offers, recruiter submissions awaiting confirmation and joining follow-ups." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <Section title={`Pending recruiter offers (${list(pending.data).length})`}>
        <SimpleTable head={['Student', 'Reg. no', 'CTC', 'Submitted', '']} rows={list(pending.data).map((p: Any) => [p.student_name, p.registration_number, lpa(p.offer?.ctc_paise), when(p.submitted_at), <Button key="c" size="sm" onClick={() => run.mutate(() => pa.confirmPending(p.application_id), { onSuccess: () => toast.success('Offer confirmed'), onError: fail })}>Confirm</Button>])} />
      </Section>
      <Section title={`Joining follow-up (${follow.length})`}>
        <SimpleTable head={['Student', 'Company', 'Joining', '']} rows={follow.map((o: Any) => [o.student_name, o.company_name, day(o.joining_on), <div key="a" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => pa.offerStatus(o.id, 'joined'), { onError: fail })}>Joined</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.offerStatus(o.id, 'not_joined'), { onError: fail })}>Not joined</Button></div>])} />
      </Section>
      <Section title={`Offers (${list(res.data).length})`} action={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['offered', 'accepted', 'declined', 'revoked', 'joined', 'not_joined'].map((s) => <option key={s}>{s}</option>)}</select>}>
        <SimpleTable head={['Student', 'Company', 'Tier', 'CTC', 'PPO', 'Status', '']} rows={list(res.data).map((o: Any) => [o.student_name, o.company_name, o.company_tier, lpa(o.ctc_paise), o.is_ppo ? 'yes' : '', <StatusBadge key="s" status={o.status} />, !['revoked', 'declined'].includes(o.status) && <Button key="r" size="sm" variant="outline" onClick={() => { const reason = window.prompt('Revocation reason') ?? undefined; run.mutate(() => pa.offerStatus(o.id, 'revoked', reason), { onError: fail }); }}>Revoke</Button>])} />
      </Section>
    </div>
  );
}

export function ProfilesPage() {
  useTitle('Placement profiles');
  const [scope, setScope] = useState<string>();
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const res = useQ(['profiles', scope, status, q], () => pa.profiles({ scope, status: status || undefined, q: q || undefined }));
  const exportCsv = () => {
    const rows = list(res.data);
    const csv = ['registration_number,name,department,cgpa,status,completeness', ...rows.map((p: Any) => [p.registration_number, `"${p.student_name}"`, p.department_code, p.academics?.cgpa ?? '', p.placement_status, p.completeness].join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = 'placement-profiles.csv';
    a.click();
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Placement profiles" description="Completeness, status, opt-out and blacklist per student (contacts masked for auditors)." actions={<div className="flex gap-2"><ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} /><Button size="sm" variant="outline" onClick={exportCsv}>Export</Button></div>} />
      <div className="flex gap-2"><Input className="w-64" placeholder="Search reg. no / name" value={q} onChange={(e) => setQ(e.target.value)} /><select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['unplaced', 'placed', 'multiple', 'opted_out', 'blacklisted'].map((s) => <option key={s}>{s}</option>)}</select></div>
      <Section title={`Profiles (${list(res.data).length})`}>
        <SimpleTable head={['Student', 'Reg. no', 'Dept', 'CGPA', 'Backlogs', 'Skills', 'Completeness', 'Status', 'Consent']} rows={list(res.data).map((p: Any) => [p.student_name, p.registration_number, p.department_code, p.academics?.cgpa ?? '—', p.academics?.active_backlogs ?? 0, (p.skills ?? []).join(', '), `${p.completeness}%`, p.is_blacklisted ? <StatusBadge key="b" status="blacklisted" /> : <StatusBadge key="s" status={p.placement_status} />, p.consent_share_profile ? 'yes' : 'no'])} />
      </Section>
    </div>
  );
}

export function BlacklistPage() {
  useTitle('Placement blacklist');
  const res = useQ(['blacklist'], () => pa.blacklist());
  const [form, setForm] = useState<Any>({ enrollment_id: '', reason: '', until: '' });
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Blacklist" description="Manual and rule-based blacklists (no-show after shortlist, declined accepted offers) and discipline debarments." />
      <Section title="Blacklist a student">
        <div className="flex flex-wrap items-end gap-2">
          <Input className="w-80" placeholder="Enrolment id" value={form.enrollment_id} onChange={(e) => setForm({ ...form, enrollment_id: e.target.value })} />
          <Input className="w-80" placeholder="Reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <Input type="date" value={form.until} onChange={(e) => setForm({ ...form, until: e.target.value })} />
          <Button size="sm" variant="destructive" disabled={!form.enrollment_id || form.reason.length < 3} onClick={() => run.mutate(() => pa.addBlacklist({ ...form, until: form.until || null }), { onSuccess: () => toast.success('Blacklisted'), onError: fail })}>Blacklist</Button>
        </div>
      </Section>
      <Section title={`Blacklisted (${list(res.data).length})`}>
        <SimpleTable head={['Student', 'Reg. no', 'Reason', 'Source', 'Until', '']} rows={list(res.data).map((b: Any) => [b.student_name, b.registration_number, b.reason, b.source, b.until ?? '—', <Button key="u" size="sm" variant="outline" onClick={() => { const reason = window.prompt('Reason for lifting') ?? undefined; run.mutate(() => pa.removeBlacklist(b.student_program_enrollment_id, reason), { onSuccess: () => toast.success('Lifted'), onError: fail }); }}>Lift</Button>])} />
      </Section>
    </div>
  );
}

// ---- internships / training ---------------------------------------------------------------------------------------------
function EvaluateForm({ it, onDone }: { it: Any; onDone?: () => void }) {
  const [ev, setEv] = useState<Any>({ work: 8, report: 8, marks: 80, remarks: '' });
  const run = useRun();
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-xs">Work <Input className="w-16" type="number" value={ev.work} onChange={(e) => setEv({ ...ev, work: Number(e.target.value) })} /></label>
      <label className="text-xs">Report <Input className="w-16" type="number" value={ev.report} onChange={(e) => setEv({ ...ev, report: Number(e.target.value) })} /></label>
      <label className="text-xs">Marks /100 <Input className="w-20" type="number" value={ev.marks} onChange={(e) => setEv({ ...ev, marks: Number(e.target.value) })} /></label>
      <Input className="w-64" placeholder="Remarks" value={ev.remarks} onChange={(e) => setEv({ ...ev, remarks: e.target.value })} />
      <Button size="sm" onClick={() => run.mutate(() => pa.evaluate(it.id, { rubric_scores: { work: ev.work, report: ev.report }, marks: ev.marks, max_marks: 100, remarks: ev.remarks }), { onSuccess: () => { toast.success('Evaluated'); onDone?.(); }, onError: fail })}>Save evaluation</Button>
    </div>
  );
}

export function InternshipsPage() {
  useTitle('Internships');
  const [scope, setScope] = useState<string>();
  const [status, setStatus] = useState('');
  const [open, setOpen] = useState<string>();
  const res = useQ(['internships', scope, status], () => pa.internships({ scope, status: status || undefined }));
  const run = useRun();
  const rows = list(res.data);
  const nocQueue = rows.filter((i: Any) => i.evaluation?.noc && !i.noc_document_id);
  return (
    <div className="space-y-4">
      <PageHeader title="Internships" description="Records, NOC queue, evaluations (marks flow to the mapped internship course)." actions={<ScopeTabs visibility={(res.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <Section title={`NOC queue (${nocQueue.length})`}>
        <SimpleTable head={['Student', 'Company', 'Requested', '']} rows={nocQueue.map((i: Any) => [i.student_name, i.company_name, when(i.evaluation?.noc?.requested_at), <Button key="n" size="sm" onClick={() => run.mutate(() => pa.noc(i.id), { onSuccess: () => toast.success('NOC issued'), onError: fail })}>Issue NOC</Button>])} />
      </Section>
      <Section title={`Internships (${rows.length})`} action={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['planned', 'ongoing', 'completed', 'cancelled'].map((s) => <option key={s}>{s}</option>)}</select>}>
        <SimpleTable head={['Student', 'Dept', 'Company', 'Role', 'Weeks', 'NOC', 'Marks', 'Status', '']} rows={rows.map((i: Any) => [i.student_name, i.department_code, i.company_name, i.role, i.weeks ?? '—', i.noc_document_id ? 'issued' : '', i.evaluation?.marks ?? '—', <StatusBadge key="s" status={i.status} />, <Button key="e" size="sm" variant="outline" onClick={() => setOpen(open === i.id ? undefined : i.id)}>Evaluate</Button>])} />
        {open && <EvaluateForm it={rows.find((i: Any) => i.id === open)} onDone={() => setOpen(undefined)} />}
      </Section>
    </div>
  );
}

export function TrainingPage() {
  useTitle('Training');
  const res = useQ(['training'], () => pa.trainings());
  const [form, setForm] = useState<Any>({ training_type: 'aptitude', title: '', trainer: '', from_on: '', sessions: '' });
  const [bulk, setBulk] = useState<Any>({ program_id: '', text: '', kind: 'attendance' });
  const run = useRun();
  const parseBulk = () => bulk.text.split('\n').map((l: string) => l.split(',').map((x) => x.trim())).filter((x: string[]) => x[0]).map(([registration_number, v]: string[]) => (bulk.kind === 'attendance' ? { registration_number, sessions_attended: Number(v) || 0 } : { registration_number, score: Number(v) || 0 }));
  return (
    <div className="space-y-4">
      <PageHeader title="Training programmes" description="Aptitude, soft skills, technical and mock interviews with sessions, attendance and scores." />
      <Section title="New programme">
        <div className="flex flex-wrap items-end gap-2">
          <select className={sel} value={form.training_type} onChange={(e) => setForm({ ...form, training_type: e.target.value })}>{['aptitude', 'soft_skills', 'technical', 'mock_interview'].map((t) => <option key={t}>{t}</option>)}</select>
          <Input className="w-64" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input className="w-40" placeholder="Trainer / vendor" value={form.trainer} onChange={(e) => setForm({ ...form, trainer: e.target.value })} />
          <Input type="date" value={form.from_on} onChange={(e) => setForm({ ...form, from_on: e.target.value })} />
          <textarea className={area} placeholder="Sessions: one per line — 2026-11-02T10:00, Topic" value={form.sessions} onChange={(e) => setForm({ ...form, sessions: e.target.value })} />
          <Button size="sm" disabled={!form.title} onClick={() => run.mutate(() => pa.createTraining({ training_type: form.training_type, title: form.title, trainer: form.trainer || null, from_on: form.from_on || null, sessions: form.sessions.split('\n').filter(Boolean).map((l: string) => { const [at, ...topic] = l.split(','); return { at: new Date(at.trim()).toISOString(), topic: topic.join(',').trim() || 'Session' }; }) }), { onSuccess: () => toast.success('Programme created'), onError: fail })}>Create</Button>
        </div>
      </Section>
      <Section title="Attendance / scores import">
        <div className="flex flex-wrap items-end gap-2">
          <select className={sel} value={bulk.program_id} onChange={(e) => setBulk({ ...bulk, program_id: e.target.value })}><option value="">Programme…</option>{list(res.data).map((p: Any) => <option key={p.id} value={p.id}>{p.title}</option>)}</select>
          <select className={sel} value={bulk.kind} onChange={(e) => setBulk({ ...bulk, kind: e.target.value })}><option value="attendance">Sessions attended</option><option value="scores">Scores</option></select>
          <textarea className={area} placeholder="registration_number, value — one per line" value={bulk.text} onChange={(e) => setBulk({ ...bulk, text: e.target.value })} />
          <Button size="sm" disabled={!bulk.program_id || !bulk.text} onClick={() => run.mutate(() => (bulk.kind === 'attendance' ? pa.trainingAttendance(bulk.program_id, parseBulk()) : pa.trainingScores(bulk.program_id, parseBulk())), { onSuccess: (r: Any) => toast.success(`${r.data.succeeded} saved, ${r.data.failed.length} failed`), onError: fail })}>Import</Button>
        </div>
      </Section>
      <Section title="Programmes">
        <SimpleTable head={['Programme', 'Type', 'Trainer', 'From', 'Sessions', 'Participants', 'Avg score']} rows={list(res.data).map((p: Any) => [p.title, p.training_type, p.trainer, day(p.from_on), (p.sessions ?? []).length, p.participants, p.avg_score ?? '—'])} />
      </Section>
    </div>
  );
}

export function StatsPage() {
  useTitle('Placement statistics');
  const [batch, setBatch] = useState('');
  const res = useQ(['stats', batch], () => pa.stats({ batch_id: batch || undefined }));
  const run = useRun();
  const s: Any = res.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Placement statistics" description="NAAC 5.2.1 / 5.2.2 and NIRF GMS on the configured median basis." actions={<div className="flex gap-2"><Input className="w-72" placeholder="Batch id (optional)" value={batch} onChange={(e) => setBatch(e.target.value)} /><Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.nirfSheet({ batch_id: batch || undefined }), { onSuccess: () => toast.success('NIRF sheet export queued — see Jobs'), onError: fail })}>NIRF sheet</Button></div>} />
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Placed %" value={`${s.placed_pct ?? 0}%`} />
        <Stat label="Placed / eligible − opted out" value={`${s.placed ?? 0} / ${(s.eligible ?? 0) - (s.opted_out ?? 0)}`} />
        <Stat label="Median CTC" value={lpa(s.median_ctc_paise)} />
        <Stat label="Highest CTC" value={lpa(s.highest_ctc_paise)} />
        <Stat label="Average CTC" value={lpa(s.avg_ctc_paise)} />
        <Stat label="Higher studies" value={`${s.higher_studies ?? 0} (${s.higher_studies_pct ?? 0}%)`} />
        <Stat label="Offers (PPO)" value={`${s.offers ?? 0} (${s.ppo ?? 0})`} />
        <Stat label="Internships %" value={`${s.internships_pct ?? 0}%`} />
      </div>
      <Section title="By programme"><SimpleTable head={['Programme', 'Eligible', 'Opted out', 'Placed', 'Placed %', 'Median CTC']} rows={(s.by_program ?? []).map((r: Any) => [r.program, r.eligible, r.opted_out, r.placed, `${r.placed_pct}%`, lpa(r.median_ctc_paise)])} /></Section>
      <Section title="By tier"><SimpleTable head={['Tier', 'Accepted offers']} rows={(s.by_tier ?? []).map((r: Any) => [r.tier, r.accepted])} /></Section>
      <Section title="Top recruiters"><SimpleTable head={['Company', 'Offers', 'Accepted', 'Max CTC']} rows={(s.by_company ?? []).map((r: Any) => [r.company, r.offers, r.accepted, lpa(r.max_ctc_paise)])} /></Section>
      <div className="flex gap-2">{['drives', 'offers', 'internships', 'training'].map((k) => <Button key={k} size="sm" variant="outline" onClick={() => run.mutate(() => pa.report(k), { onSuccess: () => toast.success(`${k} report queued`), onError: fail })}>{k} report</Button>)}</div>
    </div>
  );
}

// ---- student / parent / faculty portals ------------------------------------------------------------------------------------
export function StudentPlacementPage() {
  useTitle('Placement');
  const [tab, setTab] = useState('drives');
  const prof = useQ(['me-profile'], () => pa.myProfile());
  const drives = useQ(['open'], () => pa.openDrives());
  const apps = useQ(['my-apps'], () => pa.myApplications());
  const offers = useQ(['my-offers'], () => pa.myOffers());
  const interns = useQ(['my-interns'], () => pa.myInternships(), tab === 'internships');
  const training = useQ(['my-training'], () => pa.myTraining(), tab === 'training');
  const run = useRun();
  const p: Any = prof.data?.data ?? {};
  const [skills, setSkills] = useState('');
  const [summary, setSummary] = useState('');
  const [tpl, setTpl] = useState('resume_classic');
  const [optOut, setOptOut] = useState<Any>({ reason: 'higher_studies', exam: '', institution: '' });
  const [intern, setIntern] = useState<Any>({ company_name: '', role: '', from_on: '', to_on: '' });
  useEffect(() => { setSkills((p.skills ?? []).join(', ')); setSummary(p.resume_json?.summary ?? ''); }, [p.skills, p.resume_json?.summary]);
  return (
    <div className="space-y-4">
      <PageHeader title="Placement" description={`Status: ${p.placement_status ?? '—'} · profile ${p.completeness ?? 0}% complete${p.is_blacklisted ? ' · blacklisted' : ''}`} />
      <Tabs tabs={['drives', 'applications', 'offers', 'profile', 'internships', 'training']} value={tab} onChange={setTab} />
      {tab === 'drives' && (
        <Section title="Open drives">
          <SimpleTable head={['Drive', 'Company', 'CTC', 'Deadline', 'My eligibility', '']} rows={list(drives.data).map((d: Any) => [d.title, `${d.company_name} (${d.company_tier ?? ''})`, lpa(d.ctc_min_paise), when(d.registration_deadline), <Reasons key="r" reasons={d.my_eligibility?.reasons} />, d.my_application_id ? <StatusBadge key="s" status={d.my_application_status} /> : <Button key="a" size="sm" disabled={!d.my_eligibility?.is_eligible} onClick={() => run.mutate(() => pa.apply(d.id), { onSuccess: () => toast.success('Applied'), onError: fail })}>Apply</Button>])} />
        </Section>
      )}
      {tab === 'applications' && (
        <Section title="My applications">
          {list(apps.data).map((a: Any) => (
            <Card key={a.id}><CardContent className="space-y-1 p-3 text-sm">
              <div className="flex justify-between"><p className="font-medium">{a.company_name} — {a.drive_title}</p><StatusBadge status={a.status} /></div>
              <p className="text-xs text-muted-foreground">Applied {day(a.applied_at)} · CGPA at apply {a.eligibility_snapshot?.cgpa ?? '—'}</p>
              <ol className="ml-4 list-decimal text-xs">{(a.rounds ?? []).map((r: Any) => <li key={r.round_id}>{r.name} — {when(r.scheduled_at)} {r.venue ?? ''} · {r.status}</li>)}</ol>
              {a.status === 'applied' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.withdraw(a.id), { onSuccess: () => toast.success('Withdrawn'), onError: fail })}>Withdraw</Button>}
            </CardContent></Card>
          ))}
        </Section>
      )}
      {tab === 'offers' && (
        <Section title="My offers">
          {list(offers.data).map((o: Any) => (
            <Card key={o.id}><CardContent className="space-y-2 p-3 text-sm">
              <div className="flex justify-between"><p className="font-medium">{o.company_name} — {o.role}</p><StatusBadge status={o.status} /></div>
              <p>{lpa(o.ctc_paise)} · joining {day(o.joining_on)} {o.is_ppo ? '· PPO' : ''} {o.is_dream ? '· dream' : ''}</p>
              {o.policy_warning && <p className="text-xs text-amber-700">{o.policy_warning}</p>}
              {o.status === 'offered' && <div className="flex gap-2"><Button size="sm" onClick={() => run.mutate(() => pa.decide(o.id, 'accept'), { onSuccess: () => toast.success('Offer accepted'), onError: fail })}>Accept</Button><Button size="sm" variant="outline" onClick={() => { const reason = window.prompt('Reason for declining') ?? undefined; run.mutate(() => pa.decide(o.id, 'decline', reason), { onError: fail }); }}>Decline</Button></div>}
            </CardContent></Card>
          ))}
        </Section>
      )}
      {tab === 'profile' && (
        <>
          <Section title="Academics (read-only)">
            <div className="grid gap-3 md:grid-cols-4"><Stat label="CGPA" value={p.academics?.cgpa} /><Stat label="Active backlogs" value={p.academics?.active_backlogs} /><Stat label="Attendance %" value={p.academics?.attendance_pct} /><Stat label="12th %" value={p.academics?.pct_12} /></div>
            <p className="text-xs text-muted-foreground">Verified achievements: {(p.achievements ?? []).map((a: Any) => a.title).join(', ') || 'none'}</p>
          </Section>
          <Section title="Resume builder">
            <Input placeholder="Skills (comma separated)" value={skills} onChange={(e) => setSkills(e.target.value)} />
            <textarea className={area} placeholder="Summary" value={summary} onChange={(e) => setSummary(e.target.value)} />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!p.consent_share_profile} onChange={(e) => run.mutate(() => pa.updateProfile({ consent_share_profile: e.target.checked }), { onError: fail })} />Share my profile with recruiters (DPDP consent)</label>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => run.mutate(() => pa.updateProfile({ skills: skills.split(',').map((s) => s.trim()).filter(Boolean), resume_json: { summary } }), { onSuccess: () => toast.success('Profile saved'), onError: fail })}>Save</Button>
              <select className={sel} value={tpl} onChange={(e) => setTpl(e.target.value)}><option value="resume_classic">Classic</option><option value="resume_modern">Modern</option><option value="resume_compact">Compact</option></select>
              <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.renderResume(tpl), { onSuccess: (r: Any) => { toast.success('Resume rendered'); if (r.data?.pdf_url) window.open(r.data.pdf_url, '_blank'); }, onError: fail })}>Render PDF</Button>
            </div>
          </Section>
          <Section title={p.is_opted_out ? `Opted out (${p.opt_out_reason})` : 'Opt out of placements'}>
            {p.is_opted_out ? <Button size="sm" variant="outline" onClick={() => run.mutate(() => pa.optOut({ opt_out: false }), { onError: fail })}>Opt back in</Button> : (
              <div className="flex flex-wrap items-end gap-2">
                <select className={sel} value={optOut.reason} onChange={(e) => setOptOut({ ...optOut, reason: e.target.value })}>{['higher_studies', 'entrepreneurship', 'family_business', 'govt_exams', 'other'].map((r) => <option key={r}>{r}</option>)}</select>
                {optOut.reason === 'higher_studies' && <><Input className="w-32" placeholder="Exam (GATE…)" value={optOut.exam} onChange={(e) => setOptOut({ ...optOut, exam: e.target.value })} /><Input className="w-56" placeholder="Institution" value={optOut.institution} onChange={(e) => setOptOut({ ...optOut, institution: e.target.value })} /></>}
                <Button size="sm" variant="destructive" onClick={() => run.mutate(() => pa.optOut({ opt_out: true, reason: optOut.reason, higher_studies: optOut.reason === 'higher_studies' ? { exam: optOut.exam, institution: optOut.institution } : null }), { onSuccess: () => toast.success('Opted out'), onError: fail })}>Opt out</Button>
              </div>
            )}
          </Section>
        </>
      )}
      {tab === 'internships' && (
        <Section title="My internships">
          <div className="flex flex-wrap items-end gap-2">
            <Input className="w-56" placeholder="Company" value={intern.company_name} onChange={(e) => setIntern({ ...intern, company_name: e.target.value })} />
            <Input className="w-40" placeholder="Role" value={intern.role} onChange={(e) => setIntern({ ...intern, role: e.target.value })} />
            <Input type="date" value={intern.from_on} onChange={(e) => setIntern({ ...intern, from_on: e.target.value })} />
            <Input type="date" value={intern.to_on} onChange={(e) => setIntern({ ...intern, to_on: e.target.value })} />
            <Button size="sm" disabled={!intern.company_name || !intern.from_on} onClick={() => run.mutate(() => pa.createInternship({ ...intern, to_on: intern.to_on || null }), { onSuccess: () => toast.success('Internship recorded'), onError: fail })}>Add</Button>
          </div>
          <SimpleTable head={['Company', 'Role', 'From', 'To', 'NOC', 'Marks', 'Status']} rows={list(interns.data).map((i: Any) => [i.company_name, i.role, day(i.from_on), day(i.to_on), i.noc_document_id ? 'ready' : <Button key="n" size="sm" variant="outline" onClick={() => run.mutate(() => pa.noc(i.id, { purpose: 'Internship' }), { onSuccess: () => toast.success('NOC requested'), onError: fail })}>Request NOC</Button>, i.evaluation?.marks ?? '—', <StatusBadge key="s" status={i.status} />])} />
        </Section>
      )}
      {tab === 'training' && (
        <Section title="My training">
          <SimpleTable head={['Programme', 'Type', 'Next session', 'Attended', 'Score']} rows={list(training.data).map((t: Any) => [t.title, t.training_type, when((t.sessions ?? []).map((s: Any) => s.at).find((at: string) => new Date(at) > new Date())), `${t.sessions_attended}/${(t.sessions ?? []).length}`, t.score ?? '—'])} />
        </Section>
      )}
    </div>
  );
}

export function ParentPlacementPage() {
  useTitle('Ward placement');
  const apps = useQ(['ward-apps'], () => pa.wardApplications());
  const offers = useQ(['ward-offers'], () => pa.wardOffers());
  return (
    <div className="space-y-4">
      <PageHeader title="Ward placement" description="Your ward's drives, rounds and offers (read only)." />
      <Section title="Offers"><SimpleTable head={['Student', 'Company', 'CTC', 'Joining', 'Status']} rows={list(offers.data).map((o: Any) => [o.student_name, o.company_name, lpa(o.ctc_paise), day(o.joining_on), <StatusBadge key="s" status={o.status} />])} /></Section>
      <Section title="Applications"><SimpleTable head={['Student', 'Company', 'Drive', 'Applied', 'Status']} rows={list(apps.data).map((a: Any) => [a.student_name, a.company_name, a.drive_title, day(a.applied_at), <StatusBadge key="s" status={a.status} />])} /></Section>
    </div>
  );
}

export function FacultyInternshipsPage() {
  useTitle('Internship evaluation');
  const res = useQ(['fac-interns'], () => pa.internships({ scope: 'own' }));
  const [open, setOpen] = useState<string>();
  const rows = list(res.data);
  return (
    <div className="space-y-4">
      <PageHeader title="Internship evaluation" description="Internships mapped to the courses you teach." />
      <Section title={`Assigned (${rows.length})`}>
        <SimpleTable head={['Student', 'Company', 'Weeks', 'Marks', 'Status', '']} rows={rows.map((i: Any) => [i.student_name, i.company_name, i.weeks ?? '—', i.evaluation?.marks ?? '—', <StatusBadge key="s" status={i.status} />, <Button key="e" size="sm" variant="outline" onClick={() => setOpen(open === i.id ? undefined : i.id)}>Evaluate</Button>])} />
        {open && <EvaluateForm it={rows.find((i: Any) => i.id === open)} onDone={() => setOpen(undefined)} />}
      </Section>
    </div>
  );
}

// ---- recruiter portal ---------------------------------------------------------------------------------------------------
export function RecruiterDrivesPage() {
  useTitle('Recruiter — drives');
  const me = useQ(['rec-me'], () => pa.recruiterMe());
  const res = useQ(['rec-drives'], () => pa.recruiterDrives());
  const [form, setForm] = useState<Any>({ title: '', ctc_lpa: 6, company_id: '' });
  const run = useRun();
  const companies = me.data?.data?.companies ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="Drives" description={`Recruiting for ${companies.map((c: Any) => c.name).join(', ') || '—'}. New drives stay in draft until the placement office publishes them.`} />
      <Section title="Post a drive">
        <div className="flex flex-wrap items-end gap-2">
          {companies.length > 1 && <select className={sel} value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })}><option value="">Company…</option>{companies.map((c: Any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>}
          <Input className="w-64" placeholder="Title / role" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <label className="text-xs">CTC (LPA) <Input className="w-20" type="number" value={form.ctc_lpa} onChange={(e) => setForm({ ...form, ctc_lpa: e.target.value })} /></label>
          <Button size="sm" disabled={!form.title} onClick={() => run.mutate(() => pa.recruiterCreateDrive({ title: form.title, ctc_min_paise: Math.round(Number(form.ctc_lpa) * 10_000_000), company_id: form.company_id || undefined }), { onSuccess: () => toast.success('Draft submitted'), onError: fail })}>Submit draft</Button>
        </div>
      </Section>
      <Section title="My drives">
        <SimpleTable head={['Drive', 'CTC', 'Date', 'Applications', 'Status']} rows={list(res.data).map((d: Any) => [<Link key="l" className="text-primary underline" to={`/recruiter/drives/${d.id}`}>{d.title}</Link>, lpa(d.ctc_min_paise), day(d.drive_on), d.applications, <StatusBadge key="s" status={d.status} />])} />
      </Section>
    </div>
  );
}

export function RecruiterDrivePage() {
  const { id = '' } = useParams();
  useTitle('Recruiter — applicants');
  const res = useQ(['rec-apps', id], () => pa.recruiterApplicants(id));
  const [round, setRound] = useState<Any>({ round_no: 1, name: '', round_type: 'technical', scheduled_at: '' });
  const [results, setResults] = useState<Any>({ round_id: '', text: '', status: 'cleared' });
  const [offer, setOffer] = useState<Any>({ application_id: '', ctc_lpa: 6 });
  const [fb, setFb] = useState('');
  const run = useRun();
  const rows = list(res.data);
  const rounds = Array.from(new Map(rows.flatMap((a: Any) => a.rounds ?? []).map((r: Any) => [r.round_id, r])).values()) as Any[];
  const download = async () => {
    try {
      const blob = await pa.recruiterShortlist(id);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob instanceof Blob ? blob : new Blob([blob as BlobPart]));
      a.download = `shortlist-${id}.xlsx`;
      a.click();
    } catch (e) { fail(e); }
  };
  const keys = Array.from(new Set(rows.flatMap((a: Any) => Object.keys(a.fields ?? {})))) as string[];
  return (
    <div className="space-y-4">
      <PageHeader title="Applicants" description="Consented fields only; students who did not consent are not listed." actions={<Button size="sm" variant="outline" onClick={download}>Shortlist (xlsx)</Button>} />
      <Section title={`Applicants (${rows.length})`}>
        <SimpleTable head={['Status', ...keys]} rows={rows.map((a: Any) => [<StatusBadge key="s" status={a.status} />, ...keys.map((k) => { const v = a.fields?.[k]; return Array.isArray(v) ? v.map((x: Any) => (typeof x === 'object' ? x.title : x)).join(', ') : typeof v === 'object' && v ? JSON.stringify(v) : v ?? '—'; })])} />
      </Section>
      <Section title="Rounds & results">
        <div className="flex flex-wrap items-end gap-2">
          <Input className="w-16" type="number" value={round.round_no} onChange={(e) => setRound({ ...round, round_no: Number(e.target.value) })} />
          <Input className="w-48" placeholder="Round name" value={round.name} onChange={(e) => setRound({ ...round, name: e.target.value })} />
          <select className={sel} value={round.round_type} onChange={(e) => setRound({ ...round, round_type: e.target.value })}>{['aptitude', 'coding', 'gd', 'technical', 'hr', 'final'].map((t) => <option key={t}>{t}</option>)}</select>
          <Input type="datetime-local" value={round.scheduled_at} onChange={(e) => setRound({ ...round, scheduled_at: e.target.value })} />
          <Button size="sm" disabled={!round.name} onClick={() => run.mutate(() => pa.recruiterAddRound(id, { ...round, scheduled_at: round.scheduled_at ? new Date(round.scheduled_at).toISOString() : null }), { onSuccess: () => toast.success('Round scheduled'), onError: fail })}>Schedule</Button>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Input className="w-80" placeholder="Round id" value={results.round_id} onChange={(e) => setResults({ ...results, round_id: e.target.value })} list="rec-rounds" />
          <datalist id="rec-rounds">{rounds.map((r: Any) => <option key={r.round_id} value={r.round_id}>{r.name}</option>)}</datalist>
          <select className={sel} value={results.status} onChange={(e) => setResults({ ...results, status: e.target.value })}>{['cleared', 'not_cleared', 'absent'].map((s) => <option key={s}>{s}</option>)}</select>
          <textarea className={area} placeholder="Registration numbers" value={results.text} onChange={(e) => setResults({ ...results, text: e.target.value })} />
          <Button size="sm" disabled={!results.round_id || !results.text} onClick={() => run.mutate(() => pa.recruiterResults(results.round_id, { rows: regsToRows(results.text).map((r) => ({ ...r, status: results.status })) }), { onSuccess: (r: Any) => toast.success(`${r.data.succeeded} recorded`), onError: fail })}>Upload results</Button>
        </div>
      </Section>
      <Section title="Offer (placement office confirms)">
        <div className="flex flex-wrap items-end gap-2">
          <select className={sel} value={offer.application_id} onChange={(e) => setOffer({ ...offer, application_id: e.target.value })}><option value="">Selected candidate…</option>{rows.filter((a: Any) => a.status === 'selected').map((a: Any) => <option key={a.application_id} value={a.application_id}>{a.fields?.name ?? a.fields?.registration_number}</option>)}</select>
          <label className="text-xs">CTC (LPA) <Input className="w-20" type="number" value={offer.ctc_lpa} onChange={(e) => setOffer({ ...offer, ctc_lpa: e.target.value })} /></label>
          <Button size="sm" disabled={!offer.application_id} onClick={() => run.mutate(() => pa.recruiterOffer(id, { application_id: offer.application_id, ctc_paise: Math.round(Number(offer.ctc_lpa) * 10_000_000) }), { onSuccess: () => toast.success('Offer submitted for confirmation'), onError: fail })}>Submit offer</Button>
        </div>
      </Section>
      <Section title="Feedback">
        <div className="flex gap-2"><Input className="w-96" placeholder="Feedback on the process" value={fb} onChange={(e) => setFb(e.target.value)} /><Button size="sm" disabled={!fb} onClick={() => run.mutate(() => pa.recruiterFeedback(id, { ratings: { process: 4 }, remarks: fb }), { onSuccess: () => toast.success('Thanks for the feedback'), onError: fail })}>Send</Button></div>
      </Section>
    </div>
  );
}
