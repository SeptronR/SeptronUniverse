import { useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { toast } from '@/components/ui/Toaster';
import { dt, Err, rows, Section, sel, Stat, useQ, useRun, useTitle, type Any } from '@/features/saas/components/kit';
import { integrationsApi as ia } from '../api';

const input = 'h-9 w-full rounded-md border bg-background px-2 text-sm';

/** /admin/integrations — capability matrix, connections with test / enable / disable (Prompts/41 §41.9). */
export function IntegrationsHubPage() {
  useTitle('Integrations');
  const caps = useQ(['int-caps'], () => ia.capabilities());
  const providers = useQ(['int-providers'], () => ia.providers());
  const run = useRun('Done');
  const [form, setForm] = useState({ capability: '', provider: 'mock', label: '' });
  const list = rows(caps.data);
  if (caps.isLoading) return <Err q={caps} />;
  const capList = rows(providers.data);
  const chosen = capList.find((c: Any) => c.capability === form.capability);
  return (
    <div className="space-y-4">
      <PageHeader title="Integrations" description="Connect payment, messaging, SSO, government and other providers" />
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Capabilities" value={list.length} />
        <Stat label="Connected" value={list.filter((c: Any) => c.status === 'active').length} />
        <Stat label="With errors" value={list.filter((c: Any) => c.last_error).length} tone="warn" />
      </div>
      <Section title="Add a connection">
        <div className="flex flex-wrap gap-2">
          <select className={sel} aria-label="Capability" value={form.capability} onChange={(e) => setForm({ ...form, capability: e.target.value })}>
            <option value="">Capability…</option>
            {capList.map((c: Any) => <option key={c.capability} value={c.capability}>{c.name ?? c.capability}</option>)}
          </select>
          <select className={sel} aria-label="Provider" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
            {(chosen?.providers ?? [{ provider: 'mock' }]).map((p: Any) => <option key={p.provider} value={p.provider}>{p.name ?? p.provider}</option>)}
          </select>
          <input className={`${input} max-w-xs`} placeholder="Label" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          <Button size="sm" disabled={!form.capability} onClick={() => run.mutate(() => ia.createConnection({ ...form, config: {}, is_sandbox: true }))}>Add</Button>
        </div>
      </Section>
      <Section title="Capabilities">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted-foreground"><th>Capability</th><th>Provider</th><th>Status</th><th>Last error</th><th /></tr></thead>
          <tbody>
            {list.map((c: Any) => (
              <tr key={c.capability} className="border-t">
                <td className="py-1.5">{c.name}</td>
                <td>{c.provider ?? '—'}</td>
                <td><StatusBadge status={c.status} /></td>
                <td className="max-w-xs truncate text-xs text-muted-foreground">{c.last_error ?? ''}</td>
                <td className="space-x-1 text-right">
                  {c.connection_id && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { const r: Any = await ia.test(c.connection_id); toast[r.data.ok ? 'success' : 'error'](`${r.data.detail} · ${r.data.latency_ms} ms`); })}>Test</Button>
                      <Button size="sm" variant="ghost" onClick={() => run.mutate(() => ia.toggle(c.connection_id, c.status !== 'active'))}>{c.status === 'active' ? 'Disable' : 'Enable'}</Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

/** /admin/integrations/inbound — inbound provider webhook log with replay. */
export function InboundLogPage() {
  useTitle('Inbound webhooks');
  const q = useQ(['int-inbound'], () => ia.inbound());
  const run = useRun('Replayed');
  return (
    <div className="space-y-4">
      <PageHeader title="Inbound webhooks" description="Provider callbacks (payments, messaging) — signature-verified and idempotent" />
      <Section title="Recent">
        <ul className="divide-y text-sm">
          {rows(q.data).map((r: Any) => (
            <li key={r.id} className="flex items-center gap-2 py-1.5">
              <span className="w-40 text-xs text-muted-foreground">{dt(r.received_at)}</span>
              <span className="flex-1">{r.provider} · {r.event_type ?? '—'}</span>
              <StatusBadge status={r.error ? 'failed' : 'processed'} />
              <Button size="sm" variant="ghost" onClick={() => run.mutate(() => ia.replayInbound(r.id))}>Replay</Button>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

/** /admin/integrations/api-keys — scoped keys; the secret is shown once. */
export function ApiKeysPage() {
  useTitle('API keys');
  const q = useQ(['int-keys'], () => ia.apiKeys());
  const run = useRun('Saved');
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState('students:read');
  const [secret, setSecret] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <PageHeader title="API keys" description="Send as the X-API-Key header; scopes limit what a key can do" />
      {secret && (
        <Section title="Copy this secret now — it will not be shown again">
          <code className="block break-all rounded bg-muted p-2 text-xs">{secret}</code>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => setSecret(null)}>Done</Button>
        </Section>
      )}
      <Section title="Create">
        <div className="flex flex-wrap gap-2">
          <input className={`${input} max-w-xs`} placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <input className={`${input} max-w-md`} placeholder="Scopes (comma separated)" value={scopes} onChange={(e) => setScopes(e.target.value)} />
          <Button size="sm" disabled={name.length < 2} onClick={() => run.mutate(async () => { const r: Any = await ia.createKey({ name, scopes: scopes.split(',').map((s) => s.trim()).filter(Boolean) }); setSecret(r.data.secret); setName(''); })}>Create key</Button>
        </div>
      </Section>
      <Section title="Keys">
        <ul className="divide-y text-sm">
          {rows(q.data).map((k: Any) => (
            <li key={k.id} className="flex items-center gap-2 py-1.5">
              <span className="flex-1">{k.name} <code className="text-xs text-muted-foreground">{k.key_prefix}…</code></span>
              <span className="text-xs text-muted-foreground">{(k.scopes ?? []).join(', ')}</span>
              <span className="w-36 text-xs">used {dt(k.last_used_at)}</span>
              <StatusBadge status={k.is_active ? 'active' : 'revoked'} />
              {k.is_active && (
                <>
                  <Button size="sm" variant="ghost" onClick={() => run.mutate(async () => { const r: Any = await ia.rotateKey(k.id); setSecret(r.data.secret); })}>Rotate</Button>
                  <Button size="sm" variant="ghost" onClick={() => window.confirm('Revoke this key?') && run.mutate(() => ia.revokeKey(k.id))}>Revoke</Button>
                </>
              )}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

/** /admin/integrations/webhooks — subscriptions, deliveries, test and retry. */
export function WebhooksPage() {
  useTitle('Webhooks');
  const hooks = useQ(['int-hooks'], () => ia.webhooks());
  const deliveries = useQ(['int-deliveries'], () => ia.deliveries({ limit: 50 }));
  const run = useRun('Done');
  const [form, setForm] = useState({ name: '', url: 'https://', events: 'student.enrolled' });
  const [secret, setSecret] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <PageHeader title="Webhooks" description="HMAC-signed (X-Septron-Signature: t=…, v1=…) event deliveries with retries" />
      {secret && <Section title="Signing secret (shown once)"><code className="block break-all text-xs">{secret}</code></Section>}
      <Section title="Subscribe">
        <div className="flex flex-wrap gap-2">
          <input className={`${input} max-w-[12rem]`} placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className={`${input} max-w-sm`} placeholder="https://…" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          <input className={`${input} max-w-sm`} placeholder="Events" value={form.events} onChange={(e) => setForm({ ...form, events: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(async () => { const r: Any = await ia.createWebhook({ name: form.name, url: form.url, events: form.events.split(',').map((s) => s.trim()) }); setSecret(r.data.secret); })}>Add</Button>
        </div>
      </Section>
      <Section title="Subscriptions">
        <ul className="divide-y text-sm">
          {rows(hooks.data).map((w: Any) => (
            <li key={w.id} className="flex items-center gap-2 py-1.5">
              <span className="flex-1">{w.name} <span className="text-xs text-muted-foreground">{w.url}</span></span>
              <StatusBadge status={w.is_active ? 'active' : 'disabled'} />
              <Button size="sm" variant="ghost" onClick={() => run.mutate(() => ia.testWebhook(w.id))}>Test</Button>
              <Button size="sm" variant="ghost" onClick={() => run.mutate(async () => { const r: Any = await ia.rotateWebhook(w.id); setSecret(r.data.secret); })}>Rotate secret</Button>
              <Button size="sm" variant="ghost" onClick={() => window.confirm('Delete webhook?') && run.mutate(() => ia.deleteWebhook(w.id))}>Delete</Button>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Recent deliveries">
        <ul className="divide-y text-sm">
          {rows(deliveries.data).map((r: Any) => (
            <li key={r.id} className="flex items-center gap-2 py-1.5">
              <span className="w-40 text-xs text-muted-foreground">{dt(r.created_at)}</span>
              <span className="flex-1">{r.event_type}</span>
              <span className="text-xs">{r.response_code ?? '—'} · {r.attempts} attempt(s)</span>
              <StatusBadge status={r.status} />
              {r.status !== 'delivered' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => ia.retry([r.id]))}>Retry</Button>}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

/** /admin/integrations/dead-letters — outbox / webhook / notification dead letters. */
export function DeadLettersPage() {
  useTitle('Dead letters');
  const [kind, setKind] = useState('webhook');
  const q = useQ(['int-dead', kind], () => ia.deadLetters(kind));
  const run = useRun('Done');
  const items = rows(q.data);
  const ids = items.map((r: Any) => r.id);
  return (
    <div className="space-y-4">
      <PageHeader
        title="Dead letters"
        actions={
          <div className="flex gap-2">
            <select className={sel} aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              {['webhook', 'outbox', 'notification'].map((k) => <option key={k}>{k}</option>)}
            </select>
            <Button size="sm" disabled={!ids.length} onClick={() => run.mutate(() => ia.replayDead(kind, ids))}>Replay all</Button>
            <Button size="sm" variant="outline" disabled={!ids.length} onClick={() => { const r = window.prompt('Reason'); if (r) run.mutate(() => ia.discardDead(kind, ids, r)); }}>Discard all</Button>
          </div>
        }
      />
      <Section title={`${items.length} item(s)`}>
        <ul className="divide-y text-sm">
          {items.map((r: Any) => (
            <li key={r.id} className="flex gap-2 py-1.5"><span className="w-40 text-xs text-muted-foreground">{dt(r.created_at)}</span><span className="flex-1">{r.event_type ?? r.kind}</span><span className="max-w-sm truncate text-xs">{r.error ?? ''}</span></li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

/** /admin/imports — migration toolkit: upload → auto-map → validate → apply → rollback, plus the cut-over workbook. */
export function ImportsPage() {
  useTitle('Data import');
  const templates = useQ(['imp-templates'], () => ia.templates());
  const list = useQ(['imp-list'], () => ia.imports(), true, 10000);
  const workbook = useQ(['imp-workbook'], () => ia.workbook());
  const run = useRun('Queued');
  const [entity, setEntity] = useState('students');
  const [fileUrl, setFileUrl] = useState('');
  return (
    <div className="space-y-4">
      <PageHeader title="Data import" description="Bring data from spreadsheets or a legacy system; every apply can be rolled back" actions={<Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.startWorkbook())}>Start cut-over workbook</Button>} />
      <Section title="New import">
        <div className="flex flex-wrap gap-2">
          <select className={sel} aria-label="Entity" value={entity} onChange={(e) => setEntity(e.target.value)}>
            {rows(templates.data).map((t: Any) => <option key={t.entity} value={t.entity}>{t.label}</option>)}
          </select>
          <input className={`${input} max-w-md`} placeholder="Uploaded file URL (CSV / XLSX)" value={fileUrl} onChange={(e) => setFileUrl(e.target.value)} />
          <a className="self-center text-sm underline" href={`/api/v1/imports/templates/${entity}/sample.xlsx`}>Sample file</a>
          <Button size="sm" disabled={!fileUrl} onClick={() => run.mutate(() => ia.createImport({ entity, file_url: fileUrl }))}>Upload</Button>
        </div>
      </Section>
      {rows(workbook.data).length > 0 && (
        <Section title="Cut-over workbook">
          <ol className="list-decimal pl-5 text-sm">{rows(workbook.data).map((s: Any) => <li key={s.order}>{s.label} — <StatusBadge status={s.status ?? 'pending'} /></li>)}</ol>
        </Section>
      )}
      <Section title="Imports">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted-foreground"><th>Entity</th><th>Status</th><th>Rows</th><th>Valid</th><th>Errors</th><th /></tr></thead>
          <tbody>
            {rows(list.data).map((r: Any) => (
              <tr key={r.id} className="border-t">
                <td className="py-1.5">{r.entity}</td>
                <td><StatusBadge status={r.status} /></td>
                <td>{r.total_rows ?? '—'}</td><td>{r.valid_rows ?? '—'}</td><td>{r.error_rows ?? '—'}</td>
                <td className="space-x-1 text-right">
                  {r.status === 'uploaded' && <Button size="sm" variant="outline" onClick={() => run.mutate(() => ia.validate(r.id))}>Validate</Button>}
                  {r.status === 'validated' && (
                    <>
                      {r.error_rows > 0 && <a className="text-xs underline" href={`/api/v1/imports/${r.id}/errors.xlsx`}>Errors</a>}
                      <Button size="sm" onClick={() => window.confirm(`Apply ${r.valid_rows} valid rows?`) && run.mutate(() => ia.apply(r.id, r.valid_rows))}>Apply</Button>
                    </>
                  )}
                  {r.status === 'applied' && <Button size="sm" variant="ghost" onClick={() => window.confirm('Roll back this import?') && run.mutate(() => ia.rollback(r.id))}>Roll back</Button>}
                  {['uploaded', 'validated', 'failed'].includes(r.status) && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => ia.deleteImport(r.id))}>Delete</Button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

/** /admin/exports — personal data export and full-tenant portability export. */
export function ExportsPage() {
  useTitle('Data export');
  const run = useRun('Export queued — you will be notified when it is ready');
  return (
    <div className="space-y-4">
      <PageHeader title="Data export" description="Data portability (DPDP Act) — files are delivered as expiring links" />
      <Section title="Exports">
        <div className="flex gap-2">
          <Button size="sm" onClick={() => run.mutate(() => ia.exportMe())}>Export my data</Button>
          <Button size="sm" variant="outline" onClick={() => window.confirm('Export all institution data?') && run.mutate(() => ia.exportTenant())}>Export institution</Button>
        </div>
      </Section>
    </div>
  );
}
