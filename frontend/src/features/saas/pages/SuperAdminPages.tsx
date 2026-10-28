import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { useAuthStore } from '@/store/authStore';
import { platformApi, supportApi } from '../api';
import { Bars, d, dt, Err, inr, rows, Section, sel, show, Stat, useQ, useRun, useTitle, type Any } from '../components/kit';

// Phase 38 super-admin console (Prompts/38 §38.9). Masking for support agents, four-eyes, locks and limits are
// enforced by the API; these pages render what it returns and pass reasons / typed confirmations through.
const ask = (msg: string) => window.prompt(msg)?.trim() || '';

// ---- dashboard -------------------------------------------------------------------------------------------------------
export function SaasDashboardPage() {
  useTitle('Platform dashboard');
  const q = useQ(['dash'], () => platformApi.dashboard());
  const run = useRun('Refreshed');
  const x: Any = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Platform dashboard" description={x ? `Generated ${dt(x.generated_at)}${x.cached ? ' (cached)' : ''}` : undefined} actions={<Button size="sm" variant="outline" onClick={() => run.mutate(() => platformApi.dashboard(true))}>Refresh</Button>} />
      <Err q={q} />
      {x && (
        <>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Tenants" value={x.tenants_total} />
            <Stat label="MRR" value={inr(x.mrr_paise)} />
            <Stat label="ARR" value={inr(x.arr_paise)} />
            <Stat label="Overdue invoices" value={`${x.invoices_overdue.count} · ${inr(x.invoices_overdue.total_paise)}`} tone={x.invoices_overdue.count ? 'warn' : undefined} />
            <Stat label="SLA breaches" value={x.sla_breaches} tone={x.sla_breaches ? 'bad' : undefined} />
            <Stat label="Chain breaks" value={x.chain_breaks.length} tone={x.chain_breaks.length ? 'bad' : undefined} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Section title="Tenants by status"><Bars points={Object.entries(x.tenants.by_status).map(([label, value]) => ({ label, value: Number(value) }))} /></Section>
            <Section title="Tenants by plan"><Bars points={Object.entries(x.tenants.by_plan).map(([label, value]) => ({ label, value: Number(value) }))} /></Section>
            <Section title="Open tickets by priority"><Bars points={Object.entries(x.tickets_open_by_priority).map(([label, value]) => ({ label, value: Number(value) }))} /></Section>
            {x.charts.map((c: Any) => (
              <Section key={c.key} title={c.title}><Bars points={(c.series[0]?.points ?? []).slice(-12)} /></Section>
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="Trials ending in 7 days"><SimpleTable head={['Institution', 'Ends']} rows={x.trials_ending.map((t: Any) => [t.institution.name, d(t.ends_on)])} /></Section>
            <Section title="Provider outages"><SimpleTable head={['Provider', 'Failing', 'Since']} rows={x.outages.map((o: Any) => [`${o.provider} (${o.capability})`, `${o.failing}/${o.total}`, dt(o.since)])} empty="No outage." /></Section>
            <Section title="Alerts (chain breaks, anomalies, dead letters)" action={<Link className="text-xs underline" to="/super-admin/audit">Platform audit</Link>}>
              <SimpleTable head={['Kind', 'Institution', 'Last seen', '']} rows={x.alerts.map((a: Any) => [a.kind, a.institution?.name ?? '—', dt(a.last_seen), <ResolveAlert key="r" id={a.id} />])} empty="No open alerts." />
            </Section>
            <Section title="Top usage (this month)"><SimpleTable head={['Institution', 'API calls', 'SMS', 'Storage GB']} rows={x.usage_top.map((u: Any) => [u.institution?.name, u.api_calls, u.sms_sent, u.storage_gb])} /></Section>
            <Section title="Read-only windows active"><SimpleTable head={['Scope', 'Reason', 'Ends']} rows={x.read_only_active.map((w: Any) => [w.institution?.name ?? 'platform', w.reason, dt(w.ends_at)])} empty="None." /></Section>
            <Section title="Recent platform actions"><SimpleTable head={['When', 'Actor', 'Action', 'Tenant']} rows={x.recent_actions.map((r: Any) => [dt(r.occurred_at), r.actor?.name ?? 'system', r.summary, r.institution?.name ?? '—'])} /></Section>
          </div>
          <p className="text-xs text-muted-foreground">Dead letters (30 days): {x.jobs_dead_letters.total} · failing connections: {x.health_failing.length}</p>
        </>
      )}
    </div>
  );
}
function ResolveAlert({ id }: { id: string }) {
  const run = useRun('Alert resolved');
  return <Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.resolveAlert(id))}>Resolve</Button>;
}

