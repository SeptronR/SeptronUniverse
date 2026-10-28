import { useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { dt, rows, Section, sel, Stat, useQ, useRun, useTitle, type Any } from '@/features/saas/components/kit';
import { opsApi as oa } from '../api';

const input = 'h-9 w-full rounded-md border bg-background px-2 text-sm';
const TABS = ['overview', 'deploys', 'backups', 'alerts', 'incidents', 'capacity', 'partitions', 'scripts', 'config', 'releases'] as const;
const SCRIPTS = ['rollover', 'close_term', 'archive_year', 'tenant_export', 'tenant_restore', 'key_rotation', 'reindex_search'];
const COMPONENTS = ['api', 'web', 'workers', 'database', 'redis', 'storage', 'payments', 'sms', 'whatsapp', 'email', 'push'];
const tone = (s: string) => (s === 'operational' || s === 'succeeded' || s === 'passed' || s === 'ok' ? 'active' : s === 'degraded' || s === 'maintenance' || s === 'pending_approval' ? 'pending' : 'failed');

/** /super-admin/ops — operations console (overview, deploys, backups & DR, alerts, incidents, capacity, partitions,
 * scripts with four-eyes, config, releases). Support agents read; writes are super-admin only (API enforced). */
export function OpsConsolePage() {
  useTitle('Operations');
  const [tab, setTab] = useState<(typeof TABS)[number]>('overview');
  return (
    <div className="space-y-4">
      <PageHeader title="Operations" description="Deploys, backups, alerts, status page and capacity" />
      <div className="flex flex-wrap gap-2" role="tablist">
        {TABS.map((t) => (
          <Button key={t} role="tab" aria-selected={tab === t} size="sm" variant={tab === t ? 'default' : 'outline'} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </Button>
        ))}
      </div>
      {tab === 'overview' && <Overview />}
      {tab === 'deploys' && <Deploys />}
      {tab === 'backups' && <Backups />}
      {tab === 'alerts' && <Alerts />}
      {tab === 'incidents' && <Incidents />}
      {tab === 'capacity' && <Capacity />}
      {tab === 'partitions' && <Partitions />}
      {tab === 'scripts' && <Scripts />}
      {tab === 'config' && <Config />}
      {tab === 'releases' && <Releases />}
    </div>
  );
}

function Overview() {
  const q = useQ(['ops-overview'], () => oa.overview(), true, 15000);
  const o: Any = q.data?.data ?? {};
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Environment / version" value={`${o.env ?? '—'} · ${o.version ?? '—'}`} />
        <Stat label="Migration head" value={o.migrations?.head ?? '—'} />
        <Stat label="Outbox lag" value={o.outbox ? `${o.outbox.lag_s}s (${o.outbox.pending})` : '—'} tone={o.outbox?.lag_s > 120 ? 'bad' : undefined} />
        <Stat label="Backup age" value={o.backups?.age_min == null ? 'none yet' : `${o.backups.age_min} min`} tone={o.backups?.age_min == null || o.backups.age_min > 360 ? 'warn' : undefined} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Queues">
          <ul className="divide-y text-sm">
            {(o.queues ?? []).map((x: Any) => (
              <li key={x.name} className="flex justify-between py-1"><span>{x.name}</span><span>{x.depth} queued · {x.worker_alive ? 'worker alive' : 'no heartbeat'}</span></li>
            ))}
          </ul>
        </Section>
        <Section title="Dead letters / data">
          <p className="text-sm">Outbox {o.dlq?.outbox ?? 0} · webhooks {o.dlq?.webhooks ?? 0} · notifications {o.dlq?.notifications ?? 0}</p>
          <p className="text-sm">DB {o.db?.connections ?? '—'} connections · {o.db?.size_gb ?? '—'} GB · Redis {o.redis?.used_mb ?? '—'} MB</p>
          <p className="text-sm">Last deploy: {o.last_deploy ? `${o.last_deploy.env} ${o.last_deploy.sha ?? ''} ${o.last_deploy.status}` : '—'} · last drill: {o.restore_drill ? `${o.restore_drill.status} ${dt(o.restore_drill.date)}` : '—'}</p>
        </Section>
      </div>
      <Section title={`Active alerts (${(o.alerts_active ?? []).length})`}>
        <ul className="text-sm">{(o.alerts_active ?? []).map((a: Any) => <li key={a.id}>{a.rule} · {a.severity} · {a.summary}</li>)}</ul>
      </Section>
    </>
  );
}

