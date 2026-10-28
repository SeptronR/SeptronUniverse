import { useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Switch } from '@/components/ui/Switch';
import { d, dt, rows, Section, sel, Stat, useQ, useRun, useTitle, type Any } from '@/features/saas/components/kit';
import { privacyApi as pa } from '../api';

const input = 'h-9 w-full rounded-md border bg-background px-2 text-sm';
const TABS = ['dsrs', 'consents', 'notices', 'pii'] as const;

/** /admin/privacy — privacy officer: DSR board, consent report, notices, PII inventory + masking audit. */
export function PrivacyOfficePage() {
  useTitle('Privacy office');
  const [tab, setTab] = useState<(typeof TABS)[number]>('dsrs');
  return (
    <div className="space-y-4">
      <PageHeader title="Privacy office" description="DPDP Act 2023 — consents, notices and data-subject requests" />
      <div className="flex gap-2" role="tablist">
        {TABS.map((t) => (
          <Button key={t} role="tab" aria-selected={tab === t} size="sm" variant={tab === t ? 'default' : 'outline'} onClick={() => setTab(t)}>
            {{ dsrs: 'Requests', consents: 'Consents', notices: 'Notices', pii: 'PII inventory' }[t]}
          </Button>
        ))}
      </div>
      {tab === 'dsrs' && <DsrBoard />}
      {tab === 'consents' && <ConsentReport />}
      {tab === 'notices' && <Notices />}
      {tab === 'pii' && <PiiInventory />}
    </div>
  );
}