// ---- institution detail ----------------------------------------------------------------------------------------------
export function SaasInstitutionDetailPage() {
  const { id = '' } = useParams();
  const q = useQ(['inst', id], () => platformApi.institution(id));
  const plans = useQ(['plans'], () => platformApi.plans());
  const run = useRun('Done');
  const [planId, setPlanId] = useState('');
  const preview = useQ(['preview', id, planId], () => platformApi.changePreview(planId, id), !!planId);
  const [caps, setCaps] = useState('');
  const x: Any = q.data?.data;
  useTitle(x?.name ?? 'Institution');
  const status = (action: string) => {
    const reason = ask(`Reason to ${action}`);
    if (reason) run.mutate(() => platformApi.status(id, action, reason));
  };
  if (!x) return <Err q={q} />;
  return (
    <div className="space-y-4">
      <PageHeader
        title={x.name}
        breadcrumbs={[{ label: 'Institutions', to: '/super-admin/institutions' }, { label: x.slug }]}
        description={<span className="flex items-center gap-2">{x.type.replace(/_/g, ' ')} · {x.plan ?? 'no plan'} ({x.subscription_status ?? 'none'}) <StatusBadge status={x.status} />{x.is_demo && <Badge>demo</Badge>}</span>}
        actions={
          <div className="flex flex-wrap gap-2">
            {['pending', 'suspended'].includes(x.status) && <Button size="sm" onClick={() => status('activate')}>Activate</Button>}
            {['pending', 'active'].includes(x.status) && <Button size="sm" variant="destructive" onClick={() => status('suspend')}>Suspend</Button>}
            {['active', 'suspended'].includes(x.status) && <Button size="sm" variant="outline" onClick={() => status('archive')}>Archive</Button>}
            {x.status === 'archived' && <Button size="sm" variant="outline" onClick={() => status('unarchive')}>Unarchive</Button>}
            <Link to={`/super-admin/institutions/${id}/features`}><Button size="sm" variant="outline">Features</Button></Link>
          </div>
        }
      />
      <Tabs defaultValue="overview">
        <TabsList>
          {['overview', 'subscription', 'usage', 'connections', 'tickets', 'impersonations', 'audit', 'danger'].map((t) => <TabsTrigger key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</TabsTrigger>)}
        </TabsList>
        <TabsContent value="overview" className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="Students" value={x.students_active} /><Stat label="Staff" value={x.staff_active} /><Stat label="Storage GB" value={x.storage_gb} /><Stat label="Health" value={x.health} tone={x.health === 'failing' ? 'bad' : undefined} />
          </div>
          <Section title="Profile"><pre className="overflow-x-auto text-xs">{JSON.stringify(x.profile, null, 1)}</pre></Section>
          <Section title="Status history"><SimpleTable head={['When', 'Action', 'From → to', 'Reason']} rows={x.status_log.map((s: Any) => [dt(s.at), s.action, `${s.from ?? '—'} → ${s.to}`, s.reason])} /></Section>
          <Section title="Last logins"><SimpleTable head={['Identifier', 'OK', 'When']} rows={x.last_logins.map((l: Any) => [l.identifier, l.success ? 'yes' : 'no', dt(l.created_at)])} /></Section>
        </TabsContent>
        <TabsContent value="subscription" className="space-y-3">
          <Section title="Change plan (preview first)" action={<div className="flex gap-2">{x.subscription?.status && <Button size="sm" variant="outline" onClick={() => run.mutate(() => platformApi.renew(id))}>Renew</Button>}<Button size="sm" variant="outline" onClick={() => { const r = ask('Cancellation reason'); if (r) run.mutate(() => platformApi.cancel(id, r)); }}>Cancel at period end</Button></div>}>
            <div className="flex gap-2">
              <select className={sel} value={planId} onChange={(e) => setPlanId(e.target.value)}>
                <option value="">Choose a plan…</option>
                {rows(plans.data).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.tier})</option>)}
              </select>
              {planId && <Button size="sm" disabled={!preview.data?.data?.allowed} onClick={() => run.mutate(() => platformApi.change(id, planId))}>Change now</Button>}
              {planId && <Button size="sm" variant="outline" onClick={() => run.mutate(() => platformApi.change(id, planId, 'next_cycle'))}>At next cycle</Button>}
            </div>
            {preview.data?.data && (
              <div className="text-xs">
                <p>Proration: {inr(preview.data.data.proration.net_paise)} ({preview.data.data.proration.remaining_days} days left)</p>
                <p>Disabled: {preview.data.data.features_disabled.map((f: Any) => `${f.key}${f.dependants.length ? ` (+${f.dependants.join(', ')})` : ''}`).join(', ') || '—'}</p>
                <p>Overrides kept: {preview.data.data.overrides_kept.join(', ') || '—'}</p>
                {preview.data.data.limit_violations.map((v: Any) => <p key={v.kind} className="text-destructive">{v.kind}: {v.current} over the limit {v.limit}</p>)}
              </div>
            )}
          </Section>
          <Section title="Invoices">
            <SimpleTable
              head={['Number', 'Period', 'Total', 'Status', 'Due', '']}
              rows={x.invoices.map((i: Any) => [i.number, i.period, inr(i.total_paise), <StatusBadge key="s" status={i.status} />, d(i.due_on), i.status !== 'paid' ? <Button key="p" size="sm" variant="ghost" onClick={() => { const ref = ask('Manual payment reference'); if (ref) run.mutate(() => platformApi.manualPay(id, i.number, ref)); }}>Record payment</Button> : i.payment_ref])}
            />
          </Section>
        </TabsContent>
        <TabsContent value="usage" className="space-y-3">
          <Section title="Last months"><SimpleTable head={['Month', 'Students', 'SMS', 'WhatsApp', 'E-mails', 'API calls', 'Cost']} rows={x.usage.map((m: Any) => [m.period_month, m.active_students, m.sms_sent, m.whatsapp_sent, m.emails_sent, m.api_calls, inr(m.cost_paise)])} /></Section>
          <Section title="Caps" action={<Button size="sm" onClick={() => { try { run.mutate(() => platformApi.caps(id, JSON.parse(caps || '{}'))); } catch { toast.error('Caps must be JSON'); } }}>Save caps</Button>}>
            <p className="text-xs text-muted-foreground">Current: {show(x.caps)}</p>
            <Input placeholder='{"api_calls_per_day": 100000, "sms_per_month": 5000}' value={caps} onChange={(e) => setCaps(e.target.value)} />
          </Section>
        </TabsContent>
        <TabsContent value="connections">
          <SimpleTable head={['Capability', 'Provider', 'Status', 'Last check', 'Error', '']} rows={x.connections.map((c: Any) => [c.capability, c.provider, <StatusBadge key="s" status={c.status} />, dt(c.last_health_at), c.last_error ?? '—', <Button key="r" size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.retry([c.id]))}>Retry</Button>])} />
        </TabsContent>
        <TabsContent value="tickets"><SimpleTable head={['Ticket', 'Subject', 'Priority', 'Status']} rows={x.open_tickets.map((t: Any) => [<Link key="l" className="underline" to={`/super-admin/support/${t.id}`}>{t.ticket_number}</Link>, t.subject, t.priority, t.status])} /></TabsContent>
        <TabsContent value="impersonations"><SimpleTable head={['Impersonator', 'Target', 'Reason', 'Started', 'Ended']} rows={x.impersonations.map((i: Any) => [i.impersonator, i.target, i.reason, dt(i.started_at), dt(i.ended_at)])} /></TabsContent>
        <TabsContent value="audit" className="space-y-3">
          <Section title="Chain integrity (Phase 37)"><p className="text-sm">{x.chain.ok === null ? 'Not verified yet' : x.chain.ok ? 'Intact' : 'Broken'} · digests {x.chain.digests} (last {x.chain.last_digest ?? '—'}) · open alerts {x.chain.open_alerts.length}</p></Section>
          <Link className="text-sm underline" to={`/super-admin/audit?institution_id=${id}`}>Platform actions on this tenant</Link>
        </TabsContent>
        <TabsContent value="danger" className="space-y-3">
          <Section title="Export (encrypted zip, password e-mailed separately)" action={<Button size="sm" onClick={() => run.mutate(() => platformApi.export(id))}>Export</Button>}>
            <SimpleTable head={['Export', 'Status', 'Expires', 'sha256']} rows={x.exports.map((e: Any) => [e.id, e.status, dt(e.expires_at), (e.sha256 ?? '').slice(0, 16)])} />
          </Section>
          <Section title="Reset (demo tenants)" action={<Button size="sm" variant="outline" onClick={() => { const s = ask(`Type ${x.slug} to reset`); if (s) run.mutate(() => platformApi.reset(id, s)); }}>Reset</Button>}><p className="text-xs text-muted-foreground">Operational data is deleted and re-seeded.</p></Section>
          <Section title="Erase (irreversible; four-eyes)" action={<Button size="sm" variant="destructive" onClick={() => { const s = ask(`Type ${x.slug} to erase`); const r = s && ask('Reason'); if (s && r) run.mutate(() => platformApi.erase(id, s, r)); }}>{x.erase_request ? 'Approve erasure' : 'Request erasure'}</Button>}>
            {x.erase_request && <p className="text-sm text-destructive">Requested {dt(x.erase_request.at)}: {x.erase_request.reason} — a second super admin approves.</p>}
          </Section>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---- plans -----------------------------------------------------------------------------------------------------------
