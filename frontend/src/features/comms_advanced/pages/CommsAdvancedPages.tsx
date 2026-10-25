import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { commsApi as cm } from '../api';

// Phase 24 web screens (Prompts/24 §24.9). Audience scoping, compliance and rate limits live in the API.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['comms', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['comms'] }) });
}
const list = (r: Any) => (Array.isArray(r?.data) ? r.data : r?.data?.items ?? []);
const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');
const CHANNELS = ['sms', 'whatsapp', 'email', 'push', 'in_app'];
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const area = 'min-h-24 w-full rounded-md border bg-background p-2 text-sm';
const openBlob = (b: Blob, name: string) => { const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(u), 30000); };

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function ChannelPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return <div className="flex flex-wrap gap-2">{CHANNELS.map((c) => <label key={c} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={value.includes(c)} onChange={(e) => onChange(e.target.checked ? [...value, c] : value.filter((x) => x !== c))} />{c}</label>)}</div>;
}
function RulesEditor({ value, onChange }: { value: Any; onChange: (v: Any) => void }) {
  const types = value.person_types ?? ['student'];
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-3">{['student', 'guardian', 'staff'].map((t) => <label key={t} className="flex items-center gap-1"><input type="checkbox" checked={types.includes(t)} onChange={(e) => onChange({ ...value, person_types: e.target.checked ? [...types, t] : types.filter((x: string) => x !== t) })} />{t}s</label>)}</div>
      <div className="grid gap-2 md:grid-cols-2">
        <label className="space-y-1"><span className="text-xs text-muted-foreground">Dues at least (₹)</span><Input type="number" value={value.dues ? value.dues.min_paise / 100 : ''} onChange={(e) => onChange({ ...value, dues: e.target.value ? { min_paise: Math.round(Number(e.target.value) * 100), overdue_only: value.dues?.overdue_only ?? false } : null })} /></label>
        <label className="space-y-1"><span className="text-xs text-muted-foreground">Attendance below (%)</span><Input type="number" value={value.attendance?.below_pct ?? ''} onChange={(e) => onChange({ ...value, attendance: e.target.value ? { below_pct: Number(e.target.value) } : null })} /></label>
      </div>
      <label className="flex items-center gap-1"><input type="checkbox" checked={!!value.notify_guardians} onChange={(e) => onChange({ ...value, notify_guardians: e.target.checked })} />Also notify guardians</label>
    </div>
  );
}
function PreviewBox({ rules }: { rules: Any }) {
  const [p, setP] = useState<Any | null>(null);
  const run = useRun();
  return <div className="space-y-2"><Button size="sm" variant="outline" onClick={() => run.mutate(() => cm.preview(rules), { onSuccess: (r: Any) => setP(r?.data), onError: fail })}>Preview audience</Button>{p && <div className="text-sm"><p className="font-medium">{p.count} recipient(s)</p><p className="text-muted-foreground">{Object.entries(p.by_channel_reachable ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p></div>}</div>;
}

// ---- segments ----------------------------------------------------------------------------------------------------------
export function SegmentsPage() {
  useTitle('Audience segments');
  const q = useQ(['segments'], () => cm.segments());
  const [form, setForm] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Audience segments" description="Saved audience rules reused by campaigns." actions={<Button onClick={() => setForm({ name: '', rules: { person_types: ['student'] }, shared: false })}>New segment</Button>} />
      <Card><CardContent className="p-2"><SimpleTable head={['Name', 'Shared', 'Updated', '']} rows={list(q.data).map((s: Any) => [s.name, s.shared ? 'yes' : 'no', when(s.updated_at), <div key="a" className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setForm({ ...s })}>Edit</Button><Button size="sm" variant="outline" onClick={() => run.mutate(() => cm.deleteSegment(s.id), { onError: fail })}>Delete</Button></div>])} /></CardContent></Card>
      {form && <Modal open onOpenChange={(o) => !o && setForm(null)} title={form.id ? 'Edit segment' : 'New segment'}>
        <div className="space-y-3"><Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <RulesEditor value={form.rules} onChange={(rules) => setForm({ ...form, rules })} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={form.shared} onChange={(e) => setForm({ ...form, shared: e.target.checked })} />Share with other senders</label>
          <PreviewBox rules={form.rules} />
          <Button onClick={() => run.mutate(() => cm.saveSegment({ name: form.name, rules: form.rules, shared: form.shared }, form.id), { onSuccess: () => { toast.success('Saved'); setForm(null); }, onError: fail })}>Save</Button></div>
      </Modal>}
    </div>
  );
}

