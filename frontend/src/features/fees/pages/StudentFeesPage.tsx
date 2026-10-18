import { useEffect, useState } from 'react';
import { CreditCard, Download, Landmark, QrCode } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { localDate } from '@/features/hr/types';
import { SimpleTable } from '@/features/hr/components/shared';
import { useWards } from '@/features/students/hooks';
import { feesApi, noDuesApi, openBlob, scholarshipsApi } from '../api';
import { useFeesMutation, useMyApplications, useMyDues, useMyNoDues, useMyReceipts, useMyRefunds, useSchemes, useWardDues } from '../hooks';
import { INVOICE_VARIANT, NO_DUES_PURPOSES, inr, toPaise, type Dues, type Invoice, type UpiQr } from '../types';

const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));

/** Mock checkout: in development the order is signed through `/_dev/fees/sign` (no real gateway keys anywhere). */
async function payOnline(invoice: Invoice) {
  const order = (await feesApi.initiate({ invoice_ids: [invoice.id] })).data;
  if (order.gateway !== 'mock') {
    toast.info(`Continue in the ${order.gateway} checkout (order ${order.order_id}).`);
    return;
  }
  const paymentId = `pay_mock_${Date.now()}`;
  const sig = (await feesApi.devSign({ order_id: order.order_id, payment_id: paymentId })).data.signature ?? '';
  const out = (await feesApi.verify({ order_id: order.order_id, payment_id: paymentId, signature: sig })).data;
  toast.success(`Paid — receipt ${out.receipt_numbers.join(', ')}`);
}

