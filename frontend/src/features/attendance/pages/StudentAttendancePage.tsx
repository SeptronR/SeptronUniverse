import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MapPin, QrCode } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { useWards } from '@/features/students/hooks';
import { attendanceApi } from '../api';
import { useAttendanceMutation, useHistory, useMyCondonations, useMyEligibility, useMySummary, useOds } from '../hooks';
import { BAND_VARIANT, CONDONATION_REASONS, DECISION_VARIANT, OD_REASONS, hhmm, type SummaryRow } from '../types';

const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const BAND_STROKE: Record<string, string> = {
  eligible: 'stroke-status-approved',
  condonable: 'stroke-status-pending',
  not_eligible: 'stroke-status-rejected',
  condoned: 'stroke-brand-500',
};

export function Ring({ pct, band, size = 88 }: { pct: number; band: string; size?: number }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox="0 0 80 80" role="img" aria-label={`${pct.toFixed(1)} percent`}>
      <circle cx="40" cy="40" r={r} strokeWidth="8" className="fill-none stroke-muted" />
      <circle
        cx="40"
        cy="40"
        r={r}
        strokeWidth="8"
        strokeLinecap="round"
        className={`fill-none ${BAND_STROKE[band] ?? 'stroke-primary'}`}
        strokeDasharray={`${(Math.min(100, pct) / 100) * c} ${c}`}
        transform="rotate(-90 40 40)"
      />
      <text x="40" y="45" textAnchor="middle" className="fill-foreground text-[15px] font-semibold">
        {pct.toFixed(0)}%
      </text>
    </svg>
  );
}

function Calculator({ r }: { r: SummaryRow }) {
  if (r.eligibility === 'condoned') return <p className="text-xs text-muted-foreground">Condoned for this term.</p>;
  if (r.sessions_needed_for_threshold > 0)
    return (
      <p className="text-xs">
        Attend the next <strong>{r.sessions_needed_for_threshold}</strong> session(s) to reach {r.min_pct}%.
      </p>
    );
  return (
    <p className="text-xs">
      You can miss <strong>{r.sessions_can_miss}</strong> session(s) and stay at or above {r.min_pct}%.
    </p>
  );
}

function CheckinDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [token, setToken] = useState('');
  const scan = useAttendanceMutation(() => attendanceApi.qrCheckin(token.trim()));
  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="QR check-in"
      description="Scan the code on the projector with the mobile app, or type the code shown under it."
      footer={<Button disabled={token.trim().length < 8} onClick={() => scan.mutate(undefined, { onSuccess: (r) => { toast.success(r.data.duplicate ? 'Already checked in' : `Marked ${r.data.status} — ${r.data.course_code ?? ''}`); onClose(); }, onError: fail })}>Check in</Button>}
    >
      <Input aria-label="QR code" placeholder="Code" value={token} onChange={(e) => setToken(e.target.value)} />
    </Modal>
  );
}

function OdForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [f, setF] = useState({ from_date: '', to_date: '', reason_type: 'sports', reason: '' });
  const [file, setFile] = useState<File>();
  const apply = useAttendanceMutation(async () => {
    const r = await attendanceApi.applyOd({ ...f, reason: f.reason || null });
    if (file) await attendanceApi.odDocument(r.data.id, file);
    return r;
  });
  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Apply for on duty"
      footer={<Button disabled={!f.from_date || !f.to_date} onClick={() => apply.mutate(undefined, { onSuccess: () => { toast.success('Submitted'); onClose(); }, onError: fail })}>Submit</Button>}
    >
      <div className="grid grid-cols-2 gap-2">
        <label className="text-sm">From<Input type="date" value={f.from_date} onChange={(e) => setF({ ...f, from_date: e.target.value })} /></label>
        <label className="text-sm">To<Input type="date" value={f.to_date} onChange={(e) => setF({ ...f, to_date: e.target.value })} /></label>
      </div>
      <Select className="mt-2" aria-label="Reason type" options={OD_REASONS.map((r) => ({ value: r, label: r }))} value={f.reason_type} onChange={(e) => setF({ ...f, reason_type: e.target.value })} />
      <Textarea className="mt-2" aria-label="Details" placeholder="Details" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
      <input className="mt-2 text-sm" type="file" aria-label="Supporting document" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0])} />
    </Modal>
  );
}

function CondonationForm({ row, onClose }: { row?: SummaryRow; onClose: () => void }) {
  const [f, setF] = useState({ reason_type: 'medical', reason: '' });
  const [file, setFile] = useState<File>();
  const req = useAttendanceMutation(async () => {
    const r = await attendanceApi.requestCondonation({ offering_id: row?.offering_id, ...f, reason: f.reason || null });
    if (file) await attendanceApi.condonationDocument(r.data.id, file);
    return r;
  });
  return (
    <Modal
      open={!!row}
      onOpenChange={(o) => !o && onClose()}
      title={`Request condonation — ${row?.course_code ?? ''} (${row?.pct.toFixed(1)}%)`}
      footer={<Button onClick={() => req.mutate(undefined, { onSuccess: () => { toast.success('Requested'); onClose(); }, onError: fail })}>Submit</Button>}
    >
      <Select aria-label="Reason type" options={CONDONATION_REASONS.map((r) => ({ value: r, label: r }))} value={f.reason_type} onChange={(e) => setF({ ...f, reason_type: e.target.value })} />
      <Textarea className="mt-2" aria-label="Details" placeholder="Details" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
      <input className="mt-2 text-sm" type="file" aria-label="Supporting document" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0])} />
    </Modal>
  );
}