function DsrBoard() {
  const [status, setStatus] = useState('');
  const dash = useQ(['dsr-dash'], () => pa.dashboard());
  const list = useQ(['dsrs', status], () => pa.dsrs({ status: status || undefined }));
  const [open, setOpen] = useState<string | null>(null);
  const s: Any = dash.data?.data ?? {};
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Requests" value={s.total ?? '—'} />
        <Stat label="Overdue" value={s.overdue ?? 0} tone={s.overdue ? 'bad' : undefined} />
        <Stat label="In progress" value={s.by_status?.in_progress ?? 0} />
        <Stat label="On-time (closed)" value={s.sla_pct == null ? '—' : `${s.sla_pct}%`} />
      </div>
      <Section title="Requests" action={
        <select className={sel} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All open + closed</option>
          {['received', 'identity_pending', 'in_progress', 'extended', 'completed', 'rejected'].map((x) => <option key={x}>{x}</option>)}
        </select>
      }>
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted-foreground"><th>Type</th><th>Status</th><th>Received</th><th>Due</th><th /></tr></thead>
          <tbody>
            {rows(list.data).map((r: Any) => {
              const overdue = r.due_at && !['completed', 'rejected'].includes(r.status) && new Date(r.due_at) < new Date();
              return (
                <tr key={r.id} className="border-t">
                  <td className="py-1.5">{r.request_type}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{d(r.created_at)}</td>
                  <td className={overdue ? 'font-semibold text-red-600' : ''}>{d(r.due_at)}</td>
                  <td className="text-right"><Button size="sm" variant="ghost" onClick={() => setOpen(r.id)}>Open</Button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>
      {open && <DsrDetail id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function DsrDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQ(['dsr', id], () => pa.dsr(id));
  const run = useRun('Updated');
  const r: Any = q.data?.data;
  if (!r) return null;
  const act = (action: string, needReason = false) => {
    const reason = needReason ? window.prompt('Reason') ?? undefined : undefined;
    if (needReason && !reason) return;
    run.mutate(async () => { await pa.act(id, action, reason); await q.refetch(); });
  };
  return (
    <Section title={`Request · ${r.request_type}`} action={<Button size="sm" variant="ghost" onClick={onClose}>Close</Button>}>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 text-sm">
          <div>Status: <StatusBadge status={r.status} /> · due {d(r.due_at)} · identity {r.identity_verified ? 'verified' : 'not verified'}</div>
          {r.details && <p className="rounded bg-muted p-2">{r.details}</p>}
          {r.result_url && <a className="underline" href={r.result_url}>Export file</a>}
          {r.manifest_id && <div>Erasure manifest: <code>{r.manifest_id}</code></div>}
          <div className="flex flex-wrap gap-2 pt-2">
            {!r.identity_verified && <Button size="sm" variant="outline" onClick={() => act('verify_identity')}>Mark identity verified</Button>}
            {['received', 'identity_pending'].includes(r.status) && <Button size="sm" onClick={() => act('start')}>Start</Button>}
            {r.extensions < 1 && !['completed', 'rejected'].includes(r.status) && <Button size="sm" variant="outline" onClick={() => act('extend', true)}>Extend 30 days</Button>}
            {['in_progress', 'extended'].includes(r.status) && <Button size="sm" onClick={() => act('complete')}>Complete</Button>}
            {!['completed', 'rejected'].includes(r.status) && <Button size="sm" variant="ghost" onClick={() => act('reject', true)}>Reject</Button>}
          </div>
          {r.work_items?.length > 0 && (
            <ul className="divide-y pt-2">
              {r.work_items.map((w: Any) => (
                <li key={w.n} className="flex items-center gap-2 py-1">
                  <span className="flex-1">{w.table}.{w.field} → {w.new_value} <span className="text-xs text-muted-foreground">({w.owner_role})</span></span>
                  <StatusBadge status={w.status} />
                  {w.status !== 'done' && <Button size="sm" variant="ghost" onClick={() => run.mutate(async () => { await pa.workItemDone(id, w.n); await q.refetch(); })}>Done</Button>}
                </li>
              ))}
            </ul>
          )}
        </div>
        <ol className="space-y-1 border-l pl-3 text-sm">
          {(r.timeline ?? []).map((t: Any, i: number) => <li key={i}><span className="text-xs text-muted-foreground">{dt(t.at)}</span> · {t.event}{t.reason ? ` — ${t.reason}` : ''}</li>)}
        </ol>
      </div>
    </Section>
  );
}

function ConsentReport() {
  const [purpose, setPurpose] = useState('');
  const purposes = useQ(['purposes'], () => pa.purposes());
  const q = useQ(['consent-report', purpose], () => pa.report({ purpose: purpose || undefined }));
  const counts: Any = q.data?.data?.counts ?? {};
  return (
    <Section title="Consent report" action={
      <select className={sel} aria-label="Purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
        <option value="">All purposes</option>
        {rows(purposes.data).map((p: Any) => <option key={p.key} value={p.key}>{p.key}</option>)}
      </select>
    }>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-muted-foreground"><th>Purpose</th><th>Granted</th><th>Not granted</th></tr></thead>
        <tbody>{Object.entries(counts).map(([k, v]: Any) => <tr key={k} className="border-t"><td className="py-1">{k}</td><td>{v.granted}</td><td>{v.denied}</td></tr>)}</tbody>
      </table>
    </Section>
  );
}

function Notices() {
  const q = useQ(['notices'], () => pa.notices());
  const run = useRun('Saved');
  const [edit, setEdit] = useState<Record<string, string>>({});
  return (
    <Section title="Notices">
      <ul className="space-y-4">
        {rows(q.data).map((n: Any) => (
          <li key={n.key} className="space-y-1">
            <div className="flex items-center gap-2 text-sm"><span className="font-medium">{n.key.replaceAll('_', ' ')}</span><span className="text-xs text-muted-foreground">v{n.version}{n.draft ? ' · draft pending' : ''}</span></div>
            <textarea className={`${input} h-20 py-1`} aria-label={`${n.key} text`} value={edit[n.key] ?? n.draft?.texts?.en ?? n.texts?.en ?? ''} onChange={(e) => setEdit({ ...edit, [n.key]: e.target.value })} />
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { await pa.saveNotice(n.key, { en: edit[n.key] ?? n.texts?.en }); await q.refetch(); })}>Save draft</Button>
              <Button size="sm" disabled={!n.draft && !edit[n.key]} onClick={() => window.confirm('Publish a new version? Users will be asked to review it.') && run.mutate(async () => { if (edit[n.key]) await pa.saveNotice(n.key, { en: edit[n.key] }); await pa.publishNotice(n.key); await q.refetch(); })}>Publish</Button>
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function PiiInventory() {
  const inv = useQ(['pii'], () => pa.pii());
  const audit = useQ(['masking'], () => pa.maskingLatest());
  const run = useRun('Audit finished');
  const a: Any = audit.data?.data ?? {};
  return (
    <>
      <Section title="Masking audit" action={<Button size="sm" variant="outline" onClick={() => run.mutate(async () => { await pa.maskingAudit(); await audit.refetch(); })}>Run audit</Button>}>
        <p className="text-sm">{a.ok == null ? 'Not run yet' : a.ok ? `OK — ${a.checked} identifier / financial fields masked` : `${a.issues.length} unmasked field(s)`}</p>
        <ul className="text-xs">{(a.issues ?? []).map((i: Any) => <li key={i.schema_field}><code>{i.schema_field}</code> ({i.cls})</li>)}</ul>
      </Section>
      <Section title={`PII inventory (${rows(inv.data).length} fields)`}>
        <table className="w-full text-xs">
          <thead><tr className="text-left text-muted-foreground"><th>Table</th><th>Column</th><th>Class</th><th>Masking</th><th>Retention</th><th>Basis</th></tr></thead>
          <tbody>{rows(inv.data).map((f: Any) => <tr key={`${f.table}.${f.column}`} className="border-t"><td>{f.table}</td><td>{f.column}</td><td>{f.cls}</td><td>{f.masking}</td><td>{f.retention_class}</td><td>{f.legal_basis}</td></tr>)}</tbody>
        </table>
      </Section>
    </>
  );
}

/** /admin/security/posture — posture controls, MFA enforcement, scans, VAPT gate, ISO readiness. */
export function SecurityPosturePage() {
  useTitle('Security posture');
  const posture = useQ(['posture'], () => pa.posture());
  const mfa = useQ(['mfa-enf'], () => pa.mfa());
  const scans = useQ(['scans'], () => pa.scans());
  const vapt = useQ(['vapt'], () => pa.vapt());
  const iso = useQ(['iso'], () => pa.iso());
  const run = useRun('Done');
  const p: Any = posture.data?.data ?? {};
  const m: Any = mfa.data?.data ?? {};
  const v: Any = vapt.data?.data ?? {};
  const i: Any = iso.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Security posture" description={p.checked_at ? `Checked ${dt(p.checked_at)}` : 'Not checked yet'}
        actions={<Button size="sm" onClick={() => run.mutate(async () => { await pa.postureCheck(); await posture.refetch(); })}>Re-check</Button>} />
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Score" value={p.score ?? '—'} tone={p.score != null && p.score < 80 ? 'warn' : undefined} />
        <Stat label="Users missing MFA" value={(m.users_missing ?? []).length} tone={(m.users_missing ?? []).length ? 'bad' : undefined} />
        <Stat label="VAPT gate" value={v.gate ?? '—'} tone={v.gate === 'blocked' ? 'bad' : undefined} />
        <Stat label="ISO controls implemented" value={i.controls_total ? `${i.implemented}/${i.controls_total}` : '—'} />
      </div>
      <Section title="Controls">
        <ul className="divide-y text-sm">
          {(p.items ?? []).map((x: Any) => (
            <li key={x.control} className="flex items-center gap-3 py-1.5">
              <StatusBadge status={x.status === 'pass' ? 'active' : x.status === 'warn' ? 'pending' : 'failed'} />
              <span className="w-48 font-medium">{x.control.replaceAll('_', ' ')}</span>
              <span className="flex-1 text-muted-foreground">{x.detail}</span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="MFA enforcement" action={<Button size="sm" variant="outline" onClick={() => { const g = window.prompt('Grace period (days)', '3'); if (g) run.mutate(async () => { await pa.enforceMfa(Number(g)); await mfa.refetch(); }); }}>Enforce</Button>}>
        <p className="text-sm text-muted-foreground">Required roles: {(m.required_roles ?? []).join(', ')}{m.grace_until ? ` · grace until ${dt(m.grace_until)}` : ''}</p>
        <ul className="text-sm">{(m.users_missing ?? []).slice(0, 50).map((u: Any) => <li key={u.user_id}>{u.user} — {u.roles.join(', ')}</li>)}</ul>
      </Section>
      <Section title="Scans">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted-foreground"><th>Tool</th><th>High</th><th>Medium</th><th>Low</th><th>Run</th></tr></thead>
          <tbody>{rows(scans.data).map((s: Any) => <tr key={s.tool} className="border-t"><td className="py-1">{s.report_url ? <a className="underline" href={s.report_url}>{s.tool}</a> : s.tool}</td><td>{s.high}</td><td>{s.medium}</td><td>{s.low}</td><td>{dt(s.run_at)}</td></tr>)}</tbody>
        </table>
      </Section>
      <Section title="VAPT findings">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted-foreground"><th>Id</th><th>Severity</th><th>Title</th><th>Status</th><th>Retest</th></tr></thead>
          <tbody>{(v.findings ?? []).map((f: Any) => <tr key={f.id} className="border-t"><td className="py-1">{f.id}</td><td>{f.severity}</td><td>{f.title}</td><td><StatusBadge status={f.status} /></td><td>{f.retest || '—'}</td></tr>)}</tbody>
        </table>
      </Section>
    </div>
  );
}

const SUITES = ['static', 'golden', 'visibility', 'immutability', 'api_all', 'api_round_0', 'api_round_1', 'api_round_2', 'api_round_3', 'api_round_4', 'api_round_5'];

/** /admin/qa — run verification suites (non-production), golden diffs, access matrix, load results. */
export function QaPage() {
  useTitle('QA');
  const runs = useQ(['qa-runs'], () => pa.runs(), true, 10000);
  const matrix = useQ(['qa-matrix'], () => pa.matrix());
  const load = useQ(['qa-load'], () => pa.loadResults());
  const run = useRun('Queued');
  const [suite, setSuite] = useState('static');
  const [golden, setGolden] = useState<Any>(null);
  const mx: Any = matrix.data?.data ?? {};
  return (
    <div className="space-y-4">
      <PageHeader title="Quality assurance" description="Verification suites run as jobs; never against production" />
      <Section title="Run">
        <div className="flex flex-wrap gap-2">
          <select className={sel} aria-label="Suite" value={suite} onChange={(e) => setSuite(e.target.value)}>{SUITES.map((s) => <option key={s}>{s}</option>)}</select>
          <Button size="sm" onClick={() => run.mutate(() => pa.runSuite(suite))}>Run suite</Button>
          <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { const r: Any = await pa.golden(); setGolden(r.data); })}>Run golden datasets</Button>
        </div>
        {golden && <p className="mt-2 text-sm">Golden: {golden.passed}/{golden.total} pass{golden.failed.length ? ` — ${golden.failed.map((f: Any) => f.name).join('; ')}` : ''}</p>}
      </Section>
      <Section title="Runs">
        <ul className="divide-y text-sm">
          {rows(runs.data).map((r: Any) => (
            <li key={r.id} className="flex items-center gap-2 py-1.5">
              <span className="w-40 text-xs text-muted-foreground">{dt(r.created_at)}</span>
              <span className="flex-1">{r.params?.suite}</span>
              {r.result?.failed != null && <span className="text-xs">{r.result.failed} failed / {r.result.total}</span>}
              <StatusBadge status={r.status} />
            </li>
          ))}
        </ul>
      </Section>
      <Section title={`Access matrix — ${mx.routes ?? '…'} routes × ${mx.roles ?? '…'} roles`}>
        <p className="text-sm">{(mx.diff_vs_docs ?? []).length ? `${mx.diff_vs_docs.length} unexpected grant(s)` : 'No unexpected grants'}</p>
        <ul className="text-xs">{(mx.diff_vs_docs ?? []).slice(0, 50).map((x: string) => <li key={x}>{x}</li>)}</ul>
      </Section>
      <Section title="Load thresholds">
        <pre className="overflow-auto text-xs">{JSON.stringify(load.data?.data ?? {}, null, 1)}</pre>
      </Section>
    </div>
  );
}

/** /profile/privacy — my consents, my data requests (raise, verify identity), wards for guardians. */
export function MyPrivacyPage() {
  useTitle('My privacy');
  const banner = useQ(['consent-banner'], () => pa.banner());
  const mine = useQ(['my-dsrs'], () => pa.myDsrs());
  const wards = useQ(['wards'], () => pa.wards());
  const run = useRun('Saved');
  const [type, setType] = useState('export');
  const b: Any = banner.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="My privacy" description="Your consents and data requests under the DPDP Act, 2023" />
      {b && (
        <Section title="Consents">
          <ul className="space-y-2">
            {b.purposes.map((p: Any) => (
              <li key={p.key} className="flex items-start gap-3 text-sm">
                <Switch checked={p.mandatory || Boolean(b.current?.[p.key])} disabled={p.mandatory || b.is_minor} aria-label={p.key}
                  onCheckedChange={(v) => run.mutate(async () => { await pa.bulk({ [p.key]: v }, b.notice_version); await banner.refetch(); })} />
                <div><div className="font-medium">{p.key.replaceAll('_', ' ')}</div><div className="text-muted-foreground">{p.texts?.en}</div></div>
              </li>
            ))}
          </ul>
        </Section>
      )}
      <Section title="My data requests" action={
        <div className="flex gap-2">
          <select className={sel} aria-label="Request type" value={type} onChange={(e) => setType(e.target.value)}>
            {['access', 'export', 'correction', 'erasure'].map((t) => <option key={t}>{t}</option>)}
          </select>
          <Button size="sm" onClick={() => run.mutate(async () => { await pa.createDsr(type, window.prompt('Details (optional)') ?? undefined); await mine.refetch(); })}>Raise request</Button>
        </div>
      }>
        <ul className="divide-y text-sm">
          {rows(mine.data).map((r: Any) => (
            <li key={r.id} className="flex items-center gap-2 py-1.5">
              <span className="flex-1">{r.request_type} · due {d(r.due_at)}</span>
              <StatusBadge status={r.status} />
              {!r.identity_verified && !['completed', 'rejected'].includes(r.status) && (
                <Button size="sm" variant="outline" onClick={() => { const otp = window.prompt('Verification code from the notification'); if (otp) run.mutate(async () => { await pa.identity(r.id, otp); await mine.refetch(); }); }}>Verify identity</Button>
              )}
              {r.result_url && <a className="underline" href={r.result_url}>Download</a>}
            </li>
          ))}
        </ul>
      </Section>
      {rows(wards.data).length > 0 && (
        <Section title="My wards">
          <ul className="space-y-3 text-sm">
            {rows(wards.data).map((w: Any) => (
              <li key={w.student_id}>
                <div className="font-medium">{w.name}{w.is_minor && <span className="ml-2 text-xs text-muted-foreground">minor — you record the optional consents</span>}</div>
                {w.is_minor && b && (
                  <div className="mt-1 flex flex-wrap gap-3">
                    {b.purposes.filter((p: Any) => !p.mandatory).map((p: Any) => (
                      <label key={p.key} className="flex items-center gap-1">
                        <Switch checked={Boolean(w.consents?.[p.key])} aria-label={`${w.name} ${p.key}`}
                          onCheckedChange={(v) => run.mutate(async () => { await pa.bulk({ [p.key]: v }, undefined, w.student_id); await wards.refetch(); })} />
                        {p.key.replaceAll('_', ' ')}
                      </label>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