function DuesCards({ dues, canPay }: { dues: Dues | undefined; canPay: boolean }) {
  const [upi, setUpi] = useState<UpiQr | null>(null);
  const [declare, setDeclare] = useState<Invoice | null>(null);
  const [form, setForm] = useState({ amount: '', utr: '', bank: '', mode: 'neft', paid_on: localDate() });
  const pay = useFeesMutation((i: Invoice) => payOnline(i));
  const doDeclare = useFeesMutation(() => feesApi.declare({ invoice_id: declare!.id, amount_paise: toPaise(form.amount), mode: form.mode, utr: form.utr, bank: form.bank || null, paid_on: form.paid_on }));
  const open = (dues?.invoices ?? []).filter((i) => ['pending', 'partial', 'overdue'].includes(i.status));
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total due</p><p className="text-xl font-semibold">{inr(dues?.total_due)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Overdue</p><p className="text-xl font-semibold text-destructive">{inr(dues?.overdue)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Next due</p><p className="text-xl font-semibold">{dues?.next_due ?? '—'}</p></CardContent></Card>
      </div>
      {(dues?.invoices ?? []).map((i) => (
        <Card key={i.id}>
          <CardContent className="space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-medium">{i.description ?? i.invoice_number} <span className="text-xs text-muted-foreground">{i.invoice_number}</span></p>
              <Badge variant={INVOICE_VARIANT[i.status] ?? 'secondary'}>{i.status}</Badge>
            </div>
            <SimpleTable head={['Item', 'Due', 'Amount']} rows={i.items.map((it) => [it.description, it.due_date ?? '—', inr(it.amount_paise + it.tax_paise)])} />
            <p className="text-sm">Paid {inr(i.paid_paise)} · Discount {inr(i.discount_paise)} · Fine {inr(i.fine_paise)} · <strong>Balance {inr(i.balance_paise)}</strong></p>
            {canPay && open.includes(i) && i.balance_paise > 0 && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => pay.mutate(i, { onError: fail })}><CreditCard className="h-4 w-4" /> Pay {inr(i.balance_paise)}</Button>
                <Button size="sm" variant="outline" onClick={() => feesApi.upiQr({ invoice_id: i.id }).then((r) => setUpi(r.data)).catch(fail)}><QrCode className="h-4 w-4" /> UPI QR</Button>
                <Button size="sm" variant="outline" onClick={() => { setDeclare(i); setForm({ ...form, amount: String(i.balance_paise / 100) }); }}><Landmark className="h-4 w-4" /> I paid by NEFT / challan</Button>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
      {!dues?.invoices.length && <p className="text-sm text-muted-foreground">No invoices yet.</p>}
      <Modal open={!!upi} onOpenChange={(o) => !o && setUpi(null)} title="Scan to pay">
        {upi && (
          <div className="space-y-2 text-center">
            {upi.qr_png ? <img src={upi.qr_png} alt="UPI QR" className="mx-auto h-56 w-56" /> : <code className="break-all text-xs">{upi.upi_uri}</code>}
            <p className="text-sm">{inr(upi.amount)} to {upi.vpa} · ref {upi.ref}</p>
            <a className="text-sm underline" href={upi.upi_uri}>Open in a UPI app</a>
          </div>
        )}
      </Modal>
      <Modal open={!!declare} onOpenChange={(o) => !o && setDeclare(null)} title="Declare an offline payment"
        footer={<Button disabled={!form.utr || !form.amount} onClick={() => doDeclare.mutate(undefined, { onSuccess: () => { toast.success('Declared — accounts will reconcile it with the bank statement'); setDeclare(null); }, onError: fail })}>Submit</Button>}>
        <div className="space-y-2">
          <Select value={form.mode} options={['neft', 'challan', 'dd', 'cheque'].map((m) => ({ value: m, label: m.toUpperCase() }))} onChange={(e) => setForm({ ...form, mode: e.target.value })} />
          <Input placeholder="Amount ₹" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <Input placeholder="UTR / reference" value={form.utr} onChange={(e) => setForm({ ...form, utr: e.target.value })} />
          <Input placeholder="Bank" value={form.bank} onChange={(e) => setForm({ ...form, bank: e.target.value })} />
          <Input type="date" value={form.paid_on} onChange={(e) => setForm({ ...form, paid_on: e.target.value })} />
        </div>
      </Modal>
    </div>
  );
}

function ReceiptsTab() {
  const list = useMyReceipts();
  return (
    <SimpleTable
      head={['Receipt', 'Date', 'Mode', 'Amount', 'Status', '']}
      rows={(list.data?.data ?? []).map((p) => [
        p.receipt_number,
        p.payment_date,
        p.payment_mode,
        inr(p.amount_paise),
        <StatusBadge key="s" status={p.status} />,
        <Button key="d" size="sm" variant="outline" onClick={() => feesApi.receiptPdf(p.id).then((b) => openBlob(b, `${p.receipt_number.replace(/\//g, '-')}.pdf`)).catch(fail)}><Download className="h-3 w-3" /> PDF</Button>,
      ])}
      empty="No receipts yet."
    />
  );
}

function ScholarshipsTab() {
  const schemes = useSchemes(true);
  const mine = useMyApplications();
  const [income, setIncome] = useState('');
  const apply = useFeesMutation((id: string) => scholarshipsApi.apply(id, { income_paise: income ? toPaise(income) : null, documents: [] }));
  return (
    <div className="space-y-3">
      <Input className="w-56" placeholder="Annual family income ₹" value={income} onChange={(e) => setIncome(e.target.value)} />
      <SimpleTable
        head={['Scheme', 'Provider', 'Amount', 'Closes', '']}
        rows={(schemes.data?.data ?? []).map((s) => [
          s.name,
          s.provider,
          inr(s.amount_paise),
          s.applications_close ?? '—',
          <Button key="a" size="sm" onClick={() => apply.mutate(s.id, { onSuccess: () => toast.success('Applied'), onError: fail })}>Apply</Button>,
        ])}
        empty="No open schemes."
      />
      <h3 className="font-medium">My applications</h3>
      <SimpleTable head={['Scheme', 'Status', 'Sanctioned', 'Disbursed']} rows={(mine.data?.data ?? []).map((a) => [a.scholarship_name, <StatusBadge key="s" status={a.status} />, a.sanctioned_paise ? inr(a.sanctioned_paise) : '—', a.disbursed_at ? new Date(a.disbursed_at).toLocaleDateString() : '—'])} empty="None yet." />
    </div>
  );
}

function RefundsTab() {
  const list = useMyRefunds();
  return <SimpleTable head={['Invoice', 'Amount', 'Reason', 'Status', 'Reference']} rows={(list.data?.data ?? []).map((r) => [r.invoice_number, inr(r.amount_paise), r.reason, <StatusBadge key="s" status={r.status} />, r.reference_no ?? '—'])} empty="No refunds." />;
}

function NoDuesTab() {
  const list = useMyNoDues();
  const [purpose, setPurpose] = useState<string>('graduation');
  const create = useFeesMutation(() => noDuesApi.create({ purpose }));
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Select className="w-44" value={purpose} options={NO_DUES_PURPOSES.map((p) => ({ value: p, label: p.replace('_', ' ') }))} onChange={(e) => setPurpose(e.target.value)} />
        <Button onClick={() => create.mutate(undefined, { onSuccess: () => toast.success('Requested'), onError: fail })}>Request no-dues</Button>
      </div>
      {(list.data?.data ?? []).map((r) => (
        <Card key={r.id}>
          <CardContent className="space-y-2 p-4">
            <p className="font-medium">{r.purpose} · <StatusBadge status={r.status} /> {r.certificate_number && <span className="text-xs">certificate {r.certificate_number}</span>}</p>
            <div className="flex flex-wrap gap-2">
              {r.signoffs.map((s) => (
                <Badge key={s.id} variant={s.status === 'cleared' ? 'success' : s.status === 'dues_pending' ? 'destructive' : 'secondary'}>
                  {s.department_key}{s.dues_paise > 0 ? ` · ${inr(s.dues_paise)}` : ''}
                </Badge>
              ))}
            </div>
            {r.status === 'cleared' && <Button size="sm" variant="outline" onClick={() => noDuesApi.certificate(r.id).then((b) => openBlob(b)).catch(fail)}>Certificate</Button>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function StudentFeesPage() {
  useTitle('My fees');
  const dues = useMyDues();
  return (
    <div className="space-y-4">
      <PageHeader title="Fees" description="Dues by invoice / instalment, online or UPI payment, offline declaration, receipts, scholarships, refunds, no-dues." />
      <Tabs defaultValue="dues">
        <TabsList>
          <TabsTrigger value="dues">Dues</TabsTrigger>
          <TabsTrigger value="receipts">Receipts</TabsTrigger>
          <TabsTrigger value="scholarships">Scholarships</TabsTrigger>
          <TabsTrigger value="refunds">Refunds</TabsTrigger>
          <TabsTrigger value="no-dues">No-dues</TabsTrigger>
        </TabsList>
        <TabsContent value="dues">{dues.error ? <p className="text-sm text-muted-foreground">{getApiError(dues.error)}</p> : <DuesCards dues={dues.data?.data} canPay />}</TabsContent>
        <TabsContent value="receipts"><ReceiptsTab /></TabsContent>
        <TabsContent value="scholarships"><ScholarshipsTab /></TabsContent>
        <TabsContent value="refunds"><RefundsTab /></TabsContent>
        <TabsContent value="no-dues"><NoDuesTab /></TabsContent>
      </Tabs>
    </div>
  );
}

export function ParentFeesPage() {
  useTitle('Ward fees');
  const wardList = useWards().data?.data;
  const wards = wardList ?? [];
  const [ward, setWard] = useState<string>();
  useEffect(() => {
    if (!ward && wardList?.[0]) setWard(wardList[0].student_id);
  }, [ward, wardList]);
  const dues = useWardDues(ward);
  return (
    <div className="space-y-4">
      <PageHeader title="Fees" description="Pay your ward's dues online or by UPI." />
      <Select className="w-64" value={ward ?? ''} options={wards.map((w) => ({ value: w.student_id, label: `${w.name} (${w.registration_number})` }))} onChange={(e) => setWard(e.target.value)} />
      {dues.error ? <p className="text-sm text-muted-foreground">{getApiError(dues.error)}</p> : <DuesCards dues={dues.data?.data} canPay />}
    </div>
  );
}