// ---- campaigns ---------------------------------------------------------------------------------------------------------
const ACTIONS: Record<string, string[]> = {
  draft: ['submit', 'send_now', 'schedule', 'cancel'],
  pending_approval: ['approve', 'reject'],
  scheduled: ['cancel', 'send_now'],
  sending: ['pause'],
  paused: ['resume', 'cancel'],
  sent: ['retry_failed'],
  failed: ['retry_failed'],
};
export function CampaignsPage() {
  useTitle('Campaigns');
  const [status, setStatus] = useState('');
  const q = useQ(['campaigns', status], () => cm.campaigns({ status: status || undefined }));
  const segs = useQ(['segments'], () => cm.segments());
  const [form, setForm] = useState<Any | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const run = useRun();
  const act = (id: string, action: string) => {
    const b: Any = { action };
    if (action === 'schedule') { const at = window.prompt('Send at (YYYY-MM-DDTHH:MM)'); if (!at) return; b.scheduled_at = new Date(at).toISOString(); }
    if (action === 'reject' || action === 'cancel') b.reason = window.prompt('Reason') ?? '';
    run.mutate(() => cm.action(id, b), { onSuccess: () => toast.success(action.replace('_', ' ')), onError: fail });
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Campaigns" description="Bulk messages across SMS, WhatsApp, email, push and in-app — DLT and quiet hours are checked before sending." actions={<Button onClick={() => setForm({ name: '', channels: ['in_app'], audience_rules: { person_types: ['student'] }, segment_id: '', body: { in_app: '', sms: '', email_subject: '', email_html: '', push_title: '', push_body: '' }, category: 'academic' })}>New campaign</Button>} />
      <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{Object.keys(ACTIONS).concat(['cancelled']).map((s) => <option key={s}>{s}</option>)}</select>
      <Card><CardContent className="p-2"><SimpleTable head={['Name', 'Channels', 'Status', 'Recipients', 'Sent / failed', 'Scheduled', '']} rows={list(q.data).map((c: Any) => [<button key="n" className="text-left underline" onClick={() => setOpen(c.id)}>{c.name}</button>, c.channels.join(', '), <StatusBadge key="s" status={c.status} />, c.total_recipients ?? '—', `${c.sent_count} / ${c.failed_count}`, when(c.scheduled_at), <div key="a" className="flex flex-wrap gap-1">{(ACTIONS[c.status] ?? []).map((a) => <Button key={a} size="sm" variant="outline" onClick={() => act(c.id, a)}>{a.replace('_', ' ')}</Button>)}</div>])} /></CardContent></Card>
      {form && <Modal open onOpenChange={(o) => !o && setForm(null)} title="New campaign">
        <div className="space-y-3"><Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <ChannelPicker value={form.channels} onChange={(channels) => setForm({ ...form, channels })} />
          <select className={`${sel} w-full`} value={form.segment_id} onChange={(e) => setForm({ ...form, segment_id: e.target.value })}><option value="">Custom audience…</option>{list(segs.data).map((s: Any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          {!form.segment_id && <><RulesEditor value={form.audience_rules} onChange={(audience_rules) => setForm({ ...form, audience_rules })} /><PreviewBox rules={form.audience_rules} /></>}
          {form.channels.includes('in_app') && <textarea className={area} placeholder="In-app message" value={form.body.in_app} onChange={(e) => setForm({ ...form, body: { ...form.body, in_app: e.target.value } })} />}
          {form.channels.includes('sms') && <textarea className={area} placeholder="SMS text (must match a DLT template)" value={form.body.sms} onChange={(e) => setForm({ ...form, body: { ...form.body, sms: e.target.value } })} />}
          {form.channels.includes('email') && <><Input placeholder="Email subject" value={form.body.email_subject} onChange={(e) => setForm({ ...form, body: { ...form.body, email_subject: e.target.value } })} /><textarea className={area} placeholder="Email body (HTML)" value={form.body.email_html} onChange={(e) => setForm({ ...form, body: { ...form.body, email_html: e.target.value } })} /></>}
          {form.channels.includes('push') && <><Input placeholder="Push title" value={form.body.push_title} onChange={(e) => setForm({ ...form, body: { ...form.body, push_title: e.target.value } })} /><Input placeholder="Push body" value={form.body.push_body} onChange={(e) => setForm({ ...form, body: { ...form.body, push_body: e.target.value } })} /></>}
          <select className={sel} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{['academic', 'transactional', 'marketing'].map((c) => <option key={c}>{c}</option>)}</select>
          <Button onClick={() => { const body = Object.fromEntries(Object.entries(form.body).filter(([, v]) => v)); run.mutate(() => cm.createCampaign({ name: form.name, channels: form.channels, category: form.category, body_override: body, ...(form.segment_id ? { segment_id: form.segment_id } : { audience_rules: form.audience_rules }) }), { onSuccess: () => { toast.success('Draft created'); setForm(null); }, onError: fail }); }}>Create draft</Button></div>
      </Modal>}
      {open && <CampaignReport id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
function CampaignReport({ id, onClose }: { id: string; onClose: () => void }) {
  const r = useQ(['report', id], () => cm.report(id));
  const chk = useQ(['compliance', id], () => cm.compliance(id));
  const rec = useQ(['recipients', id], () => cm.recipients(id, { status: 'failed' }));
  const d = (r.data as Any)?.data;
  const c = (chk.data as Any)?.data;
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Campaign report">
      <div className="space-y-3 text-sm">
        {c && <p className={c.ok ? 'text-emerald-600' : 'text-destructive'}>{c.ok ? 'Compliance OK' : c.errors.join('; ')}</p>}
        {d && <SimpleTable head={['Channel', 'Sent', 'Delivered', 'Read', 'Failed', 'Cost']} rows={(d.by_channel ?? []).map((x: Any) => [x.channel, x.sent, x.delivered, x.read ?? '—', x.failed, x.cost_paise != null ? `₹${(x.cost_paise / 100).toFixed(2)}` : '—'])} />}
        <h3 className="font-medium">Failed recipients</h3>
        <SimpleTable head={['Recipient', 'Channel', 'Error']} rows={list(rec.data).slice(0, 50).map((x: Any) => [x.recipient, x.channel, x.error ?? '—'])} />
      </div>
    </Modal>
  );
}

// ---- emergency ---------------------------------------------------------------------------------------------------------
export function EmergencyPage() {
  useTitle('Emergency broadcast');
  const log = useQ(['emergency'], () => cm.emergencyLog());
  const [f, setF] = useState<Any>({ alert_type: 'security', message: '', audience: 'all' });
  const [confirm, setConfirm] = useState(false);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Emergency broadcast" description="Bypasses quiet hours and opt-outs; every channel at once. Every broadcast is audited." />
      <Section title="Raise an alert">
        <div className="grid gap-2 md:grid-cols-2"><select className={sel} value={f.alert_type} onChange={(e) => setF({ ...f, alert_type: e.target.value })}>{['sos', 'fire', 'medical', 'security', 'weather', 'other'].map((t) => <option key={t}>{t}</option>)}</select><select className={sel} value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })}>{['all', 'college', 'hostel'].map((t) => <option key={t}>{t}</option>)}</select></div>
        <textarea className={area} placeholder="Message (what, where, what to do)" value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} />
        {!confirm ? <Button variant="destructive" disabled={f.message.length < 5} onClick={() => setConfirm(true)}>Broadcast…</Button> : <div className="flex gap-2"><Button variant="destructive" onClick={() => run.mutate(() => cm.broadcast(f), { onSuccess: () => { toast.success('Broadcast sent'); setConfirm(false); setF({ ...f, message: '' }); }, onError: fail })}>Confirm broadcast</Button><Button variant="outline" onClick={() => setConfirm(false)}>Cancel</Button></div>}
      </Section>
      <Section title="Log"><SimpleTable head={['When', 'Type', 'Message', 'Recipients', '']} rows={list(log.data).map((e: Any) => [when(e.at), e.alert_type ?? '—', e.message, e.recipients ?? '—', e.all_clear_at ? `all clear ${when(e.all_clear_at)}` : <Button key="c" size="sm" variant="outline" onClick={() => { const m = window.prompt('All-clear message', 'All clear. Normal activity may resume.'); if (m) run.mutate(() => cm.allClear(e.campaign_id, m), { onError: fail }); }}>All clear</Button>])} /></Section>
    </div>
  );
}