/** /student/attendance (self) and /parent/attendance (ward picker, read-only). */
export function StudentAttendancePage({ parent = false }: { parent?: boolean }) {
  useTitle('Attendance');
  const [search, setSearch] = useSearchParams();
  const wards = useWards();
  const ward = parent ? (search.get('ward') ?? wards.data?.data[0]?.student_id) : undefined;
  const ready = !parent || !!ward;
  const me = useMySummary({ ward_id: ward }, ready);
  const [offering, setOffering] = useState<string>();
  const history = useHistory({ ward_id: ward, offering_id: offering }, ready);
  const elig = useMyEligibility({ ward_id: ward }, ready);
  const ods = useOds({ scope: 'mine', page_size: 20 });
  const conds = useMyCondonations(!parent);
  const [qr, setQr] = useState(false);
  const [odOpen, setOdOpen] = useState(false);
  const [condFor, setCondFor] = useState<SummaryRow>();
  const data = me.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader
        title={parent ? 'Ward attendance' : 'My attendance'}
        description={data ? `Overall ${data.overall_pct.toFixed(1)}% (credit-weighted, ${data.attendance_mode.replace('_', ' ')})` : undefined}
        actions={
          parent ? (
            <Select
              className="w-56"
              aria-label="Ward"
              options={(wards.data?.data ?? []).map((w) => ({ value: w.student_id, label: w.name ?? w.student_id }))}
              value={ward ?? ''}
              onChange={(e) => setSearch({ ward: e.target.value })}
            />
          ) : (
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setQr(true)}><QrCode className="h-4 w-4" /> QR check-in</Button>
              <Button variant="outline" onClick={() => setOdOpen(true)}><MapPin className="h-4 w-4" /> Apply for OD</Button>
            </div>
          )
        }
      />
      {me.error && <p className="text-sm text-muted-foreground">{getApiError(me.error)}</p>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(data?.per_offering ?? []).map((r) => (
          <Card key={r.offering_id} className={offering === r.offering_id ? 'border-primary' : undefined}>
            <CardContent className="flex gap-3 pt-4">
              <button type="button" onClick={() => setOffering(offering === r.offering_id ? undefined : r.offering_id)} aria-label={`Show ${r.course_code} history`}>
                <Ring pct={r.pct} band={r.eligibility} />
              </button>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="font-semibold">{r.course_code} <span className="font-normal text-muted-foreground">{r.course_title}</span></div>
                <div className="text-xs text-muted-foreground">
                  {r.present + r.late + r.on_duty} of {r.total_sessions - r.exempt} attended{r.on_duty ? ` (${r.on_duty} OD)` : ''}
                </div>
                <Badge variant={BAND_VARIANT[r.eligibility] ?? 'outline'}>{r.eligibility.replace('_', ' ')}</Badge>
                <Calculator r={r} />
                {!parent && r.eligibility === 'condonable' && (
                  <Button size="sm" variant="outline" onClick={() => setCondFor(r)}>Request condonation</Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <section className="space-y-2">
        <h3 className="font-medium">Session history{offering ? ' (filtered)' : ''}</h3>
        <SimpleTable
          head={['Date', 'Time', 'Course', 'Mark', 'Source']}
          rows={(history.data?.data ?? []).slice(0, 60).map((h) => [h.session_date, hhmm(h.start_time), h.course_code, <StatusBadge key="m" status={h.status ?? 'not marked'} />, h.source ?? '—'])}
          empty="No sessions yet."
        />
      </section>
      {(elig.data?.data ?? []).length > 0 && (
        <section className="space-y-2">
          <h3 className="font-medium">Examination eligibility</h3>
          <SimpleTable
            head={['Course', 'Attendance %', 'Decision', 'Reasons']}
            rows={(elig.data?.data ?? []).map((e) => [e.course_code, e.attendance_pct?.toFixed(1) ?? '—', <Badge key="d" variant={DECISION_VARIANT[e.decision] ?? 'outline'}>{e.decision}</Badge>, (e.reason_codes ?? []).join(', ')])}
          />
        </section>
      )}
      {!parent && (
        <section className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <h3 className="font-medium">My on-duty requests</h3>
            <SimpleTable
              head={['Dates', 'Reason', 'Status', '']}
              rows={(ods.data?.data ?? []).map((o) => [
                `${o.from_date} → ${o.to_date}`,
                o.reason_type,
                <StatusBadge key="s" status={o.status} />,
                ['requested', 'recommended'].includes(o.status) ? (
                  <Button key="w" size="sm" variant="outline" onClick={() => attendanceApi.odAction(o.id, 'withdraw').then(() => { toast.success('Withdrawn'); void ods.refetch(); }, fail)}>Withdraw</Button>
                ) : null,
              ])}
              empty="None."
            />
          </div>
          <div className="space-y-2">
            <h3 className="font-medium">My condonation requests</h3>
            <SimpleTable
              head={['Course', '%', 'Status', 'Fee']}
              rows={(conds.data?.data ?? []).map((c) => [c.course_code ?? 'aggregate', c.actual_pct.toFixed(1), <StatusBadge key="s" status={c.status} />, c.fee_paise ? `₹${(c.fee_paise / 100).toFixed(2)} ${c.fee_status ?? ''}` : '—'])}
              empty="None."
            />
          </div>
        </section>
      )}
      <CheckinDialog open={qr} onClose={() => setQr(false)} />
      <OdForm open={odOpen} onClose={() => setOdOpen(false)} />
      <CondonationForm row={condFor} onClose={() => setCondFor(undefined)} />
    </div>
  );
}

export function ParentAttendancePage() {
  return <StudentAttendancePage parent />;
}
