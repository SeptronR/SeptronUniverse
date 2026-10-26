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
import { govApi as ga } from '../api';

// Phase 33 web screens (Prompts/33 §33.9). Membership / secretary / chair / owner / holder / PIO / legal visibility,
// quorum blocking, numbering and approvals are enforced by the API; these screens only present them.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const done = (m: string) => () => toast.success(m);
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['gov', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['gov'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const data = (r: Any) => r?.data;
const day = (s?: string | null) => (s ? new Date(s).toLocaleDateString() : '—');
const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');
const rupees = (p?: number | null) => (p === null || p === undefined ? '—' : `₹${(p / 100).toLocaleString('en-IN')}`);
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-[120px] w-full rounded-md border bg-background p-2 text-sm';
const openBlob = (b: Blob) => window.open(URL.createObjectURL(b), '_blank');
const POLICY_CATS = ['academic', 'examination', 'it', 'posh', 'anti_ragging', 'research_ethics', 'data_protection', 'hr', 'finance', 'hostel', 'conduct'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value ?? '—'}</p></CardContent></Card>;
}
function Err({ q }: { q: Any }) {
  return q.isError ? <p className="text-sm text-destructive">{getApiError(q.error)}</p> : null;
}
function Badge({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs ${ok ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>{label}</span>;
}

// ---- committees -----------------------------------------------------------------------------------------------------------
export function CommitteesPage() {
  useTitle('Committees');
  const [type, setType] = useState('');
  const q = useQ(['committees', type], () => ga.committees({ committee_type: type || undefined }));
  const cov = useQ(['coverage'], () => ga.coverage());
  const tpl = useQ(['templates'], () => ga.templates());
  const run = useRun();
  const [f, setF] = useState<Any>({ template_key: '', department_id: '', chair_staff_id: '', secretary_staff_id: '' });
  const create = () => run.mutate(() => ga.fromTemplate({ template_key: f.template_key, department_id: f.department_id || undefined, chair_staff_id: f.chair_staff_id || undefined, secretary_staff_id: f.secretary_staff_id || undefined }), { onSuccess: done('Committee constituted'), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Committees" description="Statutory and custom committees with members, tenure, quorum rules, validity and coverage." />
      <Section title="Statutory coverage">
        <div className="flex flex-wrap gap-2">{list(cov.data).map((c: Any) => <span key={c.committee_type} className="flex items-center gap-1 text-sm">{c.committee_type}{c.mandatory && '*'} <Badge ok={c.present && c.valid} label={c.present ? (c.valid ? 'valid' : 'expired') : 'missing'} /></span>)}</div>
      </Section>
      <Section title="Constitute from a template">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.template_key} onChange={(e) => setF({ ...f, template_key: e.target.value })}><option value="">Template…</option>{list(tpl.data).map((t: Any) => <option key={t.template_key} value={t.template_key}>{t.name}</option>)}</select>
          <Input className="w-64" placeholder="Department id (BoS)" value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })} />
          <Input className="w-64" placeholder="Chair staff id" value={f.chair_staff_id} onChange={(e) => setF({ ...f, chair_staff_id: e.target.value })} />
          <Input className="w-64" placeholder="Secretary staff id" value={f.secretary_staff_id} onChange={(e) => setF({ ...f, secretary_staff_id: e.target.value })} />
          <Button size="sm" disabled={!f.template_key} onClick={create}>Constitute</Button>
        </div>
      </Section>
      <div className="flex gap-2"><Input className="w-56" placeholder="Filter by type" value={type} onChange={(e) => setType(e.target.value)} /></div>
      <Err q={q} />
      <SimpleTable head={['Committee', 'Type', 'Code', 'Chair', 'Members', 'Valid to', 'Next meeting', 'Open res.', 'ATR pending']} rows={list(q.data).map((c: Any) => [<Link key="n" className="text-primary underline" to={`/admin/governance/committees/${c.id}`}>{c.name}</Link>, c.committee_type, c.code, c.chair_name ?? '—', c.members, <Badge key="v" ok={c.valid} label={day(c.valid_to)} />, when(c.next_meeting), c.open_resolutions, c.pending_atrs])} />
    </div>
  );
}