function Deploys() {
  const q = useQ(['ops-deploys'], () => oa.deploys());
  const run = useRun('Noted');
  return (
    <Section title="Deploys">
      <table className="w-full text-sm">
        <thead><tr className="text-left text-muted-foreground"><th>Env</th><th>SHA</th><th>Images</th><th>Status</th><th>Started</th><th>Finished</th><th /></tr></thead>
        <tbody>{rows(q.data).map((d: Any) => (
          <tr key={d.id} className="border-t">
            <td className="py-1">{d.env}</td><td><code>{(d.sha ?? '').slice(0, 8)}</code></td>
            <td className="text-xs">{d.image_tags?.api}</td><td><StatusBadge status={tone(d.status)} /> {d.status}{d.rollback_to ? ` → ${d.rollback_to}` : ''}</td>
            <td>{dt(d.started_at)}</td><td>{dt(d.finished_at)}</td>
            <td><Button size="sm" variant="ghost" onClick={() => { const n = window.prompt('Note'); if (n) run.mutate(async () => { await oa.noteDeploy(d.id, n); await q.refetch(); }); }}>Note</Button></td>
          </tr>
        ))}</tbody>
      </table>
    </Section>
  );
}

function Backups() {
  const b = useQ(['ops-backups'], () => oa.backups());
  const d = useQ(['ops-drills'], () => oa.drills());
  const s: Any = b.data?.data?.summary ?? {};
  return (
    <>
      <Section title="Backups">
        <p className="text-sm">Last success {dt(s.last_success_at)} · full {dt(s.last_full)} · incr {dt(s.last_incr)} · status {s.status ?? '—'}</p>
        <ul className="divide-y text-sm">{(b.data?.data?.log ?? []).slice(0, 50).map((r: Any) => (
          <li key={r.id} className="flex gap-2 py-1"><span className="w-40 text-xs text-muted-foreground">{dt(r.finished_at)}</span><span className="flex-1">{r.kind}</span><StatusBadge status={tone(r.status === 'succeeded' ? 'ok' : 'failed')} /></li>
        ))}</ul>
      </Section>
      <Section title="Restore drills (target RPO 15 min / RTO 4 h)">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted-foreground"><th>Date</th><th>RPO (min)</th><th>RTO (min)</th><th>Checks</th><th>Status</th></tr></thead>
          <tbody>{rows(d.data).map((r: Any) => <tr key={r.id} className="border-t"><td className="py-1">{dt(r.date)}</td><td>{r.rpo_observed_min}</td><td>{r.rto_observed_min}</td><td>{(r.verified_checks ?? []).length}</td><td><StatusBadge status={tone(r.status)} /></td></tr>)}</tbody>
        </table>
      </Section>
    </>
  );
}

function Alerts() {
  const ev = useQ(['ops-alerts'], () => oa.alerts());
  const rules = useQ(['ops-rules'], () => oa.rules());
  const run = useRun('Test recorded');
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Section title="Events">
        <ul className="divide-y text-sm">{rows(ev.data).slice(0, 100).map((a: Any) => (
          <li key={`${a.id}${a.fired_at}`} className="py-1"><span className="text-xs text-muted-foreground">{dt(a.fired_at)}</span> · {a.rule} · {a.severity} · {a.status}</li>
        ))}</ul>
      </Section>
      <Section title="Rules">
        <ul className="divide-y text-sm">{rows(rules.data).map((r: Any) => (
          <li key={r.alert} className="flex items-center gap-2 py-1">
            <span className="flex-1"><span className="font-medium">{r.alert}</span> <span className="text-xs text-muted-foreground">{r.severity} · {r.summary}</span></span>
            <Button size="sm" variant="ghost" onClick={() => run.mutate(async () => { await oa.testAlert(r.alert); await ev.refetch(); })}>Test</Button>
          </li>
        ))}</ul>
      </Section>
    </div>
  );
}