export function SaasPlansPage() {
  useTitle('Plans');
  const q = useQ(['plans'], () => platformApi.plans());
  const run = useRun('Plan saved');
  const [edit, setEdit] = useState<Any>(null);
  return (
    <div className="space-y-4">
      <PageHeader title="Plans" description="Tiers, prices, limits and enabled features (validated against the feature registry tiers)." />
      <Err q={q} />
      <SimpleTable
        head={['Plan', 'Tier', 'Monthly', 'Yearly', 'Limits', 'Features', 'Subscribers', '']}
        rows={rows(q.data).map((p) => [p.name, <Badge key="t">{p.tier}</Badge>, inr(p.prices.monthly), inr(p.prices.yearly), `${p.limits.students ?? '∞'} students · ${p.limits.staff ?? '∞'} staff · ${p.limits.storage_gb ?? '∞'} GB`, p.enabled_features.length, p.subscribers,
          <div key="a" className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setEdit({ ...p, features: p.enabled_features.join('\n') })}>Edit</Button>{p.is_active && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.deactivatePlan(p.id))}>Deactivate</Button>}</div>])}
      />
      {edit && (
        <Section title={`Edit ${edit.name}`} action={<div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setEdit(null)}>Close</Button><Button size="sm" onClick={() => run.mutate(() => platformApi.updatePlan(edit.id, { price_paise_monthly: Number(edit.prices.monthly), price_paise_yearly: Number(edit.prices.yearly), enabled_features: edit.features.split(/\s+/).filter(Boolean), allow_above_tier: !!edit.above }))}>Save</Button></div>}>
          <div className="grid gap-2 sm:grid-cols-2">
            <Input type="number" value={edit.prices.monthly ?? ''} onChange={(e) => setEdit({ ...edit, prices: { ...edit.prices, monthly: e.target.value } })} placeholder="monthly paise" />
            <Input type="number" value={edit.prices.yearly ?? ''} onChange={(e) => setEdit({ ...edit, prices: { ...edit.prices, yearly: e.target.value } })} placeholder="yearly paise" />
          </div>
          <Textarea rows={8} value={edit.features} onChange={(e) => setEdit({ ...edit, features: e.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.above} onChange={(e) => setEdit({ ...edit, above: e.target.checked })} /> allow features above the tier</label>
        </Section>
      )}
    </div>
  );
}