export function CommitteePage() {
  const { id = '' } = useParams();
  const q = useQ(['committee', id], () => ga.committee(id));
  const c: Any = data(q.data);
  useTitle(c?.name ?? 'Committee');
  const run = useRun();
  const [m, setM] = useState<Any>({ member_type: 'staff', staff_id: '', role: 'member', name: '', org: '' });
  const [recon, setRecon] = useState('');
  const add = () => run.mutate(() => ga.addMember(id, m.member_type === 'external' ? { member_type: 'external', role: m.role, external: { name: m.name, org: m.org } } : { member_type: m.member_type, staff_id: m.staff_id || undefined, user_id: m.user_id || undefined, role: m.role }), { onSuccess: done('Member added'), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title={c?.name ?? 'Committee'} description={c ? `${c.committee_type} · ${c.code} · quorum ${c.quorum_rule?.value ?? '1/2'} · valid ${day(c.constituted_on)} – ${day(c.valid_to)}` : ''} />
      <Err q={q} />
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Members (tenure)">
          <SimpleTable head={['Name', 'Type', 'Role', 'From', 'To', '']} rows={(c?.member_list ?? []).map((x: Any) => [x.name ?? '—', x.member_type, x.role, day(x.from_on), day(x.to_on), x.active ? <Button key="r" size="sm" variant="outline" onClick={() => run.mutate(() => ga.removeMember(x.id), { onError: fail })}>End</Button> : 'past'])} />
          <div className="flex flex-wrap gap-2">
            <select className={sel} value={m.member_type} onChange={(e) => setM({ ...m, member_type: e.target.value })}><option>staff</option><option>student</option><option>external</option></select>
            {m.member_type === 'external' ? <><Input className="w-40" placeholder="Name" value={m.name} onChange={(e) => setM({ ...m, name: e.target.value })} /><Input className="w-40" placeholder="Organisation" value={m.org} onChange={(e) => setM({ ...m, org: e.target.value })} /></> : <Input className="w-64" placeholder={m.member_type === 'staff' ? 'Staff id' : 'User id'} value={m.member_type === 'staff' ? m.staff_id : m.user_id ?? ''} onChange={(e) => setM(m.member_type === 'staff' ? { ...m, staff_id: e.target.value } : { ...m, user_id: e.target.value })} />}
            <select className={sel} value={m.role} onChange={(e) => setM({ ...m, role: e.target.value })}>{['member', 'chair', 'secretary', 'convenor', 'special_invitee'].map((r) => <option key={r}>{r}</option>)}</select>
            <Button size="sm" onClick={add}>Add</Button>
          </div>
        </Section>
        <Section title="Reconstitute (new tenure)">
          <div className="flex gap-2"><Input type="date" className="w-44" value={recon} onChange={(e) => setRecon(e.target.value)} /><Button size="sm" disabled={!recon} onClick={() => run.mutate(() => ga.reconstitute(id, { constituted_on: recon }), { onSuccess: done('Reconstituted'), onError: fail })}>Reconstitute</Button></div>
          <SimpleTable head={['From', 'To', 'Members']} rows={(c?.history ?? []).map((h: Any) => [day(h.constituted_on), day(h.valid_to), h.members])} />
        </Section>
      </div>
      <Section title="Meetings">
        <SimpleTable head={['No.', 'Held on', 'Status', '']} rows={(c?.meetings ?? []).map((x: Any) => [x.meeting_no, when(x.held_on), <StatusBadge key="s" status={x.status} />, <Link key="o" className="text-primary underline" to={`/admin/governance/meetings/${x.id}`}>Open</Link>])} />
      </Section>
    </div>
  );
}

// ---- meetings ---------------------------------------------------------------------------------------------------------------
export function MeetingsPage() {
  useTitle('Meetings');
  const [scope, setScope] = useState<string | undefined>();
  const q = useQ(['meetings', scope], () => ga.meetings({ scope }));
  const coms = useQ(['committees-all'], () => ga.committees({ active: true }));
  const run = useRun();
  const [f, setF] = useState<Any>({ committee_id: '', held_on: '', venue_or_link: '', item: '' });
  const create = () => run.mutate(() => ga.createMeeting({ committee_id: f.committee_id, held_on: new Date(f.held_on).toISOString(), venue_or_link: f.venue_or_link || undefined, agenda: f.item ? [{ item: f.item }] : [] }), { onSuccess: done('Meeting scheduled'), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Meetings" description="Schedule, notice, attendance and quorum, minutes approval and resolutions." actions={<ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <Section title="Schedule a meeting">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.committee_id} onChange={(e) => setF({ ...f, committee_id: e.target.value })}><option value="">Committee…</option>{list(coms.data).map((c: Any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <Input type="datetime-local" className="w-56" value={f.held_on} onChange={(e) => setF({ ...f, held_on: e.target.value })} />
          <Input className="w-48" placeholder="Venue / link" value={f.venue_or_link} onChange={(e) => setF({ ...f, venue_or_link: e.target.value })} />
          <Input className="w-72" placeholder="First agenda item" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} />
          <Button size="sm" disabled={!f.committee_id || !f.held_on} onClick={create}>Schedule</Button>
        </div>
      </Section>
      <Err q={q} />
      <SimpleTable head={['Committee', 'No.', 'Held on', 'Status', 'Quorum', '']} rows={list(q.data).map((m: Any) => [m.committee_name, m.meeting_no, when(m.held_on), <StatusBadge key="s" status={m.status} />, m.quorum_met === null || m.quorum_met === undefined ? '—' : m.quorum_met ? 'met' : 'not met', <Link key="o" className="text-primary underline" to={`/admin/governance/meetings/${m.id}`}>Open</Link>])} />
    </div>
  );
}

export function MeetingPage() {
  const { id = '' } = useParams();
  const q = useQ(['meeting', id], () => ga.meeting(id));
  const m: Any = data(q.data);
  useTitle(m ? `${m.committee_name} ${m.meeting_no}` : 'Meeting');
  const run = useRun();
  const sug = useQ(['suggestions', id], () => ga.suggestions(id), !!m?.can_edit);
  const com = useQ(['committee', m?.committee_id], () => ga.committee(m.committee_id), !!m?.committee_id);
  const [present, setPresent] = useState<string[]>([]);
  const [minutes, setMinutes] = useState('');
  const [res, setRes] = useState<Any[]>([]);
  const [r, setR] = useState<Any>({ subject: '', text: '', status: 'passed', action_owner_staff_id: '' });
  const [corr, setCorr] = useState('');
  const agenda = m?.agenda ?? [];
  const addItem = (item: Any) => run.mutate(() => ga.setAgenda(id, { agenda: [...agenda, item] }), { onError: fail });
  const members = (data(com.data)?.member_list ?? []).filter((x: Any) => x.active);
  return (
    <div className="space-y-4">
      <PageHeader title={m ? `${m.committee_name} — meeting ${m.meeting_no}` : 'Meeting'} description={m ? `${when(m.held_on)} · ${m.venue_or_link ?? ''}${m.short_notice ? ' · short notice' : ''}` : ''} actions={m && <div className="flex gap-2"><StatusBadge status={m.status} />{m.status === 'minutes_approved' && <Button size="sm" variant="outline" onClick={() => ga.minutesPdf(id).then(openBlob, fail)}>Minutes PDF</Button>}</div>} />
      <Err q={q} />
      <div className="grid gap-4 md:grid-cols-2">
        <Section title={`Agenda${m?.agenda_frozen ? ' (frozen)' : ''}`} action={m?.can_edit && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.notice(id, ['in_app', 'email']), { onSuccess: done('Notice sent'), onError: fail })}>Send notice</Button>}>
          <ol className="list-decimal space-y-1 pl-5 text-sm">{agenda.map((a: Any, i: number) => <li key={i}>{a.item}{a.doc_url && <a className="ml-1 text-primary underline" href={a.doc_url}>doc</a>}{a.linked_entity && <span className="ml-1 rounded bg-muted px-1 text-xs">{a.linked_entity.entity_type}</span>}</li>)}</ol>
          {m?.can_edit && (list(sug.data).length > 0) && <div className="space-y-1"><p className="text-xs font-medium">Suggestions</p>{list(sug.data).map((s: Any, i: number) => <div key={i} className="flex items-center justify-between gap-2 text-xs"><span>[{s.source}] {s.item}</span><Button size="sm" variant="outline" onClick={() => addItem({ item: s.item, linked_entity: s.linked_entity, source: s.source })}>Add</Button></div>)}</div>}
        </Section>
        <Section title="Attendance & quorum" action={m?.quorum && <Badge ok={m.quorum.met} label={`${m.quorum.present}/${m.quorum.total} (need ${m.quorum.required})`} />}>
          {m?.can_edit ? (
            <>
              <div className="grid grid-cols-2 gap-1 text-sm">{members.map((x: Any) => <label key={x.id} className="flex items-center gap-2"><input type="checkbox" checked={present.includes(x.id) || (m.attendance?.present_member_ids ?? []).includes(x.id)} onChange={(e) => setPresent(e.target.checked ? [...present, x.id] : present.filter((p) => p !== x.id))} />{x.name ?? x.member_type} <span className="text-xs text-muted-foreground">{x.role}</span></label>)}</div>
              <Button size="sm" onClick={() => run.mutate(() => ga.attendance(id, { present_member_ids: Array.from(new Set([...(m.attendance?.present_member_ids ?? []), ...present])) }), { onError: fail })}>Save attendance</Button>
            </>
          ) : <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.attendance(id, { self_check_in: true }), { onSuccess: done('Marked present'), onError: fail })}>Mark me present</Button>}
        </Section>
      </div>
      <Section title={`Minutes (version ${m?.minutes_version ?? 0})`}>
        {m?.minutes_text && <pre className="whitespace-pre-wrap text-sm">{m.minutes_text}</pre>}
        {m?.can_edit && ['held', 'minutes_draft'].includes(m.status) && (
          <div className="space-y-2">
            <textarea className={area} placeholder="Minutes" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
            <div className="flex flex-wrap gap-2">
              <Input className="w-56" placeholder="Resolution subject" value={r.subject} onChange={(e) => setR({ ...r, subject: e.target.value })} />
              <Input className="w-72" placeholder="Resolution text" value={r.text} onChange={(e) => setR({ ...r, text: e.target.value })} />
              <select className={sel} value={r.status} onChange={(e) => setR({ ...r, status: e.target.value })}><option>passed</option><option>deferred</option><option>rejected</option></select>
              <Input className="w-56" placeholder="Action owner staff id" value={r.action_owner_staff_id} onChange={(e) => setR({ ...r, action_owner_staff_id: e.target.value })} />
              <Button size="sm" variant="outline" disabled={!r.subject || !r.text} onClick={() => { setRes([...res, { ...r, action_owner_staff_id: r.action_owner_staff_id || undefined }]); setR({ subject: '', text: '', status: 'passed', action_owner_staff_id: '' }); }}>Add resolution</Button>
            </div>
            {res.length > 0 && <ul className="list-disc pl-5 text-sm">{res.map((x, i) => <li key={i}>{x.subject} ({x.status})</li>)}</ul>}
            <div className="flex gap-2">
              <Button size="sm" disabled={!minutes} onClick={() => run.mutate(() => ga.draftMinutes(id, { minutes_text: minutes, resolutions: res }), { onSuccess: done('Draft saved'), onError: fail })}>Save draft</Button>
              {m.status === 'minutes_draft' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.submitMinutes(id), { onSuccess: done('Submitted to the chair'), onError: fail })}>Submit for approval</Button>}
            </div>
          </div>
        )}
        {m?.status === 'minutes_draft' && <div className="flex gap-2"><Button size="sm" onClick={() => run.mutate(() => ga.approveMinutes(id, { approve: true }), { onSuccess: done('Approved'), onError: fail })}>Approve (chair)</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.approveMinutes(id, { approve: false, comment: 'Please revise' }), { onError: fail })}>Return</Button></div>}
        {m?.status === 'minutes_approved' && m?.can_edit && <div className="flex gap-2"><Input className="w-96" placeholder="Corrigendum: corrected minutes text" value={corr} onChange={(e) => setCorr(e.target.value)} /><Button size="sm" variant="outline" disabled={!corr} onClick={() => run.mutate(() => ga.corrigendum(id, { reason: 'Corrigendum', minutes_text: corr }), { onSuccess: done('Corrigendum recorded'), onError: fail })}>Record corrigendum</Button></div>}
        <SimpleTable head={['Approval', 'At', 'Comment']} rows={(m?.approval ?? []).map((a: Any) => [a.action, when(a.at), a.comment ?? a.reason ?? ''])} />
      </Section>
      <Section title="Resolutions">
        <SimpleTable head={['Number', 'Subject', 'Status', 'Owner', 'Due', 'ATR']} rows={(m?.resolutions ?? []).map((x: Any) => [x.number, x.subject, <StatusBadge key="s" status={x.status} />, x.owner_name ?? '—', day(x.due_on), x.atr?.status ?? '—'])} />
      </Section>
    </div>
  );
}

