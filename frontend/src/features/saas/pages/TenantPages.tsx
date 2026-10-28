import { api } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { billingApi } from '../api';
import { d, Err, inr, rows, Section, Stat, useQ, useRun, useTitle, type Any } from '../components/kit';

/** /admin/billing — subscription card, invoices (pay / download), usage vs limits, plan comparison (Prompts/38 §38.9). */
export function TenantBillingPage() {
  useTitle('Billing');
  const sub = useQ(['bsub'], () => billingApi.subscription());
  const usage = useQ(['busage'], () => billingApi.usage());
  const plans = useQ(['bplans'], () => billingApi.plans());
  const run = useRun();
  const s: Any = sub.data?.data;
  const download = async (n: string) => {
    const r = await api.get(billingApi.pdfUrl(n), { responseType: 'blob' });
    const url = URL.createObjectURL(r.data as unknown as Blob);
    Object.assign(document.createElement('a'), { href: url, download: `${n.replace(/\//g, '-')}.pdf` }).click();
  };
  const pay = (n: string) =>
    run.mutate(async () => {
      const r = await billingApi.pay(n);
      const url = r.data?.order?.checkout?.url;
      toast.success(url ? 'Opening the checkout…' : 'Payment started');
      if (url) window.open(url, '_blank', 'noopener');
    });
  return (
    <div className="space-y-4">
      <PageHeader title="Billing" description="Your SeptronUniverse subscription, invoices and usage." actions={<Button size="sm" variant="outline" onClick={() => run.mutate(async () => { await billingApi.export(); toast.success('Export queued — the password arrives by e-mail'); })}>Export our data</Button>} />
      <Err q={sub} />
      {s && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Stat label="Plan" value={s.plan?.name ?? '—'} />
          <Stat label="Status" value={s.status} tone={['grace', 'expired', 'cancelled'].includes(s.status) ? 'bad' : undefined} />
          <Stat label="Renews / ends" value={d(s.ends_on)} />
          <Stat label="Grace until" value={d(s.grace_until)} />
        </div>
      )}
      {s && (
        <Section title="Usage vs limits">
          <SimpleTable head={['Metric', 'Used', 'Limit', '%']} rows={['students', 'staff', 'storage_gb', 'sms'].map((k) => [k, s.usage_vs_limits[k]?.used, s.usage_vs_limits[k]?.limit ?? '∞', s.usage_vs_limits[k]?.pct ?? '—'])} />
          <p className="text-xs text-muted-foreground">Plan-locked settings: {Object.entries(s.locked_settings ?? {}).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join(' · ') || '—'}</p>
        </Section>
      )}
      <Section title="Invoices">
        <SimpleTable head={['Number', 'Period', 'Total', 'Status', 'Due', '']} rows={(s?.invoices ?? []).map((i: Any) => [i.number, i.period, inr(i.total_paise), <StatusBadge key="s" status={i.status} />, d(i.due_on), <div key="a" className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => download(i.number)}>PDF</Button>{i.status !== 'paid' && <Button size="sm" onClick={() => pay(i.number)}>Pay</Button>}</div>])} />
      </Section>
      <Section title="Usage by month">
        <SimpleTable head={['Month', 'Students', 'SMS', 'WhatsApp', 'E-mails', 'API calls', 'Cost']} rows={(usage.data?.data?.months ?? []).slice().reverse().map((m: Any) => [m.period_month, m.active_students, m.sms_sent, m.whatsapp_sent, m.emails_sent, m.api_calls, inr(m.cost_paise)])} />
      </Section>
      <Section title="Compare plans">
        <SimpleTable head={['Plan', 'Monthly', 'Yearly', 'Students', 'Features', '']} rows={rows(plans.data).map((p) => [p.name, inr(p.prices.monthly), inr(p.prices.yearly), p.limits.students ?? '∞', p.enabled_features.length, p.code !== s?.plan?.code ? <Button key="u" size="sm" variant="outline" onClick={() => run.mutate(async () => { await billingApi.upgrade(p.code); toast.success('Request sent to the SeptronUniverse team'); })}>Request</Button> : 'current'])} />
      </Section>
    </div>
  );
}
