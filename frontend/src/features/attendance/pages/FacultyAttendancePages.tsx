import { useEffect, useMemo, useState } from 'react';
import { CheckCheck, Download, Lock, Pencil, QrCode, Save } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { localDate } from '@/features/hr/types';
import { useOfferings } from '@/features/registration/hooks';
import { TermPicker } from '@/features/registration/pages/OfferingsPage';
import { useSessions } from '@/features/timetable/hooks';
import type { Session } from '@/features/timetable/types';
import { cn } from '@/utils/cn';
import { attendanceApi } from '../api';
import { useAttendanceMutation, useSheet, useSummaries } from '../hooks';
import { BAND_VARIANT, CYCLE, MARK_SHORT, hhmm, type Mark, type RosterRow } from '../types';

const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));

const MARK_CLASS: Record<string, string> = {
  present: 'bg-status-approved/15 text-status-approved border-status-approved/40',
  late: 'bg-status-pending/15 text-status-pending border-status-pending/40',
  absent: 'bg-status-rejected/15 text-status-rejected border-status-rejected/40',
  on_duty: 'bg-brand-100 text-brand-800 border-brand-300 dark:bg-brand-900/40 dark:text-brand-200',
  leave: 'bg-muted text-foreground',
  medical: 'bg-muted text-foreground',
  exempt: 'bg-muted text-muted-foreground',
};

// ---- QR projector mode ------------------------------------------------------------------------------------------------
function QrMode({ sessionId, open, onClose }: { sessionId: string; open: boolean; onClose: () => void }) {
  const [qr, setQr] = useState<{ token: string; png?: string | null; ttl: number; checked: number } | null>(null);
  const sheet = useSheet(open ? sessionId : undefined, open ? 5000 : undefined);
  useEffect(() => {
    if (!open) return undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const issue = () =>
      attendanceApi
        .issueQr(sessionId)
        .then((r) => {
          setQr({ token: r.data.token, png: r.data.png_base64, ttl: r.data.ttl_seconds, checked: r.data.checked_in });
          timer = setTimeout(issue, Math.max(15, r.data.ttl_seconds - 10) * 1000);
        })
        .catch((e) => {
          fail(e);
          onClose();
        });
    void issue();
    return () => timer && clearTimeout(timer);
  }, [open, sessionId, onClose]);
  const present = sheet.data?.data.roster?.filter((r) => r.source === 'qr').length ?? qr?.checked ?? 0;
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Scan to mark attendance" size="xl">
      <div className="flex flex-col items-center gap-4 py-4">
        {qr?.png ? (
          <img alt="Session QR" className="h-80 w-80" src={`data:image/png;base64,${qr.png}`} />
        ) : (
          <code className="rounded border p-4 text-lg">{qr?.token ?? '…'}</code>
        )}
        <p className="text-3xl font-semibold" aria-live="polite">
          {present} / {sheet.data?.data.counts?.roster ?? '—'} checked in
        </p>
        <p className="text-sm text-muted-foreground">The code rotates every {qr?.ttl ?? 120} s. Students scan it from the app.</p>
      </div>
    </Modal>
  );
}