// ---- resolutions ------------------------------------------------------------------------------------------------------------
export function ResolutionsPage() {
  useTitle('Resolutions');
  const [scope, setScope] = useState<string | undefined>();
  const [status, setStatus] = useState('');
  const q = useQ(['resolutions', scope, status], () => ga.resolutions({ scope, status: status || undefined }));
  const run = useRun();
  const [atr, setAtr] = useState<Any>({});
  const [link, setLink] = useState<Any>({});
  return (
    <div className="space-y-4">
      <PageHeader title="Resolutions" description="Register with links, extracts and action-taken reports." actions={<ScopeTabs visibility={(q.data as Any)?.meta?.visibility} value={scope} onChange={setScope} />} />
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['passed', 'deferred', 'rejected', 'implemented'].map((s) => <option key={s}>{s}</option>)}</select>
      <Err q={q} />
      <SimpleTable head={['Number', 'Committee', 'Subject', 'Status', 'Owner / due', 'Link', 'ATR', '']} rows={list(q.data).map((x: Any) => [
        x.number, x.committee_name, x.subject, <StatusBadge key="s" status={x.status} />, `${x.owner_name ?? '—'} · ${day(x.due_on)}${x.overdue ? ' (overdue)' : ''}`,
        x.linked_entity ? `${x.linked_entity.entity_type}` : <span key="l" className="flex gap-1"><select className={sel} value={link[x.id]?.t ?? ''} onChange={(e) => setLink({ ...link, [x.id]: { ...link[x.id], t: e.target.value } })}><option value="">type</option>{['regulation', 'result_run', 'degree_award', 'policy', 'purchase', 'discipline'].map((t) => <option key={t}>{t}</option>)}</select><Input className="w-40" placeholder="entity id" value={link[x.id]?.e ?? ''} onChange={(e) => setLink({ ...link, [x.id]: { ...link[x.id], e: e.target.value } })} /><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.link(x.id, { entity_type: link[x.id]?.t, entity_id: link[x.id]?.e }), { onError: fail })}>Link</Button></span>,
        x.atr ? <span key="a" className="flex items-center gap-1">{x.atr.status}{x.atr.status === 'submitted' && <><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.decideAtr(x.atr.id, { decision: 'accepted' }), { onError: fail })}>Accept</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.decideAtr(x.atr.id, { decision: 'returned' }), { onError: fail })}>Return</Button></>}</span> : x.status === 'passed' && x.action_owner_staff_id ? <span key="a" className="flex gap-1"><Input className="w-48" placeholder="Action taken" value={atr[x.id] ?? ''} onChange={(e) => setAtr({ ...atr, [x.id]: e.target.value })} /><Button size="sm" onClick={() => run.mutate(() => ga.submitAtr(x.id, { report_text: atr[x.id] }), { onSuccess: done('ATR submitted'), onError: fail })}>Submit</Button></span> : '—',
        <Button key="e" size="sm" variant="outline" onClick={() => ga.extract(x.id).then((r: Any) => (r?.data?.url ? window.open(r.data.url, '_blank') : toast.success('Extract issued')), fail)}>Extract</Button>,
      ])} />
    </div>
  );
}