// ---- billing / usage / impersonations --------------------------------------------------------------------------------
export function SaasBillingPage() {
  useTitle('Billing');
  const [status, setStatus] = useState('');
  const q = useQ(['invoices', status], () => platformApi.invoices({ status: status || undefined }));
  return (
    <div className="space-y-4">
      <PageHeader title="Billing" description="Invoices across tenants; dunning reminders at due − 7, due and due + 7." actions={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['issued', 'paid', 'overdue'].map((s) => <option key={s}>{s}</option>)}</select>} />
      <Err q={q} />
      <SimpleTable head={['Number', 'Institution', 'Period', 'Net', 'GST', 'Total', 'Status', 'Due', 'Dunning']} rows={rows(q.data).map((i) => [i.number, i.institution_name, i.period, inr(i.amount_paise), inr(i.gst_paise), inr(i.total_paise), <StatusBadge key="s" status={i.status} />, d(i.due_on), i.dunning.map((x: Any) => x.stage).join(', ') || '—'])} />
    </div>
  );
}

export function SaasUsagePage() {
  useTitle('Usage');
  const q = useQ(['usage'], () => platformApi.usage());
  const run = useRun('Queued — the result arrives in the jobs tray');
  const x: Any = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Usage" description="Metered per tenant and month; cost from the platform rates." actions={<div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => run.mutate(() => platformApi.meter())}>Meter now</Button><Button size="sm" onClick={() => run.mutate(() => platformApi.usageExport())}>Export CSV</Button></div>} />
      <Err q={q} />
      {x && <p className="text-sm text-muted-foreground">Totals: {Object.entries(x.totals).map(([k, v]) => `${k} ${k === 'cost_paise' ? inr(v) : Number(v).toLocaleString('en-IN')}`).join(' · ')}</p>}
      <SimpleTable head={['Institution', 'Month', 'Students', 'Staff', 'SMS', 'WhatsApp', 'API calls', 'AI tokens', 'Cost', 'Overage']} rows={(x?.months ?? []).slice(-120).reverse().map((m: Any) => [m.institution_name, m.period_month, m.active_students, m.active_staff, m.sms_sent, m.whatsapp_sent, m.api_calls, m.ai_tokens, inr(m.cost_paise), m.overage.map((o: Any) => `${o.metric} ${o.pct}%`).join(', ') || '—'])} />
    </div>
  );
}

export function SaasImpersonationsPage() {
  useTitle('Impersonations');
  const [active, setActive] = useState(false);
  const q = useQ(['imp', active], () => platformApi.impersonations({ active: active || undefined }));
  const run = useRun('Impersonation stopped');
  return (
    <div className="space-y-4">
      <PageHeader title="Impersonations" description="Every session with its reason and the writes made under it; sessions auto-stop after 60 minutes." actions={<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> active only</label>} />
      <Err q={q} />
      <SimpleTable head={['Impersonator', 'Target', 'Tenant', 'Reason', 'Started', 'Ended', 'Writes', '']} rows={rows(q.data).map((i) => [i.impersonator.name, i.target.name, i.institution?.name ?? '—', i.reason, dt(i.started_at), i.ended_at ? dt(i.ended_at) : <Badge key="a" variant="destructive">active</Badge>, i.writes_count, i.active ? <Button key="s" size="sm" variant="ghost" onClick={() => { const r = ask('Reason to force-stop'); if (r) run.mutate(() => platformApi.forceStop(i.id, r)); }}>Force-stop</Button> : i.ended_by ?? ''])} />
    </div>
  );
}