// ---- marking grid ------------------------------------------------------------------------------------------------------------
export function MarkingGrid({ sessionId }: { sessionId: string }) {
  const sheet = useSheet(sessionId);
  const data = sheet.data?.data;
  const [marks, setMarks] = useState<Record<string, Mark>>({});
  const [restAs, setRestAs] = useState<'' | 'present' | 'absent'>('present');
  const [qrOpen, setQrOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [reason, setReason] = useState('');
  useEffect(() => {
    const init: Record<string, Mark> = {};
    for (const r of data?.roster ?? []) {
      const s = (r.status ?? r.prefill) as Mark | null | undefined;
      if (s) init[r.student_program_enrollment_id] = s;
    }
    setMarks(init);
  }, [data]);
  const finalized = data?.attendance_status === 'finalized';
  const editable = (data?.can_mark && !finalized) || (finalized && data?.can_edit_finalized);
  const changed = useMemo(
    () => (data?.roster ?? []).filter((r) => marks[r.student_program_enrollment_id] && marks[r.student_program_enrollment_id] !== r.status),
    [data, marks],
  );
  const save = useAttendanceMutation(() =>
    attendanceApi.mark(sessionId, {
      marks: changed.map((r) => ({ student_program_enrollment_id: r.student_program_enrollment_id, status: marks[r.student_program_enrollment_id] })),
      mark_rest_as: restAs || null,
      source: 'manual',
    }),
  );
  const finalize = useAttendanceMutation(() => attendanceApi.finalize(sessionId));
  const edit = useAttendanceMutation(() =>
    attendanceApi.editFinalized(sessionId, {
      marks: changed.map((r) => ({ student_program_enrollment_id: r.student_program_enrollment_id, status: marks[r.student_program_enrollment_id] })),
      reason,
    }),
  );
  const cycle = (r: RosterRow) => {
    if (!editable) return;
    const cur = marks[r.student_program_enrollment_id];
    const next = CYCLE[(CYCLE.indexOf(cur ?? 'absent') + 1) % CYCLE.length];
    setMarks({ ...marks, [r.student_program_enrollment_id]: next });
  };
  const allPresent = () =>
    setMarks(Object.fromEntries((data?.roster ?? []).map((r) => [r.student_program_enrollment_id, (r.prefill as Mark) ?? 'present'])));
  if (sheet.error) return <p className="text-sm text-muted-foreground">{getApiError(sheet.error)}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading roster…</p>;
  const counts = Object.values(marks).reduce<Record<string, number>>((a, m) => ({ ...a, [m]: (a[m] ?? 0) + 1 }), {});
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">
          {data.course_code} {data.section_name && `· ${data.section_name}`} · {data.session_date} {hhmm(data.start_time)}–{hhmm(data.end_time)}
          {data.room_code && ` · ${data.room_code}`}
        </h3>
        <StatusBadge status={data.attendance_status} />
        <span className="ml-auto text-sm text-muted-foreground">
          {Object.entries(counts).map(([k, v]) => `${MARK_SHORT[k] ?? k} ${v}`).join(' · ')} · {data.counts?.roster ?? 0} on roster
        </span>
      </div>
      {editable && (
        <div className="flex flex-wrap gap-2">
          {!finalized && (
            <Button variant="outline" onClick={allPresent}>
              <CheckCheck className="h-4 w-4" /> All present
            </Button>
          )}
          {!finalized && (
            <Select
              className="w-48"
              aria-label="Mark the rest as"
              options={[
                { value: 'present', label: 'Rest: present' },
                { value: 'absent', label: 'Rest: absent' },
                { value: '', label: 'Leave the rest' },
              ]}
              value={restAs}
              onChange={(e) => setRestAs(e.target.value as '' | 'present' | 'absent')}
            />
          )}
          {!finalized && (
            <Button onClick={() => save.mutate(undefined, { onSuccess: (r) => toast.success(`Saved: ${r.data.created} new, ${r.data.updated} changed${(r.data.rejected ?? []).length ? `, ${(r.data.rejected ?? []).length} rejected` : ''}`), onError: fail })}>
              <Save className="h-4 w-4" /> Save
            </Button>
          )}
          {!finalized && (
            <Button variant="outline" onClick={() => setQrOpen(true)}>
              <QrCode className="h-4 w-4" /> QR mode
            </Button>
          )}
          {!finalized && data.attendance_status === 'taken' && (
            <Button variant="outline" onClick={() => window.confirm('Finalize? Later edits need the HOD with a reason.') && finalize.mutate(undefined, { onSuccess: () => toast.success('Finalized'), onError: fail })}>
              <Lock className="h-4 w-4" /> Finalize
            </Button>
          )}
          {finalized && (
            <Button disabled={!changed.length} onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4" /> Save corrections ({changed.length})
            </Button>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5" role="grid" aria-label="Attendance roster">
        {(data.roster ?? []).map((r) => {
          const m = marks[r.student_program_enrollment_id];
          return (
            <button
              key={r.student_program_enrollment_id}
              type="button"
              role="gridcell"
              aria-label={`${r.name}: ${m ?? 'not marked'}`}
              disabled={!editable}
              onClick={() => cycle(r)}
              className={cn('flex min-h-16 items-center gap-2 rounded-md border p-2 text-left text-sm transition-colors', m ? MARK_CLASS[m] : 'bg-card')}
            >
              {r.photo_url ? <img src={r.photo_url} alt="" className="h-9 w-9 rounded-full object-cover" /> : <span className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-xs">{r.roll_number ?? '#'}</span>}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{r.name}</span>
                <span className="block truncate text-xs opacity-80">
                  {r.roll_number ?? r.registration_number}
                  {r.prefill === 'on_duty' && ' · OD'}
                  {r.source && r.source !== 'manual' && ` · ${r.source}`}
                </span>
              </span>
              <span className="text-base font-semibold">{m ? MARK_SHORT[m] : '–'}</span>
            </button>
          );
        })}
      </div>
      <QrMode sessionId={sessionId} open={qrOpen} onClose={() => setQrOpen(false)} />
      <Modal
        open={editOpen}
        onOpenChange={setEditOpen}
        title="Edit finalized attendance"
        description="Every changed mark is audited with the old and new status."
        footer={
          <Button disabled={reason.trim().length < 3} onClick={() => edit.mutate(undefined, { onSuccess: () => { toast.success('Corrected'); setEditOpen(false); setReason(''); }, onError: fail })}>
            Save {changed.length} correction(s)
          </Button>
        }
      >
        <Textarea aria-label="Reason" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </div>
  );
}

// ---- /faculty/attendance --------------------------------------------------------------------------------------------------------
function SessionCard({ s, active, onClick }: { s: Session; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={cn('rounded-md border p-3 text-left text-sm', active ? 'border-primary bg-brand-50 dark:bg-slate-800' : 'bg-card')}>
      <div className="font-semibold">
        {hhmm(s.start_time)}–{hhmm(s.end_time)} · {s.course_code}
      </div>
      <div className="text-muted-foreground">{[s.section_name, s.room_code, s.substituted && 'substitution'].filter(Boolean).join(' · ')}</div>
      <div className="mt-1 flex gap-1">
        <StatusBadge status={s.status} />
        <StatusBadge status={s.attendance_status} />
      </div>
    </button>
  );
}

export function FacultyAttendancePage() {
  useTitle('Attendance');
  const [day, setDay] = useState(localDate());
  const [active, setActive] = useState<string>();
  const sessions = useSessions({ date: day, scope: 'mine', page_size: 50 });
  const rows = useMemo(() => (sessions.data?.data ?? []).filter((s) => s.status !== 'cancelled' && s.status !== 'rescheduled'), [sessions.data]);
  useEffect(() => {
    if (rows.length && !rows.some((s) => s.id === active)) setActive(rows[0].id);
  }, [rows, active]);
  return (
    <div className="space-y-4">
      <PageHeader title="Attendance" description="Pick a class, tap to cycle a student's mark, then save. Finalize locks the session." />
      <Input type="date" className="w-44" aria-label="Date" value={day} onChange={(e) => setDay(e.target.value)} />
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No classes on {day}.</p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {rows.map((s) => (
            <SessionCard key={s.id} s={s} active={s.id === active} onClick={() => setActive(s.id)} />
          ))}
        </div>
      )}
      {active && (
        <Card>
          <CardContent className="pt-4">
            <MarkingGrid key={active} sessionId={active} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---- /faculty/attendance/summary --------------------------------------------------------------------------------------------------
export function FacultySummaryPage() {
  useTitle('Attendance summary');
  const [term, setTerm] = useState('');
  const [offering, setOffering] = useState('');
  const offerings = useOfferings({ term_id: term || undefined, scope: 'mine', page_size: 200 });
  const list = useSummaries({ offering_id: offering || undefined, scope: 'mine', page_size: 200 }, !!offering);
  const exportReg = useAttendanceMutation(() => attendanceApi.exportRegister({ offering_id: offering }));
  return (
    <div className="space-y-4">
      <PageHeader
        title="Attendance summary"
        description="Per-student percentage, band and the sessions needed to reach the minimum."
        actions={
          <Button variant="outline" disabled={!offering} onClick={() => exportReg.mutate(undefined, { onSuccess: () => toast.success('Register export queued — see Jobs'), onError: fail })}>
            <Download className="h-4 w-4" /> Export register
          </Button>
        }
      />
      <div className="flex flex-wrap gap-2">
        <TermPicker value={term} onChange={setTerm} />
        <Select
          className="w-64"
          aria-label="Offering"
          placeholder="Choose an offering"
          options={(offerings.data?.data ?? []).map((o) => ({ value: o.id, label: `${o.course_code} ${o.section_code}` }))}
          value={offering}
          onChange={(e) => setOffering(e.target.value)}
        />
      </div>
      <SummaryTable rows={list.data?.data ?? []} />
    </div>
  );
}

export function SummaryTable({ rows }: { rows: import('../types').SummaryRow[] }) {
  return (
    <SimpleTable
      head={['Student', 'Course', 'Sessions', 'P / L / OD / A', '%', 'Band', 'Needed', 'Can miss']}
      rows={rows.map((r) => [
        <span key="n">
          {r.student_name} <span className="text-xs text-muted-foreground">{r.registration_number}</span>
        </span>,
        r.course_code,
        r.total_sessions,
        `${r.present} / ${r.late} / ${r.on_duty} / ${r.absent}`,
        <span key="p" className="font-semibold">{r.pct.toFixed(1)}</span>,
        <Badge key="b" variant={BAND_VARIANT[r.eligibility] ?? 'outline'}>{r.eligibility.replace('_', ' ')}</Badge>,
        r.sessions_needed_for_threshold || '—',
        r.sessions_can_miss,
      ])}
      empty="Choose an offering."
    />
  );
}