// ---- legal ------------------------------------------------------------------------------------------------------------------
export function LegalPage() {
  useTitle('Legal cases');
  const q = useQ(['cases'], () => ga.cases());
  const cal = useQ(['legal-cal'], () => ga.legalCalendar());
  const run = useRun();
  const [f, setF] = useState<Any>({ court: '', case_type: 'writ', next_hearing: '', counsel: '' });
  const [h, setH] = useState<Any>({});
  return (
    <div className="space-y-4">
      <PageHeader title="Legal cases" description="Case register, hearings with reminders, outcomes and appeals (confidential)." />
      <Section title="Register a case">
        <div className="flex flex-wrap gap-2">
          <Input className="w-56" placeholder="Court" value={f.court} onChange={(e) => setF({ ...f, court: e.target.value })} />
          <Input className="w-32" placeholder="Type" value={f.case_type} onChange={(e) => setF({ ...f, case_type: e.target.value })} />
          <Input className="w-48" placeholder="Counsel" value={f.counsel} onChange={(e) => setF({ ...f, counsel: e.target.value })} />
          <Input type="date" className="w-44" value={f.next_hearing} onChange={(e) => setF({ ...f, next_hearing: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => ga.createCase({ ...f, next_hearing: f.next_hearing || undefined }), { onSuccess: done('Case registered'), onError: fail })}>Register</Button>
        </div>
      </Section>
      <Section title="Hearing calendar (60 days)"><SimpleTable head={['Date', 'Case', 'Court', 'Status']} rows={list(cal.data).map((c: Any) => [c.date, c.case_no, c.court, c.status])} /></Section>
      <Err q={q} />
      <SimpleTable head={['Case no.', 'Court', 'Type', 'Next hearing', 'Status', 'Hearings', 'Record hearing / outcome']} rows={list(q.data).map((c: Any) => [c.case_no, c.court, c.case_type, day(c.next_hearing), <StatusBadge key="s" status={c.status} />, c.hearings.length,
        <span key="h" className="flex flex-wrap gap-1"><Input type="date" className="w-36" value={h[c.id]?.next ?? ''} onChange={(e) => setH({ ...h, [c.id]: { ...h[c.id], next: e.target.value } })} /><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.hearing(c.id, { held_on: new Date().toISOString().slice(0, 10), notes: 'Heard', next_hearing: h[c.id]?.next || undefined }), { onError: fail })}>Hearing</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.outcome(c.id, { outcome: 'Judgement pronounced', status: 'judgement' }), { onError: fail })}>Judgement</Button></span>])} />
    </div>
  );
}