// ---- support desk ---------------------------------------------------------------------------------------------------
export function SaasSupportPage({ tenant = false }: { tenant?: boolean }) {
  useTitle('Support');
  const [scope, setScope] = useState('all');
  const [status, setStatus] = useState('');
  const q = useQ(['tickets', scope, status], () => supportApi.tickets({ scope, status: status || undefined }));
  const run = useRun('Ticket raised');
  const [form, setForm] = useState({ subject: '', description: '', priority: 'normal', category: 'other' });
  const base = tenant ? '/admin/support' : '/super-admin/support';
  return (
    <div className="space-y-4">
      <PageHeader title="Support" description={tenant ? 'Raise a ticket with the SeptronUniverse team and follow its thread.' : 'Ticket board by status / priority / assignee with SLA timers.'} actions={<div className="flex gap-2"><select className={sel} value={scope} onChange={(e) => setScope(e.target.value)}><option value="all">All</option><option value="mine">Mine</option></select><select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['open', 'in_progress', 'waiting', 'resolved', 'closed'].map((s) => <option key={s}>{s}</option>)}</select></div>} />
      {tenant && (
        <Section title="Raise a ticket" action={<Button size="sm" disabled={!form.subject || !form.description} onClick={() => run.mutate(() => supportApi.create(form))}>Raise</Button>}>
          <div className="grid gap-2 sm:grid-cols-3">
            <Input placeholder="Subject" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            <select className={sel} value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>{['urgent', 'high', 'normal', 'low'].map((p) => <option key={p}>{p}</option>)}</select>
            <select className={sel} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{['login', 'billing', 'data', 'integration', 'exams', 'mobile', 'other'].map((p) => <option key={p}>{p}</option>)}</select>
          </div>
          <Textarea rows={3} placeholder="What happened?" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Section>
      )}
      <Err q={q} />
      <SimpleTable head={['Ticket', 'Tenant', 'Subject', 'Priority', 'Status', 'Assignee', 'SLA due']} rows={rows(q.data).map((t) => [<Link key="l" className="underline" to={`${base}/${t.id}`}>{t.ticket_number}</Link>, t.institution?.name ?? '—', t.subject, t.priority, <StatusBadge key="s" status={t.status} />, t.assigned_to?.name ?? '—', <span key="d" className={t.breached ? 'text-destructive' : ''}>{dt(t.sla_due_at)}{t.breached ? ' (breached)' : ''}</span>])} />
    </div>
  );
}

export function SaasTicketPage({ tenant = false }: { tenant?: boolean }) {
  const { id = '' } = useParams();
  const me = useAuthStore((s) => s.currentUser);
  const q = useQ(['ticket', id], () => supportApi.ticket(id));
  const diag = useQ(['diag', id], () => supportApi.diagnostics(id), !tenant);
  const run = useRun('Saved');
  const [text, setText] = useState('');
  const [internal, setInternal] = useState(false);
  const t: Any = q.data?.data;
  useTitle(t?.ticket_number ?? 'Ticket');
  if (!t) return <Err q={q} />;
  return (
    <div className="space-y-4">
      <PageHeader title={`${t.ticket_number} · ${t.subject}`} breadcrumbs={[{ label: 'Support', to: tenant ? '/admin/support' : '/super-admin/support' }, { label: t.ticket_number }]} description={<span className="flex items-center gap-2"><StatusBadge status={t.status} /> {t.priority} · {t.category} · SLA {dt(t.sla_due_at)}{t.breached && <Badge variant="destructive">breached</Badge>}</span>}
        actions={
          <div className="flex flex-wrap gap-2">
            {!tenant && me && <Button size="sm" variant="outline" onClick={() => run.mutate(() => supportApi.assign(id, me.id))}>Assign to me</Button>}
            {!tenant && ['waiting', 'resolved'].map((s) => <Button key={s} size="sm" variant="outline" onClick={() => run.mutate(() => supportApi.status(id, s, s === 'resolved' ? ask('Resolution') : undefined))}>{s}</Button>)}
            {['resolved', 'closed'].includes(t.status) && t.can_reopen && <Button size="sm" variant="outline" onClick={() => run.mutate(() => supportApi.status(id, 'in_progress'))}>Reopen</Button>}
            {tenant && t.status === 'resolved' && [1, 2, 3, 4, 5].map((n) => <Button key={n} size="sm" variant="ghost" onClick={() => run.mutate(() => supportApi.rate(id, n))}>{'★'.repeat(n)}</Button>)}
            {!tenant && t.institution && <Link to={`/super-admin/institutions/${t.institution.id}`}><Button size="sm" variant="ghost">Tenant</Button></Link>}
          </div>
        }
      />
      <Section title="Thread">
        <p className="whitespace-pre-wrap text-sm">{t.description}</p>
        {t.messages.map((m: Any) => (
          <div key={m.id} className={`rounded border p-2 text-sm ${m.internal ? 'border-warning bg-warning/10' : ''}`}>
            <p className="text-xs text-muted-foreground">{m.by?.name ?? 'system'} · {dt(m.at)}{m.internal ? ' · internal note' : ''}</p>
            <p className="whitespace-pre-wrap">{m.text}</p>
          </div>
        ))}
        <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Reply…" />
        <div className="flex items-center gap-3">
          {!tenant && <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> internal note</label>}
          <Button size="sm" disabled={!text} onClick={() => run.mutate(async () => { await supportApi.reply(id, text, internal); setText(''); })}>Send</Button>
        </div>
      </Section>
      {!tenant && diag.data?.data && (
        <Section title="Diagnostics">
          <pre className="max-h-96 overflow-auto text-xs">{JSON.stringify(diag.data.data, null, 1)}</pre>
        </Section>
      )}
    </div>
  );
}