function Incidents() {
  const inc = useQ(['ops-incidents'], () => oa.incidents());
  const status = useQ(['public-status'], () => oa.publicStatus());
  const run = useRun('Saved');
  const [form, setForm] = useState({ title: '', components: 'api', message: '' });
  return (
    <>
      <Section title="Components (public page)">
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{(status.data?.data?.components ?? []).map((c: Any) => (
          <li key={c.key} className="flex items-center gap-2 text-sm">
            <StatusBadge status={tone(c.state)} /><span className="flex-1">{c.key}</span>
            <select className={sel} aria-label={`${c.key} state`} value="" onChange={(e) => run.mutate(async () => { await oa.setComponent(c.key, e.target.value === 'auto' ? null : e.target.value); await status.refetch(); })}>
              <option value="">Set…</option>{['auto', 'operational', 'degraded', 'outage', 'maintenance'].map((s) => <option key={s}>{s}</option>)}
            </select>
          </li>
        ))}</ul>
      </Section>
      <Section title="Open an incident">
        <div className="flex flex-wrap gap-2">
          <input className={`${input} max-w-xs`} placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <select className={sel} aria-label="Component" value={form.components} onChange={(e) => setForm({ ...form, components: e.target.value })}>{COMPONENTS.map((c) => <option key={c}>{c}</option>)}</select>
          <input className={`${input} max-w-md`} placeholder="First update" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
          <Button size="sm" disabled={form.title.length < 3} onClick={() => run.mutate(async () => { await oa.openIncident({ title: form.title, components: [form.components], message: form.message }); await inc.refetch(); })}>Open</Button>
        </div>
      </Section>
      <Section title="Incidents">
        <ul className="space-y-3">{rows(inc.data).map((i: Any) => (
          <li key={i.id} className="text-sm">
            <div className="flex items-center gap-2"><StatusBadge status={i.state === 'resolved' ? 'active' : 'failed'} /><span className="flex-1 font-medium">{i.title}</span>
              {i.state !== 'resolved' && <>
                <Button size="sm" variant="ghost" onClick={() => { const m = window.prompt('Update'); if (m) run.mutate(async () => { await oa.updateIncident(i.id, 'monitoring', m); await inc.refetch(); }); }}>Update</Button>
                <Button size="sm" variant="outline" onClick={() => { const m = window.prompt('Resolution summary') ?? ''; run.mutate(async () => { await oa.updateIncident(i.id, 'resolved', m); await inc.refetch(); }); }}>Resolve</Button>
              </>}
            </div>
            <ol className="ml-6 list-disc text-xs text-muted-foreground">{(i.updates ?? []).map((u: Any, n: number) => <li key={n}>{dt(u.at)} · {u.state} · {u.message}</li>)}</ol>
          </li>
        ))}</ul>
      </Section>
    </>
  );
}

function Capacity() {
  const q = useQ(['ops-capacity'], () => oa.capacity());
  const run = useRun('Snapshot taken');
  const c: Any = q.data?.data ?? {};
  const last = (c.snapshots ?? []).at(-1);
  return (
    <Section title="Capacity" action={<Button size="sm" variant="outline" onClick={() => run.mutate(async () => { await oa.snapshot(); await q.refetch(); })}>Snapshot now</Button>}>
      {last && <p className="text-sm">{last.date}: {last.tenants} tenants · {last.students} students · {last.staff} staff · DB {last.db_size_gb} GB · queue peak {last.queue_depth_peak}</p>}
      <p className="text-sm">12-month projection: students {c.projections?.students_12m ?? '—'} · DB {c.projections?.db_size_gb_12m ?? '—'} GB</p>
      <ul className="mt-2 list-disc pl-5 text-sm">{(c.recommendations ?? []).map((r: string) => <li key={r}>{r}</li>)}</ul>
    </Section>
  );
}

function Partitions() {
  const q = useQ(['ops-partitions'], () => oa.partitions());
  const run = useRun('Queued');
  return (
    <Section title="Partitions" action={<Button size="sm" onClick={() => run.mutate(() => oa.ensurePartitions())}>Ensure next month</Button>}>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-muted-foreground"><th>Table</th><th>Partitions</th><th>Next month</th><th>Oldest</th></tr></thead>
        <tbody>{rows(q.data).map((p: Any) => <tr key={p.table} className="border-t"><td className="py-1">{p.table}</td><td>{p.partitions.length}</td><td>{p.next_month_exists ? 'yes' : <span className="text-red-600">missing</span>}</td><td>{p.oldest ?? '—'}</td></tr>)}</tbody>
      </table>
    </Section>
  );
}

function Scripts() {
  const q = useQ(['ops-scripts'], () => oa.scriptRuns(), true, 10000);
  const run = useRun('Requested');
  const [script, setScript] = useState('rollover');
  const [params, setParams] = useState('{"institution": "demo-uni"}');
  return (
    <>
      <Section title="Run a script (tenant_restore, key_rotation and archive_year need a second super admin)">
        <div className="flex flex-wrap gap-2">
          <select className={sel} aria-label="Script" value={script} onChange={(e) => setScript(e.target.value)}>{SCRIPTS.map((s) => <option key={s}>{s}</option>)}</select>
          <input className={`${input} max-w-xl font-mono`} aria-label="Parameters (JSON)" value={params} onChange={(e) => setParams(e.target.value)} />
          <Button size="sm" onClick={() => run.mutate(async () => { await oa.runScript(script, JSON.parse(params || '{}')); await q.refetch(); })}>Request</Button>
          <Button size="sm" variant="outline" onClick={() => run.mutate(() => oa.cacheWarm())}>Warm caches</Button>
        </div>
      </Section>
      <Section title="Runs">
        <ul className="divide-y text-sm">{rows(q.data).map((r: Any) => (
          <li key={r.id} className="flex items-center gap-2 py-1">
            <span className="w-40 text-xs text-muted-foreground">{dt(r.requested_at)}</span><span className="flex-1">{r.script} <code className="text-xs">{JSON.stringify(r.params)}</code></span>
            <StatusBadge status={tone(r.status)} /> <span className="text-xs">{r.status}</span>
            {r.status === 'pending_approval' && <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { await oa.approveScript(r.id); await q.refetch(); })}>Approve</Button>}
          </li>
        ))}</ul>
      </Section>
    </>
  );
}