// ---- RTI ----------------------------------------------------------------------------------------------------------------------
export function RtiPage() {
  useTitle('RTI');
  const [status, setStatus] = useState('');
  const q = useQ(['rti', status], () => ga.rti({ status: status || undefined }));
  const run = useRun();
  const [f, setF] = useState<Any>({ name: '', address: '', subject: '', is_bpl: false });
  const [pio, setPio] = useState('');
  const [reply, setReply] = useState<Any>({});
  const [period, setPeriod] = useState(String(new Date().getFullYear()));
  const ret = useQ(['rti-return', period], () => ga.rtiReturn(period), /^\d{4}(-Q[1-4])?$/.test(period));
  const r: Any = data(ret.data);
  return (
    <div className="space-y-4">
      <PageHeader title="RTI requests" description="Receipt → PIO → reply within 30 days, fees / BPL waiver, consultations via e-File, first appeals and returns." />
      <Section title="Record a request">
        <div className="flex flex-wrap gap-2">
          <Input className="w-48" placeholder="Applicant" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <Input className="w-48" placeholder="Address" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />
          <Input className="w-80" placeholder="Information sought" value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.is_bpl} onChange={(e) => setF({ ...f, is_bpl: e.target.checked })} />BPL</label>
          <Button size="sm" onClick={() => run.mutate(() => ga.createRti({ applicant: { name: f.name, address: f.address, is_bpl: f.is_bpl }, subject: f.subject }), { onSuccess: done('Recorded'), onError: fail })}>Record</Button>
        </div>
      </Section>
      <Section title="Return" action={<Input className="w-28" value={period} onChange={(e) => setPeriod(e.target.value)} />}>
        {r && <div className="grid gap-2 md:grid-cols-6"><Stat label="Received" value={r.received} /><Stat label="Disposed" value={r.disposed} /><Stat label="Within time" value={`${r.within_time_pct}%`} /><Stat label="Appeals" value={r.appeals} /><Stat label="Pending" value={r.pending} /><Stat label="Fees" value={rupees(r.fees_collected_paise)} /></div>}
      </Section>
      <div className="flex gap-2"><select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['received', 'assigned', 'responded', 'appealed', 'closed'].map((s) => <option key={s}>{s}</option>)}</select><Input className="w-64" placeholder="PIO staff id (assign)" value={pio} onChange={(e) => setPio(e.target.value)} /></div>
      <Err q={q} />
      <SimpleTable head={['No.', 'Applicant', 'Subject', 'Due', 'Status', 'Actions']} rows={list(q.data).map((x: Any) => [x.request_no, x.applicant?.name, x.subject, <span key="d" className={x.late ? 'text-destructive' : ''}>{day(x.due_on)}{x.days_left !== null && x.days_left !== undefined ? ` (${x.days_left}d)` : ''}</span>, <StatusBadge key="s" status={x.status} />,
        <span key="a" className="flex flex-wrap gap-1">
          {['received', 'assigned'].includes(x.status) && <Button size="sm" variant="outline" disabled={!pio} onClick={() => run.mutate(() => ga.assignRti(x.id, { pio_staff_id: pio }), { onError: fail })}>Assign</Button>}
          {['received', 'assigned'].includes(x.status) && <><Input className="w-48" placeholder="Reply" value={reply[x.id] ?? ''} onChange={(e) => setReply({ ...reply, [x.id]: e.target.value })} /><Button size="sm" onClick={() => run.mutate(() => ga.respondRti(x.id, { response_text: reply[x.id] }), { onError: fail })}>Reply</Button></>}
          {x.status === 'responded' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.closeRti(x.id), { onError: fail })}>Close</Button>}
          {x.status === 'appealed' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.decideRti(x.id, { decision: 'upheld', remarks: 'Reply adequate' }), { onError: fail })}>Decide appeal</Button>}
        </span>])} />
    </div>
  );
}

