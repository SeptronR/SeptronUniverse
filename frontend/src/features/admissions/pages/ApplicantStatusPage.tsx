import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { admissionsApi } from '../api';
import { useAdmissionsMutation, useMyApplication, useMyTimeline } from '../hooks';
import { label, rupees } from '../types';
import { Timeline } from './ApplicantDetailPage';

const DECISIONS: { action: string; text: string; help: string }[] = [
  { action: 'accept', text: 'Accept', help: 'Take this seat and pay the admission fee.' },
  { action: 'float', text: 'Float', help: 'Keep this seat but stay in the next round for a higher preference.' },
  { action: 'freeze', text: 'Freeze', help: 'Keep this seat and leave counselling.' },
  { action: 'decline', text: 'Decline', help: 'Give up the seat.' },
];

/** /apply (+ /apply/:cycle/status) — the applicant portal: status, timeline, document resubmission, payments,
 * allotment decisions (accept / float / freeze / decline) and withdrawal. */
export default function ApplicantStatusPage() {
  const me = useMyApplication();
  const tl = useMyTimeline();
  const allot = useQuery({ queryKey: ['admissions', 'me', 'allotment'], queryFn: admissionsApi.myAllotment, retry: false });
  const [withdrawing, setWithdrawing] = useState(false);
  const [reason, setReason] = useState('');
  const decide = useAdmissionsMutation((v: { id: string; action: string }) => admissionsApi.decide(v.id, v.action));
  const pay = useAdmissionsMutation((purpose: 'application' | 'admission') => admissionsApi.pay(purpose));
  const up = useAdmissionsMutation((v: { t: string; f: File }) => admissionsApi.myDocument(v.t, v.f));
  const withdraw = useAdmissionsMutation(() => admissionsApi.withdrawMe(reason));
  useEffect(() => {
    document.title = 'My application';
  }, []);
  const run = async (p: Promise<unknown>, ok: string) => {
    try {
      await p;
      toast.success(ok);
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  if (me.isError) return <p className="p-4 text-sm">{getApiError(me.error)} <Link className="underline" to="/admissions">See open admissions</Link></p>;
  const a = me.data?.data;
  if (!a) return <p className="p-4 text-sm text-muted-foreground">Loading…</p>;
  const al = allot.data?.data;
  const decidable = al && ['allotted', 'float', 'freeze'].includes(al.status);
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-lg">
            {a.cycle_name} <StatusBadge status={a.status} />
          </CardTitle>
          <p className="text-sm text-muted-foreground">Application <span className="font-mono">{a.application_number}</span> · {a.name}</p>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>Preferences: {a.preferences.map((p) => p.program_code).join(' › ') || '—'}</p>
          {a.status === 'draft' && a.cycle_slug && <Link className="font-medium text-primary underline" to={`/apply/${a.cycle_slug}`}>Continue your application</Link>}
          {Object.entries(a.payments).filter(([k]) => k !== 'refund').map(([k, p]) => (
            <div key={k} className="flex flex-wrap items-center gap-2">
              {label(k)} fee {rupees(p.amount_paise)} <StatusBadge status={p.status} />
              {p.status === 'pending' && <Button size="sm" disabled={pay.isPending} onClick={() => run(pay.mutateAsync(k as 'application' | 'admission'), 'Payment received (test mode)')}>Pay now</Button>}
            </div>
          ))}
          {a.payments.refund && <p>Refund: {rupees(a.payments.refund.amount_paise)} · {label(a.payments.refund.status)} ({a.payments.refund.policy})</p>}
        </CardContent>
      </Card>

      {al && (
        <Card className={decidable ? 'border-primary' : ''}>
          <CardHeader><CardTitle className="text-base">Seat allotment — round {al.round_number}</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p><b>{al.program_code}</b> — {al.program_name} · {al.quota} / {al.category} · preference {al.priority ?? '—'} · <StatusBadge status={al.status} /></p>
            {al.reporting_deadline && <p className="text-muted-foreground">Decide by {new Date(al.reporting_deadline).toLocaleString()}</p>}
            {al.payment && <p>Admission fee {rupees(al.payment.amount_paise)} <StatusBadge status={al.payment.status} /></p>}
            {decidable && (
              <div className="grid gap-2 sm:grid-cols-2">
                {DECISIONS.filter((d) => !(d.action === 'float' && al.status !== 'allotted')).map((d) => (
                  <Button key={d.action} variant={d.action === 'accept' ? 'default' : d.action === 'decline' ? 'outline' : 'secondary'} title={d.help} disabled={decide.isPending}
                    onClick={() => run(decide.mutateAsync({ id: al.id, action: d.action }), `${d.text} recorded`)}>
                    {d.text}
                  </Button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {a.documents.some((d) => d.status === 'rejected' || d.status === 'resubmit') && (
        <Card>
          <CardHeader><CardTitle className="text-base">Documents to resubmit</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {a.documents.filter((d) => d.status === 'rejected' || d.status === 'resubmit').map((d) => (
              <div key={d.doc_type} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="flex-1">{label(d.doc_type)} — {d.remarks}</span>
                <Input type="file" accept="image/*,application/pdf" capture="environment" aria-label={`Resubmit ${d.doc_type}`} className="w-60" onChange={(e) => { const f = e.target.files?.[0]; if (f) run(up.mutateAsync({ t: d.doc_type, f }), 'Resubmitted'); }} />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">Timeline</CardTitle></CardHeader>
        <CardContent><Timeline entries={tl.data?.data ?? []} /></CardContent>
      </Card>

      {!['admitted', 'withdrawn', 'rejected', 'declined', 'lapsed'].includes(a.status) && (
        <Button variant="outline" onClick={() => setWithdrawing(true)}>Withdraw application</Button>
      )}
      <Modal open={withdrawing} onOpenChange={setWithdrawing} title="Withdraw application" description="A refund is computed by the institution's policy and approved by the office."
        footer={<Button variant="destructive" disabled={reason.length < 3} onClick={async () => { await run(withdraw.mutateAsync(undefined), 'Application withdrawn'); setWithdrawing(false); }}>Withdraw</Button>}>
        <Textarea rows={3} placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </div>
  );
}