// ---- help authoring (platform and institution) ------------------------------------------------------------------------
export function SaasHelpPage({ tenant = false }: { tenant?: boolean }) {
  useTitle('Help articles');
  const q = useQ(['help'], () => supportApi.helpList());
  const run = useRun('Saved');
  const [a, setA] = useState<Any>(null);
  const save = () => {
    const body = { slug: a.slug, title: a.title, body: a.body, module: a.module || null, is_published: a.is_published ?? true, audience: { roles: String(a.roles ?? '').split(',').map((s: string) => s.trim()).filter(Boolean), portals: [], public: false } };
    run.mutate(async () => { await (a.id ? supportApi.helpUpdate(a.id, body) : supportApi.helpCreate(body)); setA(null); });
  };
  const exportJson = async () => {
    const r = await supportApi.helpExport();
    const url = URL.createObjectURL(new Blob([JSON.stringify(r.data, null, 1)], { type: 'application/json' }));
    Object.assign(document.createElement('a'), { href: url, download: 'help-articles.json' }).click();
  };
  const importJson = async (f: File) => run.mutate(async () => supportApi.helpImport(JSON.parse(await f.text())));
  return (
    <div className="space-y-4">
      <PageHeader title="Help articles" description={tenant ? 'Institution articles; the same slug overrides the platform article for your institution only.' : 'Platform articles (markdown) with contextual slugs help:<route>.'}
        actions={<div className="flex gap-2"><Button size="sm" onClick={() => setA({ slug: 'help:/', title: '', body: '' })}>New</Button>{!tenant && <><Button size="sm" variant="outline" onClick={exportJson}>Export</Button><label className="cursor-pointer rounded border px-3 py-1.5 text-sm">Import<input type="file" accept="application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} /></label></>}</div>} />
      <Err q={q} />
      {a && (
        <Section title={a.id ? `Edit ${a.slug}` : 'New article'} action={<div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setA(null)}>Close</Button><Button size="sm" onClick={save}>Save</Button></div>}>
          <div className="grid gap-2 sm:grid-cols-3">
            <Input placeholder="slug (help:/admin/fees/collect)" value={a.slug} onChange={(e) => setA({ ...a, slug: e.target.value })} />
            <Input placeholder="title" value={a.title} onChange={(e) => setA({ ...a, title: e.target.value })} />
            <Input placeholder="roles (comma separated, empty = everyone)" value={a.roles ?? ''} onChange={(e) => setA({ ...a, roles: e.target.value })} />
          </div>
          <div className="grid gap-2 lg:grid-cols-2">
            <Textarea rows={14} value={a.body} onChange={(e) => setA({ ...a, body: e.target.value })} />
            <div className="prose-sm max-h-80 overflow-auto whitespace-pre-wrap rounded border p-2 text-sm">{a.body}</div>
          </div>
        </Section>
      )}
      <SimpleTable head={['Slug', 'Title', 'Module', 'Published', 'Helpful', '']} rows={rows(q.data).map((r) => [r.slug, r.title, r.module ?? '—', r.is_published ? 'yes' : 'no', show(r.helpful), <div key="a" className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setA({ ...r, roles: (r.audience?.roles ?? []).join(', ') })}>Edit</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => supportApi.helpDelete(r.id))}>Delete</Button></div>])} />
    </div>
  );
}

// ---- feedback / announcements / health -------------------------------------------------------------------------------
export function SaasFeedbackPage() {
  useTitle('Feedback');
  const [status, setStatus] = useState('new');
  const q = useQ(['feedback', status], () => platformApi.feedback({ status: status || undefined }));
  const run = useRun('Saved');
  return (
    <div className="space-y-4">
      <PageHeader title="Feedback" description="Triage in-app feedback, respond to the author or convert to a ticket." actions={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['new', 'triaged', 'planned', 'done', 'declined'].map((s) => <option key={s}>{s}</option>)}</select>} />
      <Err q={q} />
      <SimpleTable head={['When', 'Tenant', 'User', 'Page', 'Rating', 'Message', 'Status', '']} rows={rows(q.data).map((f) => [d(f.created_at), f.institution?.name ?? '—', f.user?.name ?? '—', f.page, f.rating ?? '—', f.message, f.status,
        <div key="a" className="flex gap-1">{['triaged', 'planned', 'done', 'declined'].map((s) => <Button key={s} size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.triage(f.id, { status: s, respond_text: s === 'triaged' ? undefined : ask('Response to the author (optional)') || undefined }))}>{s}</Button>)}{!f.ticket_number ? <Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.toTicket(f.id))}>→ ticket</Button> : f.ticket_number}</div>])} />
    </div>
  );
}

export function SaasAnnouncementsPage() {
  useTitle('Announcements');
  const q = useQ(['ann'], () => platformApi.announcements());
  const run = useRun('Saved');
  const [f, setF] = useState({ title: '', body: '', type: 'all', values: '', channels: 'banner,inapp', kind: 'info', ends_at: '' });
  const publish = () => run.mutate(() => platformApi.createAnnouncement({ title: f.title, body: f.body, kind: f.kind, audience: { type: f.type, values: f.values.split(',').map((s) => s.trim()).filter(Boolean) }, channels: f.channels.split(',').map((s) => s.trim()).filter(Boolean), ends_at: f.ends_at ? new Date(f.ends_at).toISOString() : null }));
  return (
    <div className="space-y-4">
      <PageHeader title="Announcements" description="Release notes, maintenance notices and incident updates; audience by plan, institution type, tenants or roles." />
      <Section title="New announcement" action={<Button size="sm" disabled={!f.title || !f.body} onClick={publish}>Publish</Button>}>
        <div className="grid gap-2 sm:grid-cols-3">
          <Input placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          <select className={sel} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>{['all', 'plan', 'institution_type', 'institution_ids', 'roles'].map((s) => <option key={s}>{s}</option>)}</select>
          <Input placeholder="values (comma separated)" value={f.values} onChange={(e) => setF({ ...f, values: e.target.value })} />
          <Input placeholder="channels: banner,inapp,email" value={f.channels} onChange={(e) => setF({ ...f, channels: e.target.value })} />
          <select className={sel} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{['info', 'release', 'maintenance', 'incident'].map((s) => <option key={s}>{s}</option>)}</select>
          <Input type="datetime-local" value={f.ends_at} onChange={(e) => setF({ ...f, ends_at: e.target.value })} />
        </div>
        <Textarea rows={3} placeholder="Body" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />
      </Section>
      <Err q={q} />
      <SimpleTable head={['Title', 'Audience', 'Channels', 'Window', 'Live', 'Delivered', '']} rows={rows(q.data).map((a) => [a.title, `${a.audience.type} ${a.audience.values.join(', ')}`, a.channels.join(', '), `${d(a.starts_at)} – ${d(a.ends_at)}`, a.live ? 'yes' : 'no', show(a.delivered?.tenants), <Button key="x" size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.deleteAnnouncement(a.id))}>Delete</Button>])} />
    </div>
  );
}