// ---- audit paras --------------------------------------------------------------------------------------------------------------
export function AuditParasPage() {
  useTitle('Audit paras');
  const q = useQ(['paras'], () => ga.paras());
  const dash = useQ(['para-dash'], () => ga.paraDashboard());
  const regs = useQ(['registers'], () => ga.registers());
  const run = useRun();
  const [f, setF] = useState<Any>({ audit_register_id: '', para_no: '', description: '', amount: '', owner_staff_id: '' });
  const [reply, setReply] = useState<Any>({});
  const d: Any = data(dash.data);
  const cols = ['open', 'replied', 'settled', 'dropped'];
  return (
    <div className="space-y-4">
      <PageHeader title="Audit paras" description="Statutory / AG audit paras under the Phase 32 registers: replies, settlement and ageing." />
      {d && <div className="grid gap-3 md:grid-cols-5">{Object.entries(d.ageing ?? {}).map(([k, v]: Any) => <Stat key={k} label={`Ageing ${k} days`} value={v} />)}<Stat label="Open amount" value={rupees(d.amount_open_paise)} /></div>}
      <Section title="Record a para">
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={f.audit_register_id} onChange={(e) => setF({ ...f, audit_register_id: e.target.value })}><option value="">Register…</option>{list(regs.data).filter((r: Any) => ['financial_statutory', 'ag'].includes(r.audit_type)).map((r: Any) => <option key={r.id} value={r.id}>{r.audit_type} {r.period_label}</option>)}</select>
          <Input className="w-24" placeholder="Para no." value={f.para_no} onChange={(e) => setF({ ...f, para_no: e.target.value })} />
          <Input className="w-80" placeholder="Description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
          <Input className="w-32" placeholder="Amount ₹" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
          <Input className="w-56" placeholder="Owner staff id" value={f.owner_staff_id} onChange={(e) => setF({ ...f, owner_staff_id: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => ga.createPara({ audit_register_id: f.audit_register_id, para_no: f.para_no, description: f.description, amount_paise: f.amount ? Math.round(Number(f.amount) * 100) : undefined, owner_staff_id: f.owner_staff_id || undefined }), { onSuccess: done('Para recorded'), onError: fail })}>Record</Button>
        </div>
      </Section>
      <Err q={q} />
      <div className="grid gap-3 md:grid-cols-4">{cols.map((c) => (
        <Section key={c} title={`${c} (${list(q.data).filter((p: Any) => p.status === c).length})`}>
          {list(q.data).filter((p: Any) => p.status === c).map((p: Any) => (
            <Card key={p.id}><CardContent className="space-y-1 p-3 text-xs">
              <div className="font-medium">{p.para_no} · {p.audit_type} {p.period_label}</div>
              <p>{p.description}</p><p>{rupees(p.amount_paise)} · {p.owner_name ?? '—'} · {p.age_days}d</p>
              {['open', 'replied'].includes(p.status) && <div className="flex flex-wrap gap-1"><Input className="h-7 w-32" placeholder="Reply" value={reply[p.id] ?? ''} onChange={(e) => setReply({ ...reply, [p.id]: e.target.value })} /><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.replyPara(p.id, { reply_text: reply[p.id] }), { onError: fail })}>Reply</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.paraStatus(p.id, { status: 'settled' }), { onError: fail })}>Settle</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.paraStatus(p.id, { status: 'dropped' }), { onError: fail })}>Drop</Button></div>}
            </CardContent></Card>
          ))}
        </Section>
      ))}</div>
    </div>
  );
}

// ---- e-File -----------------------------------------------------------------------------------------------------------------
export function EfilesPage() {
  useTitle('e-File');
  const [box, setBox] = useState<'inbox' | 'outbox' | 'mine' | 'all'>('inbox');
  const [search, setSearch] = useState('');
  const q = useQ(['efiles', box, search], () => ga.efiles(box, { q: search || undefined }));
  const pend = useQ(['pendency'], () => ga.pendency());
  const run = useRun();
  const [f, setF] = useState<Any>({ subject: '', category: 'general', priority: 'normal', initial_noting: '' });
  return (
    <div className="space-y-4">
      <PageHeader title="e-File" description="File movement with append-only notings, holders and pendency." />
      <Section title="Open a file">
        <div className="flex flex-wrap gap-2">
          <Input className="w-72" placeholder="Subject" value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} />
          <Input className="w-32" placeholder="Category" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} />
          <select className={sel} value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>{['low', 'normal', 'high', 'urgent'].map((p) => <option key={p}>{p}</option>)}</select>
          <Input className="w-96" placeholder="Initial noting" value={f.initial_noting} onChange={(e) => setF({ ...f, initial_noting: e.target.value })} />
          <Button size="sm" disabled={!f.subject || !f.initial_noting} onClick={() => run.mutate(() => ga.createEfile(f), { onSuccess: done('File opened'), onError: fail })}>Open</Button>
        </div>
      </Section>
      <div className="flex flex-wrap gap-2">{(['inbox', 'outbox', 'mine', 'all'] as const).map((b) => <Button key={b} size="sm" variant={b === box ? 'default' : 'outline'} onClick={() => setBox(b)}>{b}</Button>)}<Input className="w-56" placeholder="Search number / subject" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
      <Err q={q} />
      <SimpleTable head={['File no.', 'Subject', 'Priority', 'Holder', 'Pendency', 'Status', '']} rows={list(q.data).map((x: Any) => [x.file_no, x.subject, x.priority, x.holder_name ?? '—', <span key="p" className={x.over_sla ? 'text-destructive' : ''}>{x.pendency_days}d</span>, <StatusBadge key="s" status={x.status} />, <Link key="o" className="text-primary underline" to={`/admin/efiles/${x.id}`}>Open</Link>])} />
      {!pend.isError && list(pend.data).length > 0 && <Section title="Pendency by holder"><SimpleTable head={['Holder', 'Files', 'Over SLA', 'Max days']} rows={list(pend.data).map((p: Any) => [p.holder_name ?? '—', p.files, p.over_sla, p.max_days])} /></Section>}
    </div>
  );
}