// ---- bot ---------------------------------------------------------------------------------------------------------------
export function BotPage() {
  useTitle('WhatsApp bot');
  const fl = useQ(['flows'], () => cm.flows());
  const ss = useQ(['sessions'], () => cm.sessions());
  const [text, setText] = useState<string | null>(null);
  const run = useRun();
  const conf = (fl.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="WhatsApp bot" description="Menu flows answered from live data; handoffs go to the help desk." />
      <Section title="Flows" action={<Button size="sm" variant="outline" onClick={() => setText(JSON.stringify(conf, null, 2))}>Edit JSON</Button>}>
        <SimpleTable head={['#', 'Key', 'Label']} rows={(conf?.flows ?? []).map((x: Any, i: number) => [i + 1, x.key, x.label])} />
      </Section>
      <Section title="Sessions"><SimpleTable head={['Phone', 'User', 'State', 'Last message', '']} rows={list(ss.data).map((s: Any) => [s.phone ?? '—', s.user_name ?? '—', s.handoff ? 'handoff' : s.state?.step ?? '—', when(s.last_message_at), s.handoff ? <Button key="h" size="sm" variant="outline" onClick={() => run.mutate(() => cm.closeHandoff(s.id), { onError: fail })}>Close handoff</Button> : null])} /></Section>
      {text != null && <Modal open onOpenChange={(o) => !o && setText(null)} title="Bot flows">
        <textarea className={`${area} min-h-80 font-mono`} value={text} onChange={(e) => setText(e.target.value)} />
        <Button onClick={() => { let b: Any; try { b = JSON.parse(text); } catch { toast.error('Invalid JSON'); return; } run.mutate(() => cm.saveFlows(b), { onSuccess: () => { toast.success('Saved'); setText(null); }, onError: fail }); }}>Save</Button>
      </Modal>}
    </div>
  );
}