export function SaasHealthPage() {
  useTitle('Integration health');
  const [status, setStatus] = useState('');
  const q = useQ(['health', status], () => platformApi.health({ status: status || undefined }));
  const out = useQ(['outages'], () => platformApi.outages());
  const run = useRun('Done');
  return (
    <div className="space-y-4">
      <PageHeader title="Integration health" description="Latest probe per connection across tenants; ≥ 50 % failing for a provider is an outage." actions={<select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['healthy', 'degraded', 'failed', 'disabled'].map((s) => <option key={s}>{s}</option>)}</select>} />
      {rows(out.data).map((o) => <p key={`${o.provider}${o.capability}`} className="rounded border border-destructive p-2 text-sm text-destructive">Outage: {o.provider} ({o.capability}) failing on {o.failing}/{o.total} tenants since {dt(o.since)}</p>)}
      <Err q={q} />
      <SimpleTable head={['Tenant', 'Capability', 'Provider', 'Status', 'Failing since', 'Latency', 'Error', '']} rows={rows(q.data).map((r) => [r.institution?.name, r.capability, r.provider, <StatusBadge key="s" status={r.status} />, dt(r.failing_since), r.latency_ms ?? '—', r.last_error ?? '—',
        <div key="a" className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.retry([r.connection_id]))}>Retry</Button>{r.status !== 'disabled' && <Button size="sm" variant="ghost" onClick={() => { const why = ask('Reason to disable'); if (why) run.mutate(() => platformApi.disable(r.connection_id, why)); }}>Disable</Button>}</div>])} />
    </div>
  );
}

// ---- read-only windows (platform and tenant) -------------------------------------------------------------------------
export function SaasReadOnlyPage({ tenant = false }: { tenant?: boolean }) {
  useTitle('Read-only windows');
  const q = useQ(['ro'], () => supportApi.windows({ include_past: true }));
  const run = useRun('Saved');
  const [f, setF] = useState({ reason: '', starts_at: '', ends_at: '', scope: tenant ? 'institution' : 'platform', institution_id: '' });
  const schedule = () => run.mutate(() => supportApi.schedule({ reason: f.reason, scope: f.scope, institution_id: f.institution_id || undefined, starts_at: new Date(f.starts_at).toISOString(), ends_at: new Date(f.ends_at).toISOString() }));
  return (
    <div className="space-y-4">
      <PageHeader title="Read-only windows" description="Scheduled maintenance / exam-day windows; a banner announces them ahead of the start." />
      <Section title="Schedule a window" action={<Button size="sm" disabled={!f.reason || !f.starts_at || !f.ends_at} onClick={schedule}>Schedule</Button>}>
        <div className="grid gap-2 sm:grid-cols-4">
          <Input placeholder="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
          <Input type="datetime-local" value={f.starts_at} onChange={(e) => setF({ ...f, starts_at: e.target.value })} />
          <Input type="datetime-local" value={f.ends_at} onChange={(e) => setF({ ...f, ends_at: e.target.value })} />
          {!tenant && <select className={sel} value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })}><option value="platform">platform</option><option value="institution">tenant</option></select>}
          {!tenant && f.scope === 'institution' && <Input placeholder="institution id" value={f.institution_id} onChange={(e) => setF({ ...f, institution_id: e.target.value })} />}
        </div>
      </Section>
      <Err q={q} />
      <SimpleTable head={['Scope', 'Reason', 'Starts', 'Ends', 'State', '']} rows={rows(q.data).map((w) => [w.institution?.name ?? 'platform', w.reason, dt(w.starts_at), dt(w.ends_at), w.state, ['upcoming', 'active'].includes(w.state) ? <Button key="c" size="sm" variant="ghost" onClick={() => run.mutate(() => supportApi.cancelWindow(w.id))}>Cancel</Button> : ''])} />
    </div>
  );
}