function Config() {
  const q = useQ(['ops-config'], () => oa.config());
  return <Section title="Configuration (non-secret)"><pre className="overflow-auto text-xs">{JSON.stringify(q.data?.data ?? {}, null, 1)}</pre></Section>;
}

function Releases() {
  const q = useQ(['ops-releases'], () => oa.releases());
  const run = useRun('Saved');
  const [version, setVersion] = useState('');
  const [notes, setNotes] = useState('');
  return (
    <>
      <Section title="Record a release">
        <div className="flex flex-wrap gap-2">
          <input className={`${input} max-w-[10rem]`} placeholder="1.0.0" value={version} onChange={(e) => setVersion(e.target.value)} />
          <input className={`${input} max-w-xl`} placeholder="Release notes (markdown)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <Button size="sm" disabled={!version} onClick={() => run.mutate(async () => { await oa.addRelease({ version, notes_md: notes }); await q.refetch(); })}>Save</Button>
        </div>
      </Section>
      <Section title="Releases">
        <ul className="divide-y text-sm">{rows(q.data).map((r: Any) => (
          <li key={r.version} className="flex items-center gap-2 py-1">
            <span className="flex-1 font-medium">{r.version}</span><span className="text-xs text-muted-foreground">{dt(r.date)}</span>
            {r.announced_at ? <span className="text-xs">announced {dt(r.announced_at)}</span> : <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { await oa.announce(r.version); await q.refetch(); })}>Announce</Button>}
          </li>
        ))}</ul>
      </Section>
    </>
  );
}

/** /status — public status page: components with 90-day uptime, incidents, maintenance, RSS. */
export function StatusPage() {
  useTitle('System status');
  const q = useQ(['public-status'], () => oa.publicStatus(), true, 60000);
  const s: Any = q.data?.data;
  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">SeptronUniverse status</h1>
        <p className={`mt-2 rounded-md p-3 text-sm ${s?.overall === 'operational' ? 'bg-green-100 text-green-900' : 'bg-amber-100 text-amber-900'}`}>
          {s ? (s.overall === 'operational' ? 'All systems operational' : `Some systems are ${s.overall}`) : 'Loading…'}
        </p>
      </header>
      <section aria-labelledby="components">
        <h2 id="components" className="mb-2 font-medium">Components</h2>
        <ul className="divide-y rounded-md border">
          {(s?.components ?? []).map((c: Any) => <ComponentRow key={c.key} c={c} />)}
        </ul>
      </section>
      {(s?.maintenance ?? []).length > 0 && (
        <section><h2 className="mb-2 font-medium">Scheduled maintenance</h2>
          <ul className="text-sm">{s.maintenance.map((m: Any, i: number) => <li key={i}>{dt(m.starts_at)} – {dt(m.ends_at)}: {m.reason}</li>)}</ul>
        </section>
      )}
      <section><h2 className="mb-2 font-medium">Incidents</h2>
        {(s?.incidents ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No recent incidents.</p> : (
          <ul className="space-y-3">{s.incidents.map((i: Any) => (
            <li key={i.id} className="text-sm"><div className="font-medium">{i.title} — {i.state}</div>
              <ol className="ml-5 list-disc text-muted-foreground">{(i.updates ?? []).map((u: Any, n: number) => <li key={n}>{dt(u.at)} · {u.message}</li>)}</ol></li>
          ))}</ul>
        )}
      </section>
      <footer className="text-xs text-muted-foreground"><a className="underline" href="/api/v1/public/status/feed.rss">RSS feed</a> · updated {dt(s?.generated_at)}</footer>
    </main>
  );
}

function ComponentRow({ c }: { c: Any }) {
  const h = useQ(['uptime', c.key], () => oa.history(c.key, 90));
  const days: Any[] = [...rows(h.data)].reverse();
  return (
    <li className="p-3 text-sm">
      <div className="flex justify-between"><span>{c.key}</span><span>{c.state}</span></div>
      <div className="mt-2 flex gap-px" aria-label={`${c.key} uptime, last 90 days`}>
        {days.map((d: Any) => (
          <span key={d.date} title={`${d.date}: ${d.uptime_pct ?? 'no data'}%`}
            className={`h-6 flex-1 rounded-sm ${d.uptime_pct == null ? 'bg-muted' : d.uptime_pct >= 99.5 ? 'bg-green-500' : d.uptime_pct >= 95 ? 'bg-amber-400' : 'bg-red-500'}`} />
        ))}
      </div>
    </li>
  );
}