export function EfilePage() {
  const { id = '' } = useParams();
  const q = useQ(['efile', id], () => ga.efile(id));
  const f: Any = data(q.data);
  useTitle(f?.file_no ?? 'File');
  const run = useRun();
  const [mv, setMv] = useState<Any>({ action: 'forward', to_user_id: '', to_role: '', noting: '' });
  const [summary, setSummary] = useState('');
  return (
    <div className="space-y-4">
      <PageHeader title={f ? `${f.file_no} — ${f.subject}` : 'File'} description={f ? `${f.category ?? ''} · ${f.priority} · with ${f.holder_name ?? '—'} for ${f.pendency_days} day(s)` : ''} actions={f && <div className="flex gap-2"><StatusBadge status={f.status} /><Button size="sm" variant="outline" onClick={() => ga.notingsPdf(id).then(openBlob, fail)}>Notings PDF</Button></div>} />
      <Err q={q} />
      <Section title="Notings sheet (append-only)">
        <ol className="space-y-2">{(f?.movements ?? []).map((m: Any, i: number) => <li key={m.id} className="rounded border p-2 text-sm"><div className="text-xs text-muted-foreground">{i + 1}. {when(m.moved_at)} · {m.action} · {m.from_name ?? '—'} → {m.to_name ?? '—'}</div><p className="whitespace-pre-wrap">{m.noting}</p></li>)}</ol>
      </Section>
      {f && f.status !== 'closed' && (
        <Section title="Move">
          <div className="flex flex-wrap gap-2">
            <select className={sel} value={mv.action} onChange={(e) => setMv({ ...mv, action: e.target.value })}>{['forward', 'return', 'approve', 'reject'].map((a) => <option key={a}>{a}</option>)}</select>
            {mv.action === 'forward' && <><Input className="w-56" placeholder="To user id" value={mv.to_user_id} onChange={(e) => setMv({ ...mv, to_user_id: e.target.value })} /><Input className="w-40" placeholder="or role (e.g. accountant)" value={mv.to_role} onChange={(e) => setMv({ ...mv, to_role: e.target.value })} /></>}
            <Input className="w-96" placeholder="Noting" value={mv.noting} onChange={(e) => setMv({ ...mv, noting: e.target.value })} />
            <Button size="sm" disabled={!mv.noting} onClick={() => run.mutate(() => ga.moveEfile(id, { action: mv.action, noting: mv.noting, to_user_id: mv.to_user_id || undefined, to_role: mv.to_role || undefined }), { onSuccess: done('Moved'), onError: fail })}>Move</Button>
          </div>
          <div className="flex gap-2"><Input className="w-96" placeholder="Closing summary" value={summary} onChange={(e) => setSummary(e.target.value)} /><Button size="sm" variant="outline" disabled={!summary} onClick={() => run.mutate(() => ga.closeEfile(id, summary), { onSuccess: done('Closed'), onError: fail })}>Close file</Button></div>
        </Section>
      )}
      {f?.status === 'closed' && <Section title="Closed"><p className="text-sm">{f.summary}</p><Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.reopenEfile(id, 'Reopened by admin'), { onError: fail })}>Reopen (admin)</Button></Section>}
    </div>
  );
}

// ---- policies ---------------------------------------------------------------------------------------------------------------
export function PoliciesPage() {
  useTitle('Policies');
  const [cat, setCat] = useState('');
  const q = useQ(['policies', cat], () => ga.policies({ category: cat || undefined }));
  const run = useRun();
  const [f, setF] = useState<Any>({ title: '', category: 'academic', version: '1.0', effective_from: '', file_url: '', requires_ack: false, website: false });
  const [resId, setResId] = useState('');
  return (
    <div className="space-y-4">
      <PageHeader title="Policies" description="Repository with versions, approval (council resolution), publication, acknowledgements and supersession." />
      <Section title="Draft a policy">
        <div className="flex flex-wrap gap-2">
          <Input className="w-64" placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          <select className={sel} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{POLICY_CATS.map((c) => <option key={c}>{c}</option>)}</select>
          <Input className="w-20" value={f.version} onChange={(e) => setF({ ...f, version: e.target.value })} />
          <Input type="date" className="w-44" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} />
          <Input className="w-56" placeholder="File URL" value={f.file_url} onChange={(e) => setF({ ...f, file_url: e.target.value })} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.requires_ack} onChange={(e) => setF({ ...f, requires_ack: e.target.checked })} />ack</label>
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.website} onChange={(e) => setF({ ...f, website: e.target.checked })} />website</label>
          <Button size="sm" disabled={!f.title} onClick={() => run.mutate(() => ga.createPolicy({ ...f, effective_from: f.effective_from || undefined, file_url: f.file_url || undefined }), { onSuccess: done('Draft created'), onError: fail })}>Create</Button>
        </div>
      </Section>
      <div className="flex gap-2"><select className={sel} value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All categories</option>{POLICY_CATS.map((c) => <option key={c}>{c}</option>)}</select><Input className="w-72" placeholder="Council resolution id (for approval)" value={resId} onChange={(e) => setResId(e.target.value)} /></div>
      <Err q={q} />
      <SimpleTable head={['Policy', 'Category', 'Version', 'Stage', 'Effective', 'Resolution', 'Ack', '']} rows={list(q.data).map((p: Any) => [p.title, p.category, p.version, <StatusBadge key="s" status={p.stage} />, day(p.effective_from), p.resolution_number ?? '—', p.requires_ack ? `${p.ack_count}${p.ack_pct !== null && p.ack_pct !== undefined ? ` (${p.ack_pct}%)` : ''}` : '—',
        <span key="a" className="flex flex-wrap gap-1">
          {p.stage === 'draft' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.submitPolicy(p.id), { onError: fail })}>Submit</Button>}
          {p.stage === 'submitted' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.approvePolicy(p.id, { approve: true, resolution_id: resId || undefined }), { onError: fail })}>Approve</Button>}
          {p.stage === 'approved' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.publishPolicy(p.id), { onError: fail })}>Publish</Button>}
          {p.status === 'approved' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ga.supersedePolicy(p.id), { onError: fail })}>Supersede</Button>}
          {p.published && p.requires_ack && !p.acknowledged && <Button size="sm" onClick={() => run.mutate(() => ga.acknowledge(p.id), { onError: fail })}>Acknowledge</Button>}
        </span>])} />
    </div>
  );
}