// ---- assistant ---------------------------------------------------------------------------------------------------------
export function AssistantPage() {
  useTitle('Assistant');
  const me = useQ(['assistant-me'], () => cm.assistantMe());
  const [conv, setConv] = useState<string | undefined>();
  const [msgs, setMsgs] = useState<{ role: string; text: string; cites?: string[] }[]>([]);
  const [input, setInput] = useState('');
  const run = useRun();
  const m = (me.data as Any)?.data;
  if (m && !m.enabled) return <div className="space-y-4"><PageHeader title="Assistant" description="The assistant is not enabled for this institution." /></div>;
  const send = () => {
    const text = input.trim();
    if (!text) return;
    setMsgs((x) => [...x, { role: 'you', text }]);
    setInput('');
    run.mutate(() => cm.chat({ conversation_id: conv, message: text }), { onSuccess: (r: Any) => { setConv(r?.data?.conversation_id); setMsgs((x) => [...x, { role: 'assistant', text: r?.data?.reply ?? '', cites: r?.data?.citations }]); }, onError: fail });
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Assistant" description="Ask about attendance, dues, timetable, results — answers come only from records you are allowed to see." />
      {m && !m.opted_in && <Section title="Before you start"><p className="text-sm">The assistant reads your own records to answer. Conversations are kept for 90 days.</p><Button onClick={() => run.mutate(() => cm.optIn(true), { onError: fail })}>I agree</Button></Section>}
      {m?.opted_in && <Card><CardContent className="space-y-3 p-4">
        <div className="max-h-[60vh] space-y-2 overflow-y-auto">{msgs.map((x, i) => <div key={i} className={`rounded-md p-2 text-sm ${x.role === 'you' ? 'ml-auto max-w-[80%] bg-primary text-primary-foreground' : 'max-w-[80%] bg-muted'}`}><p className="whitespace-pre-wrap">{x.text}</p>{x.cites && x.cites.length > 0 && <p className="mt-1 text-xs opacity-70">Source: {x.cites.join(', ')}</p>}</div>)}</div>
        <div className="flex gap-2"><Input value={input} placeholder="e.g. What is my attendance in DBMS?" onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} /><Button disabled={run.isPending} onClick={send}>Send</Button></div>
      </CardContent></Card>}
    </div>
  );
}