// ---- platform settings -----------------------------------------------------------------------------------------------
export function SaasSettingsPage() {
  useTitle('Platform settings');
  const q = useQ(['psettings'], () => platformApi.settings());
  const run = useRun('Platform settings saved');
  const [draft, setDraft] = useState<Record<string, string>>({});
  const save = () => {
    try {
      const values = Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, JSON.parse(v)]));
      run.mutate(async () => { await platformApi.saveSettings(values, ask('Reason (optional)') || undefined); setDraft({}); });
    } catch {
      toast.error('Values are JSON (strings in quotes)');
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Platform settings" description="Billing profile, rates, defaults, minimum app versions, captcha, on-call, danger flags. Secrets show as *** — keep *** to leave them unchanged." actions={<Button size="sm" disabled={!Object.keys(draft).length} onClick={save}>Save</Button>} />
      <Err q={q} />
      <SimpleTable head={['Group', 'Key', 'Value (JSON)', 'Updated']} rows={rows(q.data).map((s) => [s.group, <span key="k" title={s.label}>{s.key}</span>, <Textarea key="v" rows={2} className="font-mono text-xs" value={draft[s.key] ?? JSON.stringify(s.value)} onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })} />, dt(s.updated_at)])} />
    </div>
  );
}

// ---- registrations / demo requests / audit ----------------------------------------------------------------------------
export function SaasRegistrationsPage() {
  useTitle('Registrations');
  const q = useQ(['regs'], () => platformApi.registrations());
  const run = useRun('Done');
  const stages = ['pending', 'verified', 'paid', 'provisioned', 'failed', 'expired'];
  return (
    <div className="space-y-4">
      <PageHeader title="Registrations" description="Self-serve pipeline: pending → verified → paid → provisioned / failed / expired." />
      <Err q={q} />
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {stages.map((s) => (
          <Section key={s} title={`${s} (${rows(q.data).filter((r) => r.status === s).length})`}>
            {rows(q.data).filter((r) => r.status === s).map((r) => (
              <div key={r.id} className="rounded border p-2 text-xs">
                <p className="font-medium">{r.institution_name}</p>
                <p className="text-muted-foreground">{r.slug} · {r.plan}{r.trial ? ' · trial' : ''}</p>
                {r.error && <p className="text-destructive">{r.error}</p>}
                <div className="mt-1 flex flex-wrap gap-1">
                  {s === 'pending' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.registrationAction(r.id, 'verify'))}>Verify</Button>}
                  {['verified', 'paid'].includes(s) && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.registrationAction(r.id, 'provision'))}>Provision</Button>}
                  {s === 'failed' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.registrationAction(r.id, 'retry'))}>Retry</Button>}
                  {['pending', 'verified', 'failed'].includes(s) && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.registrationAction(r.id, 'expire'))}>Expire</Button>}
                </div>
              </div>
            ))}
          </Section>
        ))}
      </div>
    </div>
  );
}

export function SaasDemoRequestsPage() {
  useTitle('Demo requests');
  const q = useQ(['demo'], () => platformApi.demoRequests());
  const run = useRun('Updated');
  const cols = ['new', 'contacted', 'converted', 'dropped'];
  return (
    <div className="space-y-4">
      <PageHeader title="Demo requests" description="CRM-lite: move leads across the board and keep notes." />
      <Err q={q} />
      <div className="grid gap-3 md:grid-cols-4">
        {cols.map((c) => (
          <Section key={c} title={`${c} (${rows(q.data).filter((r) => r.status === c).length})`}>
            {rows(q.data).filter((r) => r.status === c).map((r) => (
              <div key={r.id} className="rounded border p-2 text-xs">
                <p className="font-medium">{r.name} · {r.institution_name ?? '—'}</p>
                <p className="text-muted-foreground">{r.email} · {d(r.created_at)}</p>
                {r.notes.slice(-1).map((n: Any, i: number) => <p key={i} className="italic">{n.text}</p>)}
                <div className="mt-1 flex flex-wrap gap-1">{cols.filter((x) => x !== c).map((x) => <Button key={x} size="sm" variant="ghost" onClick={() => run.mutate(() => platformApi.updateDemo(r.id, x, ask('Note (optional)') || undefined))}>{x}</Button>)}</div>
              </div>
            ))}
          </Section>
        ))}
      </div>
    </div>
  );
}

export function SaasAuditPage() {
  useTitle('Platform audit');
  const params = new URLSearchParams(window.location.search);
  const [f, setF] = useState({ institution_id: params.get('institution_id') ?? '', module: '', from: '', to: '' });
  const q = useQ(['paudit', f], () => platformApi.audit(Object.fromEntries(Object.entries(f).filter(([, v]) => v))));
  return (
    <div className="space-y-4">
      <PageHeader title="Platform audit" description="Platform actions, support reads and impersonated writes across tenants (Phase 37 audit chain)." />
      <div className="flex flex-wrap gap-2">
        <Input className="w-72" placeholder="institution id" value={f.institution_id} onChange={(e) => setF({ ...f, institution_id: e.target.value })} />
        <Input className="w-36" placeholder="module" value={f.module} onChange={(e) => setF({ ...f, module: e.target.value })} />
        <Input type="date" className="w-40" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} />
        <Input type="date" className="w-40" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} />
      </div>
      <Err q={q} />
      <SimpleTable head={['When', 'Tenant', 'Actor', 'Module', 'Summary']} rows={rows(q.data).map((r) => [dt(r.occurred_at), r.institution?.name ?? '—', `${r.actor?.name ?? 'system'}${r.impersonator ? ` (as ${r.impersonator.name})` : ''}`, `${r.module}:${r.action}`, r.summary])} />
    </div>
  );
}