// ---- stats --------------------------------------------------------------------------------------------------------------------
export function GovernanceStatsPage() {
  useTitle('Governance stats');
  const [year, setYear] = useState(new Date().getFullYear());
  const q = useQ(['stats', year], () => ga.stats(year));
  const s: Any = data(q.data);
  const pct = (v?: number | null) => (v === null || v === undefined ? '—' : `${v}%`);
  return (
    <div className="space-y-4">
      <PageHeader title="Governance statistics" description="Meetings, quorum, resolutions implemented, ATR pendency, legal, RTI, audit paras, e-file pendency and policy acknowledgements." actions={<Input type="number" className="w-24" value={year} onChange={(e) => setYear(Number(e.target.value))} />} />
      <Err q={q} />
      {s && <div className="grid gap-3 md:grid-cols-5">
        <Stat label="Meetings" value={s.meetings} /><Stat label="Quorum compliance" value={pct(s.quorum_compliance_pct)} /><Stat label="Resolutions" value={s.resolutions} /><Stat label="Implemented" value={pct(s.resolutions_implemented_pct)} /><Stat label="ATR pending" value={s.atr_pending} />
        <Stat label="RTI received" value={s.rti_received} /><Stat label="RTI within time" value={pct(s.rti_within_time_pct)} /><Stat label="Paras settled" value={pct(s.audit_paras_settled_pct)} /><Stat label="Files open / over SLA" value={`${s.efile_open} / ${s.efile_over_sla}`} /><Stat label="Policy ack" value={pct(s.policy_ack_pct)} />
      </div>}
      {s && <Section title="Meetings per committee"><SimpleTable head={['Committee', 'Type', 'Meetings']} rows={s.meetings_per_committee.map((m: Any) => [m.name, m.committee_type, m.meetings])} /></Section>}
      {s && <Section title="Legal cases by status"><div className="flex flex-wrap gap-2 text-sm">{Object.entries(s.legal_by_status ?? {}).map(([k, v]: Any) => <span key={k} className="rounded bg-muted px-2 py-1">{k}: {v}</span>)}</div></Section>}
    </div>
  );
}

// ---- staff portal -------------------------------------------------------------------------------------------------------------
export function StaffGovernancePage() {
  useTitle('Governance');
  const q = useQ(['me'], () => ga.me());
  const g: Any = data(q.data);
  const run = useRun();
  const [atr, setAtr] = useState<Any>({});
  return (
    <div className="space-y-4">
      <PageHeader title="Governance" description="My committees and meetings, resolutions I own, e-files with me and policies to acknowledge." />
      <Err q={q} />
      {g && <div className="grid gap-3 md:grid-cols-4"><Stat label="Committees" value={g.committees.length} /><Stat label="Meetings" value={g.meetings.length} /><Stat label="Files with me" value={g.efile_inbox} /><Stat label="Audit paras" value={g.audit_paras} /></div>}
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="My committees"><SimpleTable head={['Committee', 'Role', 'Next meeting']} rows={(g?.committees ?? []).map((c: Any) => [c.name, c.my_role ?? 'member', when(c.next_meeting)])} /></Section>
        <Section title="Meetings (agenda / approved minutes)"><SimpleTable head={['Committee', 'No.', 'When', 'Status', '']} rows={(g?.meetings ?? []).map((m: Any) => [m.committee_name, m.meeting_no, when(m.held_on), <StatusBadge key="s" status={m.status} />, m.status === 'minutes_approved' ? <Button key="p" size="sm" variant="outline" onClick={() => ga.minutesPdf(m.id).then(openBlob, fail)}>Minutes</Button> : m.status === 'scheduled' ? <Button key="c" size="sm" variant="outline" onClick={() => run.mutate(() => ga.attendance(m.id, { self_check_in: true }), { onSuccess: done('Marked present'), onError: fail })}>Check in</Button> : ''])} /></Section>
        <Section title="Resolutions I own (ATR)"><SimpleTable head={['Number', 'Subject', 'Due', 'ATR']} rows={(g?.resolutions ?? []).map((r: Any) => [r.number, r.subject, day(r.due_on), r.atr ? r.atr.status : r.status === 'passed' ? <span key="a" className="flex gap-1"><Input className="h-8 w-40" value={atr[r.id] ?? ''} onChange={(e) => setAtr({ ...atr, [r.id]: e.target.value })} /><Button size="sm" onClick={() => run.mutate(() => ga.submitAtr(r.id, { report_text: atr[r.id] }), { onSuccess: done('ATR submitted'), onError: fail })}>Submit</Button></span> : r.status])} /></Section>
        <Section title="Policies to acknowledge"><SimpleTable head={['Policy', 'Version', '']} rows={(g?.pending_acks ?? []).map((p: Any) => [p.file_url ? <a key="l" className="text-primary underline" href={p.file_url}>{p.title}</a> : p.title, p.version, <Button key="a" size="sm" onClick={() => run.mutate(() => ga.acknowledge(p.id), { onSuccess: done('Acknowledged'), onError: fail })}>Acknowledge</Button>])} /></Section>
      </div>
      <p className="text-sm"><Link className="text-primary underline" to="/admin/efiles">Open my e-file inbox</Link></p>
    </div>
  );
}