// ---- simulator (dev / staging) --------------------------------------------------------------------------------------------
export function SimulatorPage() {
  useTitle('Message simulator');
  const q = useQ(['inbox'], () => cm.inbox());
  const [f, setF] = useState({ from: '+919000000101', text: 'hi' });
  const [reply, setReply] = useState<string>('');
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Message simulator" description="Console-provider inbox and an inbound WhatsApp tester (non-production only)." actions={<Button variant="outline" onClick={() => run.mutate(() => cm.clearInbox(), { onError: fail })}>Clear inbox</Button>} />
      <Section title="Inbound WhatsApp"><div className="flex gap-2"><Input className="w-48" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /><Input value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /><Button onClick={() => run.mutate(() => cm.inboundWhatsapp(f), { onSuccess: (r: Any) => setReply(String(r?.data?.reply ?? JSON.stringify(r?.data))), onError: fail })}>Send</Button></div>{reply && <pre className="whitespace-pre-wrap rounded bg-muted p-2 text-sm">{reply}</pre>}</Section>
      <Section title="Outbox"><SimpleTable head={['When', 'Channel', 'To', 'Message']} rows={list(q.data).slice(0, 100).map((m: Any) => [when(m.at ?? m.created_at), m.channel, m.to ?? m.recipient, m.body ?? m.body_preview])} /></Section>
    </div>
  );
}

// ---- analytics ---------------------------------------------------------------------------------------------------------
export function DeliveryAnalyticsPage() {
  useTitle('Delivery analytics');
  const q = useQ(['delivery'], () => cm.delivery());
  const pv = useQ(['providers'], () => cm.providers());
  const d = (q.data as Any)?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Delivery analytics" description="Sent, delivered, failed and cost by channel and provider." actions={<Button variant="outline" onClick={() => cm.exportDelivery().then((b) => openBlob(b, 'delivery.csv')).catch(fail)}>Export CSV</Button>} />
      {d && <div className="grid gap-3 md:grid-cols-4">{[['Sent', d.sent], ['Delivered', d.delivered], ['Failed', d.failed], ['Cost', d.cost_paise != null ? `₹${(d.cost_paise / 100).toLocaleString('en-IN')}` : '—']].map(([k, v]) => <Card key={String(k)}><CardContent className="p-3"><p className="text-xs text-muted-foreground">{k}</p><p className="text-lg font-semibold">{String(v ?? 0)}</p></CardContent></Card>)}</div>}
      {d && <Section title="By channel"><SimpleTable head={['Channel', 'Sent', 'Delivered', 'Failed']} rows={(d.by_channel ?? []).map((x: Any) => [x.channel, x.sent, x.delivered, x.failed])} /></Section>}
      <Section title="Providers"><SimpleTable head={['Provider', 'Channel', 'Success %', 'Avg latency']} rows={list(pv.data).map((x: Any) => [x.provider, x.channel, x.success_pct ?? '—', x.avg_latency_s != null ? `${x.avg_latency_s}s` : '—'])} /></Section>
    </div>
  );
}

// ---- my messages -------------------------------------------------------------------------------------------------------
export function MyMessagesPage() {
  useTitle('My messages');
  const q = useQ(['mine'], () => cm.myMessages());
  return (
    <div className="space-y-4">
      <PageHeader title="My messages" description="SMS, WhatsApp, email and push messages sent to you." />
      <Card><CardContent className="p-2"><SimpleTable head={['When', 'Channel', 'Message', 'Status']} rows={list(q.data).map((m: Any) => [when(m.sent_at ?? m.created_at), m.channel, m.subject ?? m.body_preview ?? '—', <StatusBadge key="s" status={m.status} />])} /></CardContent></Card>
    </div>
  );
}
