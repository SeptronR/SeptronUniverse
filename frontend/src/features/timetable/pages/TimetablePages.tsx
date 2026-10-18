import { useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { CalendarPlus, Copy, Download, Printer, Send, Trash2, Wand2 } from 'lucide-react';
import { getApiError, getApiErrorDetails } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { SimpleTable } from '@/features/hr/components/shared';
import { useOfferings } from '@/features/registration/hooks';
import { TermPicker } from '@/features/registration/pages/OfferingsPage';
import type { Offering } from '@/features/registration/types';
import { timetableApi } from '../api';
import {
  useBuildings,
  useCandidates,
  useMyWeek,
  useRooms,
  useSessions,
  useSlots,
  useSubstitutions,
  useTimetable,
  useTimetableMutation,
  useTimetables,
  useToday,
  useWeekly,
} from '../hooks';
import { DAYS, ROOM_TYPES, hhmm, type ConflictReport, type Entry, type Session, type Substitution, type WeeklyView } from '../types';

const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));

// ---- weekly grid -------------------------------------------------------------------------------------------------------
function EntryCell({ e, onClick }: { e: Entry; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className="mb-1 w-full rounded border bg-brand-50 p-1 text-left text-xs dark:bg-slate-800">
      <div className="font-semibold">
        {e.course_code} {e.session_type !== 'lecture' && <span className="font-normal">({e.session_type})</span>}
      </div>
      <div className="text-muted-foreground">{[e.staff_name, e.room_code, e.section_name].filter(Boolean).join(' · ')}</div>
      {(e.week_pattern !== 'all' || e.slot_span > 1) && (
        <div className="text-[10px] text-muted-foreground">{[e.week_pattern !== 'all' && `${e.week_pattern} weeks`, e.slot_span > 1 && `${e.slot_span} slots`].filter(Boolean).join(' · ')}</div>
      )}
    </button>
  );
}

/** Day × slot grid; ``onDrop`` receives a dragged offering id, ``onCell`` an empty-cell click. */
export function WeekGrid({
  view,
  onEntry,
  onCell,
  onDrop,
}: {
  view: WeeklyView | undefined;
  onEntry?: (e: Entry) => void;
  onCell?: (day: number, slotId: string) => void;
  onDrop?: (offeringId: string, day: number, slotId: string) => void;
}) {
  const days = view?.days ?? [];
  if (!view || days.length === 0) return <p className="text-sm text-muted-foreground">No timetable published.</p>;
  const slots = days[0].slots ?? [];
  return (
    <div className="overflow-x-auto rounded-md border print:overflow-visible">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-2 py-2 text-left">Day</th>
            {slots.map((s) => (
              <th key={s.slot_id} className="px-2 py-2 text-left">
                {s.name}
                <div className="font-normal normal-case">{hhmm(s.start_time)}–{hhmm(s.end_time)}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.day_of_week} className="border-t align-top">
              <td className="px-2 py-2 font-medium">
                {d.label}
                {d.date && <div className="text-xs text-muted-foreground">{d.date.slice(5)}</div>}
              </td>
              {(d.slots ?? []).map((s) => {
                const brk = s.slot_type === 'break' || s.slot_type === 'lunch';
                return (
                  <td
                    key={s.slot_id}
                    className={`min-w-[110px] px-1 py-1 ${brk ? 'bg-muted/40' : ''}`}
                    onDragOver={(ev) => onDrop && !brk && ev.preventDefault()}
                    onDrop={(ev) => {
                      const id = ev.dataTransfer.getData('text/offering');
                      if (id && onDrop) onDrop(id, d.day_of_week, s.slot_id);
                    }}
                    onClick={() => !brk && (s.entries ?? []).length === 0 && onCell?.(d.day_of_week, s.slot_id)}
                  >
                    {brk ? <span className="text-xs text-muted-foreground">{s.slot_type}</span> : (s.entries ?? []).map((e) => <EntryCell key={e.id} e={e} onClick={() => onEntry?.(e)} />)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Builds a WeeklyView from a draft's entries and its slot group (the editor grid). */
function draftView(entries: Entry[], slots: { id: string; name: string; start_time: string; end_time: string; slot_type: string }[]): WeeklyView {
  const days = [1, 2, 3, 4, 5, 6].map((dow) => ({
    day_of_week: dow,
    label: DAYS[dow],
    date: null,
    slots: slots.map((s) => ({
      slot_id: s.id,
      name: s.name,
      start_time: s.start_time,
      end_time: s.end_time,
      slot_type: s.slot_type,
      entries: entries.filter((e) => e.day_of_week === dow && e.time_slot_id === s.id),
    })),
  }));
  return { scope: 'draft', days, sessions: [] } as unknown as WeeklyView;
}

function ConflictBadges({ report }: { report: ConflictReport | null }) {
  if (!report) return null;
  const items = [...(report.room ?? []), ...(report.staff ?? []), ...(report.section ?? []), ...(report.capacity ?? []), ...(report.workload ?? [])];
  if (!items.length) return <Badge variant="success">No conflicts</Badge>;
  return (
    <div className="space-y-1">
      {items.map((c, i) => (
        <div key={i} className="text-xs">
          <Badge variant={['capacity', 'workload'].includes(c.kind) ? 'warning' : 'destructive'}>{c.kind}</Badge> {c.message}
          {c.course_code ? ` (${c.course_code})` : ''}
        </div>
      ))}
    </div>
  );
}

// ---- /admin/facilities/rooms ---------------------------------------------------------------------------------------------
const roomSchema = z
  .object({
    code: z.string().min(1).max(20),
    name: z.string().min(1).max(120),
    room_type: z.string(),
    building_id: z.string().optional(),
    capacity: z.coerce.number().int().min(0),
    exam_capacity: z.coerce.number().int().min(0).optional().or(z.literal('').transform(() => undefined)),
    features: z.string().optional(),
  })
  .refine((v) => v.exam_capacity == null || v.exam_capacity <= v.capacity, { message: 'Exam capacity cannot exceed capacity', path: ['exam_capacity'] });
type RoomForm = z.infer<typeof roomSchema>;

export function RoomsPage() {
  useTitle('Rooms & buildings');
  const { can } = usePermission();
  const write = can('timetable', 'update') || can('timetable', 'manage');
  const [type, setType] = useState('');
  const [building, setBuilding] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const buildings = useBuildings();
  const rooms = useRooms({ room_type: type || undefined, building_id: building || undefined, q: q || undefined, page, page_size: 50 });
  const [open, setOpen] = useState(false);
  const form = useForm<RoomForm>({ resolver: zodResolver(roomSchema), defaultValues: { room_type: 'classroom', capacity: 60 } });
  const create = useTimetableMutation((v: RoomForm) =>
    timetableApi.createRoom({
      ...v,
      building_id: v.building_id || null,
      exam_capacity: v.exam_capacity ?? null,
      features: (v.features ?? '').split(',').map((s) => s.trim()).filter(Boolean),
    }),
  );
  const del = useTimetableMutation((id: string) => timetableApi.deleteRoom(id));
  // availability finder
  const slots = useSlots({ slot_group: 'Default' });
  const [avDate, setAvDate] = useState(new Date().toISOString().slice(0, 10));
  const [avSlot, setAvSlot] = useState('');
  const [avail, setAvail] = useState<{ code: string; free: boolean; busy: string[] }[] | null>(null);
  const bOpts = (buildings.data?.data ?? []).map((b) => ({ value: b.id, label: `${b.code} — ${b.name} (${b.rooms_count})` }));
  const pg = rooms.data?.meta.pagination;
  return (
    <div className="space-y-4">
      <PageHeader title="Rooms & buildings" description="Rooms, labs and halls with capacity and features." actions={write && <Button onClick={() => setOpen(true)}>New room</Button>} />
      <div className="flex flex-wrap gap-2">
        <Select className="w-56" aria-label="Building" placeholder="All buildings" options={bOpts} value={building} onChange={(e) => setBuilding(e.target.value)} />
        <Select className="w-44" aria-label="Type" placeholder="All types" options={ROOM_TYPES.map((t) => ({ value: t, label: t }))} value={type} onChange={(e) => setType(e.target.value)} />
        <Input className="w-56" placeholder="Search code / name" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <SimpleTable
        head={['Code', 'Name', 'Building', 'Type', 'Capacity', 'Exam', 'Features', '']}
        rows={(rooms.data?.data ?? []).map((r) => [
          r.code,
          r.name,
          r.building_code ?? '—',
          r.room_type,
          r.capacity,
          r.exam_capacity ?? '—',
          (r.features ?? []).filter((f) => !f.startsWith('dept:')).join(', '),
          write ? (
            <Button key="d" size="sm" variant="ghost" onClick={() => del.mutate(r.id, { onSuccess: () => toast.success('Room deleted'), onError: fail })}>
              <Trash2 className="h-4 w-4" />
            </Button>
          ) : null,
        ])}
      />
      {pg && pg.total_pages > 1 && (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button>
          <span className="text-sm">{page} / {pg.total_pages}</span>
          <Button size="sm" variant="outline" disabled={page >= pg.total_pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
      <section className="space-y-2 rounded-md border p-3">
        <h3 className="font-medium">Availability finder</h3>
        <div className="flex flex-wrap gap-2">
          <Input type="date" className="w-44" value={avDate} onChange={(e) => setAvDate(e.target.value)} />
          <Select className="w-40" aria-label="Slot" placeholder="Slot" options={(slots.data?.data ?? []).filter((s) => s.slot_type !== 'break' && s.slot_type !== 'lunch').map((s) => ({ value: s.id, label: `${s.name} ${hhmm(s.start_time)}` }))} value={avSlot} onChange={(e) => setAvSlot(e.target.value)} />
          <Button
            variant="outline"
            disabled={!avSlot}
            onClick={() =>
              timetableApi
                .availability({ date: avDate, slot_id: avSlot, type: type || undefined })
                .then((r) => setAvail(r.data.map((a) => ({ code: a.room.code, free: a.free, busy: a.busy_with ?? [] }))))
                .catch(fail)
            }
          >
            Find
          </Button>
        </div>
        {avail && (
          <div className="flex flex-wrap gap-1">
            {avail.map((a) => (
              <Badge key={a.code} variant={a.free ? 'success' : 'outline'} title={a.busy.join(', ')}>{a.code}{a.free ? '' : ` · ${a.busy[0] ?? 'busy'}`}</Badge>
            ))}
          </div>
        )}
      </section>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="New room"
        footer={<Button onClick={form.handleSubmit((v) => create.mutate(v, { onSuccess: () => { toast.success('Room created'); setOpen(false); form.reset(); }, onError: fail }))}>Save</Button>}
      >
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Code" error={form.formState.errors.code?.message}><Input {...form.register('code')} /></FormField>
          <FormField label="Name" error={form.formState.errors.name?.message}><Input {...form.register('name')} /></FormField>
          <FormField label="Type"><Select options={ROOM_TYPES.map((t) => ({ value: t, label: t }))} {...form.register('room_type')} /></FormField>
          <FormField label="Building"><Select placeholder="—" options={bOpts} {...form.register('building_id')} /></FormField>
          <FormField label="Capacity" error={form.formState.errors.capacity?.message}><Input type="number" {...form.register('capacity')} /></FormField>
          <FormField label="Exam capacity" error={form.formState.errors.exam_capacity?.message}><Input type="number" {...form.register('exam_capacity')} /></FormField>
          <FormField label="Features (comma separated)"><Input {...form.register('features')} /></FormField>
        </div>
      </Modal>
    </div>
  );
}

// ---- /admin/timetable/slots ----------------------------------------------------------------------------------------------
export function SlotsPage() {
  useTitle('Time slots');
  const [group, setGroup] = useState('Default');
  const slots = useSlots({ slot_group: group });
  const [rows, setRows] = useState<{ name: string; start_time: string; end_time: string; slot_type: string }[]>([]);
  useEffect(() => {
    setRows((slots.data?.data ?? []).map((s) => ({ name: s.name, start_time: hhmm(s.start_time), end_time: hhmm(s.end_time), slot_type: s.slot_type })));
  }, [slots.data]);
  const save = useTimetableMutation(() => timetableApi.saveSlots({ slot_group: group, slots: rows }));
  const set = (i: number, k: string, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div className="space-y-4">
      <PageHeader title="Time slots" description="Ordered, non-overlapping periods of a slot group." actions={<Button onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Slot group saved'), onError: fail })}>Save group</Button>} />
      <Input className="w-56" value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Slot group" />
      <SimpleTable
        head={['Name', 'Start', 'End', 'Type', '']}
        rows={rows.map((r, i) => [
          <Input key="n" value={r.name} onChange={(e) => set(i, 'name', e.target.value)} />,
          <Input key="s" type="time" value={r.start_time} onChange={(e) => set(i, 'start_time', e.target.value)} />,
          <Input key="e" type="time" value={r.end_time} onChange={(e) => set(i, 'end_time', e.target.value)} />,
          <Select key="t" options={['lecture', 'lab', 'break', 'lunch'].map((t) => ({ value: t, label: t }))} value={r.slot_type} onChange={(e) => set(i, 'slot_type', e.target.value)} />,
          <Button key="x" size="sm" variant="ghost" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>,
        ])}
      />
      <Button variant="outline" onClick={() => setRows([...rows, { name: `P${rows.length + 1}`, start_time: '09:00', end_time: '09:50', slot_type: 'lecture' }])}>Add slot</Button>
    </div>
  );
}

// ---- /admin/timetable/:termId --------------------------------------------------------------------------------------------
export function TimetableEditorPage() {
  useTitle('Timetable');
  const { can } = usePermission();
  const params = useParams();
  const [term, setTerm] = useState(params.termId ?? '');
  const [scopeType, setScopeType] = useState('section');
  const [scopeId, setScopeId] = useState('');
  const [selected, setSelected] = useState('');
  const [mode, setMode] = useState<'editor' | 'faculty' | 'room'>('editor');
  const [viewId, setViewId] = useState('');
  const versions = useTimetables({ term_id: term || undefined, scope_type: scopeType, scope_id: scopeId || undefined, page_size: 100 });
  const tt = useTimetable(selected || undefined);
  const slots = useSlots({ slot_group: 'Default', college_id: tt.data?.data.college_id });
  const offerings = useOfferings({ term_id: term || undefined, page_size: 200 });
  const rooms = useRooms({ page_size: 200 });
  const [cell, setCell] = useState<{ day: number; slot: string; offering?: string } | null>(null);
  const [report, setReport] = useState<ConflictReport | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [effective, setEffective] = useState(new Date().toISOString().slice(0, 10));
  const draft = tt.data?.data;
  const editable = !!draft?.can_edit;
  const scopes = useMemo(() => {
    const seen = new Map<string, string>();
    for (const t of versions.data?.data ?? []) seen.set(t.scope_id, t.scope_label ?? t.scope_id);
    return [...seen].map(([value, label]) => ({ value, label }));
  }, [versions.data]);
  const palette = (offerings.data?.data ?? []).filter((o: Offering) => ['open', 'closed', 'in_progress'].includes(o.status));
  const add = useTimetableMutation((b: Record<string, unknown>) => timetableApi.addEntry(selected, b));
  const remove = useTimetableMutation((eid: string) => timetableApi.deleteEntry(selected, eid));
  const publish = useTimetableMutation(() => timetableApi.publish(selected, { effective_from: effective, regenerate_sessions: true }));
  const clone = useTimetableMutation(() => timetableApi.clone(selected));
  const auto = useTimetableMutation(() => timetableApi.autoGenerate(selected, false));
  const facultyView = useWeekly({ scope: mode, id: viewId }, mode !== 'editor' && !!viewId);
  const [form, setForm] = useState({ room_id: '', staff_id: '', week_pattern: 'all', slot_span: 1, session_type: 'lecture' });

  const tryEntry = async (offering: string, day: number, slot: string, apply: boolean) => {
    const off = palette.find((o) => o.id === offering);
    const body = {
      offering_id: offering,
      day_of_week: day,
      time_slot_id: slot,
      room_id: form.room_id || null,
      staff_id: form.staff_id || off?.faculty?.[0]?.staff_id || null,
      week_pattern: form.week_pattern,
      slot_span: Number(form.slot_span),
      session_type: form.session_type,
    };
    try {
      setReport((await timetableApi.check(selected, body)).data);
      if (apply) {
        const r = await add.mutateAsync(body);
        setReport(r.data.warnings);
        toast.success('Entry added');
        setCell(null);
      }
    } catch (e) {
      const details = getApiErrorDetails(e) as { conflicts?: ConflictReport };
      if (details.conflicts) setReport(details.conflicts);
      fail(e);
    }
  };
  const createDraft = useTimetableMutation(() => timetableApi.create({ term_id: term, scope_type: scopeType, scope_id: scopeId }));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Timetable"
        description="Versions per section / batch / department; drag offerings into the grid."
        actions={
          <div className="flex flex-wrap gap-2 print:hidden">
            <TermPicker value={term} onChange={setTerm} />
            <Button variant="outline" onClick={() => window.print()}><Printer className="h-4 w-4" /> Print</Button>
          </div>
        }
      />
      <div className="flex flex-wrap items-end gap-2 print:hidden">
        <Select className="w-36" aria-label="View" options={[{ value: 'editor', label: 'Editor' }, { value: 'faculty', label: 'Faculty view' }, { value: 'room', label: 'Room view' }]} value={mode} onChange={(e) => setMode(e.target.value as 'editor')} />
        {mode === 'editor' ? (
          <>
            <Select className="w-36" aria-label="Scope type" options={['section', 'batch', 'department'].map((s) => ({ value: s, label: s }))} value={scopeType} onChange={(e) => setScopeType(e.target.value)} />
            <Select className="w-56" aria-label="Scope" placeholder="All scopes" options={scopes} value={scopeId} onChange={(e) => setScopeId(e.target.value)} />
            <Input className="w-72" placeholder="…or paste a scope id for a new draft" value={scopeId} onChange={(e) => setScopeId(e.target.value)} />
            {(can('timetable', 'create') || can('timetable', 'manage')) && scopeId && (
              <Button variant="outline" onClick={() => createDraft.mutate(undefined, { onSuccess: (r) => setSelected(r.data.id), onError: fail })}>New draft</Button>
            )}
          </>
        ) : mode === 'room' ? (
          <Select className="w-56" aria-label="Room" placeholder="Room" options={(rooms.data?.data ?? []).map((r) => ({ value: r.id, label: r.code }))} value={viewId} onChange={(e) => setViewId(e.target.value)} />
        ) : (
          <Select
            className="w-64"
            aria-label="Faculty"
            placeholder="Faculty"
            options={[...new Map(palette.flatMap((o) => o.faculty ?? []).map((f) => [f.staff_id, { value: f.staff_id, label: f.name ?? f.staff_id }])).values()]}
            value={viewId}
            onChange={(e) => setViewId(e.target.value)}
          />
        )}
      </div>
      {mode !== 'editor' ? (
        <WeekGrid view={facultyView.data?.data} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <aside className="space-y-3 print:hidden">
            <h3 className="text-sm font-medium">Versions</h3>
            {(versions.data?.data ?? []).map((v) => (
              <button key={v.id} type="button" onClick={() => setSelected(v.id)} className={`block w-full rounded border p-2 text-left text-xs ${selected === v.id ? 'border-primary' : ''}`}>
                {v.scope_label} · v{v.version} <StatusBadge status={v.status} />
                <div className="text-muted-foreground">{v.entries_count} entries{v.effective_from ? ` · from ${v.effective_from}` : ''}</div>
              </button>
            ))}
            {editable && (
              <>
                <h3 className="pt-2 text-sm font-medium">Offerings (drag into a cell)</h3>
                <div className="max-h-80 space-y-1 overflow-y-auto">
                  {palette.map((o) => (
                    <div key={o.id} draggable onDragStart={(ev) => ev.dataTransfer.setData('text/offering', o.id)} className="cursor-grab rounded border p-1 text-xs">
                      <b>{o.course_code}</b> {o.section_code} · {(o.faculty ?? []).map((f) => f.name).join(', ') || 'no faculty'}
                    </div>
                  ))}
                </div>
                <div className="space-y-2 text-xs">
                  <Select aria-label="Room" placeholder="Room" options={(rooms.data?.data ?? []).map((r) => ({ value: r.id, label: `${r.code} (${r.capacity})` }))} value={form.room_id} onChange={(e) => setForm({ ...form, room_id: e.target.value })} />
                  <Select aria-label="Weeks" options={['all', 'odd', 'even'].map((w) => ({ value: w, label: `${w} weeks` }))} value={form.week_pattern} onChange={(e) => setForm({ ...form, week_pattern: e.target.value })} />
                  <Select aria-label="Span" options={[1, 2, 3].map((n) => ({ value: String(n), label: `${n} slot(s)` }))} value={String(form.slot_span)} onChange={(e) => setForm({ ...form, slot_span: Number(e.target.value) })} />
                  <Select aria-label="Type" options={['lecture', 'tutorial', 'lab', 'project'].map((w) => ({ value: w, label: w }))} value={form.session_type} onChange={(e) => setForm({ ...form, session_type: e.target.value })} />
                </div>
              </>
            )}
          </aside>
          <section className="space-y-3">
            {draft && (
              <div className="flex flex-wrap items-center gap-2 print:hidden">
                <span className="font-medium">{draft.scope_label} · v{draft.version}</span>
                <StatusBadge status={draft.status} />
                {editable && <Button size="sm" onClick={() => setPublishOpen(true)}><Send className="h-4 w-4" /> Publish</Button>}
                {editable && <Button size="sm" variant="outline" onClick={() => timetableApi.check(selected).then((r) => setReport(r.data)).catch(fail)}>Check conflicts</Button>}
                {editable && can('timetable', 'generate') && (
                  <Button size="sm" variant="outline" onClick={() => auto.mutate(undefined, { onSuccess: () => toast.success('Auto-generation queued'), onError: fail })}><Wand2 className="h-4 w-4" /> Auto-generate</Button>
                )}
                {draft.status !== 'draft' && (can('timetable', 'create') || can('timetable', 'manage')) && (
                  <Button size="sm" variant="outline" onClick={() => clone.mutate(undefined, { onSuccess: (r) => setSelected(r.data.id), onError: fail })}><Copy className="h-4 w-4" /> New version</Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => timetableApi.exportCsv(selected).then(() => toast.success('Export queued — see Background jobs')).catch(fail)}><Download className="h-4 w-4" /></Button>
              </div>
            )}
            <ConflictBadges report={report} />
            {draft && (
              <WeekGrid
                view={draftView(draft.entries ?? [], slots.data?.data ?? [])}
                onDrop={editable ? (off, day, slot) => tryEntry(off, day, slot, true) : undefined}
                onCell={editable ? (day, slot) => setCell({ day, slot }) : undefined}
                onEntry={editable ? (e) => remove.mutate(e.id, { onSuccess: () => toast.success(`${e.course_code} removed`), onError: fail }) : undefined}
              />
            )}
            {!draft && <p className="text-sm text-muted-foreground">Pick a version.</p>}
          </section>
        </div>
      )}
      <Modal
        open={!!cell}
        onOpenChange={(o) => !o && setCell(null)}
        title={cell ? `Add entry · ${DAYS[cell.day]}` : ''}
        footer={
          <div className="flex gap-2">
            <Button variant="outline" disabled={!cell?.offering} onClick={() => cell?.offering && tryEntry(cell.offering, cell.day, cell.slot, false)}>Check</Button>
            <Button disabled={!cell?.offering} onClick={() => cell?.offering && tryEntry(cell.offering, cell.day, cell.slot, true)}>Add</Button>
          </div>
        }
      >
        <Select aria-label="Offering" placeholder="Offering" options={palette.map((o) => ({ value: o.id, label: `${o.course_code} ${o.section_code}` }))} value={cell?.offering ?? ''} onChange={(e) => cell && setCell({ ...cell, offering: e.target.value })} />
        <div className="mt-2"><ConflictBadges report={report} /></div>
      </Modal>
      <Modal
        open={publishOpen}
        onOpenChange={setPublishOpen}
        title="Publish timetable"
        description="The previous published version is archived; future scheduled sessions are regenerated (holidays skipped, attendance-taken sessions kept)."
        footer={
          <Button
            onClick={() =>
              publish.mutate(undefined, {
                onSuccess: (r) => {
                  setPublishOpen(false);
                  toast.success(r.data.job_id ? 'Published — sessions are being generated' : `Published — ${r.data.sessions_created} sessions created, ${r.data.sessions_removed} removed, ${r.data.sessions_preserved} kept`);
                },
                onError: (e) => {
                  const d = getApiErrorDetails(e) as { conflicts?: ConflictReport };
                  if (d.conflicts) setReport(d.conflicts);
                  fail(e);
                },
              })
            }
          >
            Publish
          </Button>
        }
      >
        <FormField label="Effective from"><Input type="date" value={effective} onChange={(e) => setEffective(e.target.value)} /></FormField>
        <p className="mt-2 text-sm text-muted-foreground">{draft?.entries_count ?? 0} entries will generate a session on every matching date until the term ends.</p>
      </Modal>
    </div>
  );
}

// ---- /admin/timetable/substitutions ----------------------------------------------------------------------------------------
function ApproveModal({ sub, onClose }: { sub: Substitution | null; onClose: () => void }) {
  const cands = useCandidates(sub?.id);
  const [pick, setPick] = useState('');
  useEffect(() => setPick(sub?.substitute_staff_id ?? ''), [sub]);
  const approve = useTimetableMutation(() => timetableApi.approveSub(sub!.id, { substitute_staff_id: pick || null }));
  return (
    <Modal
      open={!!sub}
      onOpenChange={(o) => !o && onClose()}
      title="Approve substitution"
      description={sub ? `${sub.course_code} · ${sub.on_date} · ${sub.slot_name} — ${sub.staff_name}` : ''}
      footer={<Button disabled={!pick} onClick={() => approve.mutate(undefined, { onSuccess: () => { toast.success('Substitution approved'); onClose(); }, onError: fail })}>Approve</Button>}
    >
      <Select
        aria-label="Substitute"
        placeholder="Substitute"
        options={(cands.data?.data ?? []).map((c) => ({ value: c.staff_id, label: `${c.name}${c.free ? ' — free' : c.on_leave ? ' — on leave' : ' — busy'}${c.teaches_offering ? ' · teaches it' : ''}`, disabled: !c.free }))}
        value={pick}
        onChange={(e) => setPick(e.target.value)}
      />
    </Modal>
  );
}

export function SubstitutionsPage() {
  useTitle('Substitutions');
  const { can } = usePermission();
  const decide = can('timetable', 'approve') || can('timetable', 'manage');
  const [status, setStatus] = useState('requested');
  const [source, setSource] = useState('');
  const [scope, setScope] = useState('');
  const list = useSubstitutions({ status: status || undefined, source: source || undefined, scope: scope || undefined, page_size: 100 });
  const [approving, setApproving] = useState<Substitution | null>(null);
  const reject = useTimetableMutation((id: string) => timetableApi.rejectSub(id, {}));
  const withdraw = useTimetableMutation((id: string) => timetableApi.withdrawSub(id));
  const vis = list.data?.meta.visibility;
  return (
    <div className="space-y-4">
      <PageHeader title="Substitutions" description="Manual requests and requests raised automatically from approved leave." />
      <div className="flex flex-wrap gap-2">
        <Select className="w-40" aria-label="Status" placeholder="All statuses" options={['requested', 'approved', 'rejected', 'withdrawn'].map((s) => ({ value: s, label: s }))} value={status} onChange={(e) => setStatus(e.target.value)} />
        <Select className="w-40" aria-label="Source" placeholder="All sources" options={[{ value: 'manual', label: 'manual' }, { value: 'leave_auto', label: 'from leave' }]} value={source} onChange={(e) => setSource(e.target.value)} />
        <Select className="w-40" aria-label="Scope" options={[{ value: '', label: 'Default' }, { value: 'mine', label: 'Mine' }, ...((vis?.scopes ?? []) as string[]).map((s) => ({ value: s, label: s === 'all' ? 'All' : 'Department' }))]} value={scope} onChange={(e) => setScope(e.target.value)} />
      </div>
      <SimpleTable
        head={['Date', 'Class', 'Section', 'Faculty', 'Substitute', 'Source', 'Status', '']}
        rows={(list.data?.data ?? []).map((s) => [
          s.on_date,
          `${s.course_code ?? ''} ${s.slot_name ?? ''}`,
          s.section_name ?? '—',
          s.staff_name ?? '—',
          s.substitute_name ?? '—',
          s.source === 'leave_auto' ? <Badge key="l" variant="info" title={s.leave_id ?? ''}>leave</Badge> : 'manual',
          <StatusBadge key="s" status={s.status} />,
          <div key="a" className="flex gap-1">
            {decide && s.status === 'requested' && <Button size="sm" onClick={() => setApproving(s)}>Approve</Button>}
            {decide && s.status === 'requested' && <Button size="sm" variant="outline" onClick={() => reject.mutate(s.id, { onError: fail })}>Reject</Button>}
            {['requested', 'approved'].includes(s.status) && <Button size="sm" variant="ghost" onClick={() => withdraw.mutate(s.id, { onError: fail })}>Withdraw</Button>}
          </div>,
        ])}
      />
      <ApproveModal sub={approving} onClose={() => setApproving(null)} />
    </div>
  );
}

// ---- /admin/timetable/sessions ---------------------------------------------------------------------------------------------
function SessionActions({ s }: { s: Session }) {
  const [mode, setMode] = useState<'' | 'cancel' | 'reschedule'>('');
  const [v, setV] = useState({ date: s.session_date, start: hhmm(s.start_time), end: hhmm(s.end_time), reason: '' });
  const cancel = useTimetableMutation(() => timetableApi.cancel(s.id, { reason: v.reason || null }));
  const resched = useTimetableMutation(() => timetableApi.reschedule(s.id, { date: v.date, start: v.start, end: v.end, reason: v.reason || null }));
  if (s.status !== 'scheduled') return null;
  const locked = s.attendance_status !== 'not_taken';
  return (
    <>
      <Button size="sm" variant="ghost" disabled={locked} title={locked ? 'Attendance already taken' : ''} onClick={() => setMode('reschedule')}>Reschedule</Button>
      <Button size="sm" variant="ghost" disabled={locked} onClick={() => setMode('cancel')}>Cancel</Button>
      <Modal
        open={!!mode}
        onOpenChange={(o) => !o && setMode('')}
        title={mode === 'cancel' ? 'Cancel session' : 'Reschedule session'}
        footer={
          <Button onClick={() => (mode === 'cancel' ? cancel : resched).mutate(undefined, { onSuccess: () => { toast.success('Done'); setMode(''); }, onError: fail })}>Confirm</Button>
        }
      >
        {mode === 'reschedule' && (
          <div className="grid grid-cols-3 gap-2">
            <Input type="date" value={v.date} onChange={(e) => setV({ ...v, date: e.target.value })} />
            <Input type="time" value={v.start} onChange={(e) => setV({ ...v, start: e.target.value })} />
            <Input type="time" value={v.end} onChange={(e) => setV({ ...v, end: e.target.value })} />
          </div>
        )}
        <Input className="mt-2" placeholder="Reason" value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />
      </Modal>
    </>
  );
}

export function SessionsTable({ rows }: { rows: Session[] }) {
  return (
    <SimpleTable
      head={['Date', 'Time', 'Course', 'Section', 'Room', 'Faculty', 'Status', 'Attendance', '']}
      rows={rows.map((s) => [
        s.session_date,
        `${hhmm(s.start_time)}–${hhmm(s.end_time)}`,
        s.course_code ?? '',
        s.section_name ?? '—',
        s.room_code ?? '—',
        <span key="f">{s.staff_name}{s.substituted && <Badge variant="info" className="ml-1">sub</Badge>}</span>,
        <StatusBadge key="s" status={s.status} />,
        s.attendance_status,
        <div key="a" className="flex"><SessionActions s={s} /></div>,
      ])}
    />
  );
}

export function SessionsPage() {
  useTitle('Class sessions');
  const [term, setTerm] = useState('');
  const [offering, setOffering] = useState('');
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));
  const [scope, setScope] = useState('');
  const offerings = useOfferings({ term_id: term || undefined, page_size: 200 });
  const list = useSessions({ offering_id: offering || undefined, date_from: from, scope: scope || undefined, page_size: 100 });
  const [extra, setExtra] = useState(false);
  const [x, setX] = useState({ date: from, start: '15:00', end: '16:00', room_id: '', topic: '' });
  const rooms = useRooms({ page_size: 200 });
  const create = useTimetableMutation(() => timetableApi.extra({ offering_id: offering, ...x, room_id: x.room_id || null, topic: x.topic || null }));
  const vis = list.data?.meta.visibility;
  return (
    <div className="space-y-4">
      <PageHeader title="Class sessions" description="Generated from published timetables, plus extra and rescheduled classes." actions={<Button disabled={!offering} onClick={() => setExtra(true)}><CalendarPlus className="h-4 w-4" /> Extra session</Button>} />
      <div className="flex flex-wrap gap-2">
        <TermPicker value={term} onChange={setTerm} />
        <Select className="w-56" aria-label="Offering" placeholder="All offerings" options={(offerings.data?.data ?? []).map((o) => ({ value: o.id, label: `${o.course_code} ${o.section_code}` }))} value={offering} onChange={(e) => setOffering(e.target.value)} />
        <Input type="date" className="w-44" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Select className="w-36" aria-label="Scope" options={[{ value: '', label: 'Default' }, { value: 'mine', label: 'Mine' }, ...((vis?.scopes ?? []) as string[]).map((s) => ({ value: s, label: s }))]} value={scope} onChange={(e) => setScope(e.target.value)} />
      </div>
      <SessionsTable rows={list.data?.data ?? []} />
      <Modal open={extra} onOpenChange={setExtra} title="Extra / remedial session" footer={<Button onClick={() => create.mutate(undefined, { onSuccess: () => { toast.success('Session created'); setExtra(false); }, onError: fail })}>Create</Button>}>
        <div className="grid grid-cols-3 gap-2">
          <Input type="date" value={x.date} onChange={(e) => setX({ ...x, date: e.target.value })} />
          <Input type="time" value={x.start} onChange={(e) => setX({ ...x, start: e.target.value })} />
          <Input type="time" value={x.end} onChange={(e) => setX({ ...x, end: e.target.value })} />
        </div>
        <Select className="mt-2" aria-label="Room" placeholder="Room (optional)" options={(rooms.data?.data ?? []).map((r) => ({ value: r.id, label: r.code }))} value={x.room_id} onChange={(e) => setX({ ...x, room_id: e.target.value })} />
        <Input className="mt-2" placeholder="Topic" value={x.topic} onChange={(e) => setX({ ...x, topic: e.target.value })} />
      </Modal>
    </div>
  );
}

// ---- my timetable (faculty / student / parent) ---------------------------------------------------------------------------
function ICalButton() {
  const [url, setUrl] = useState('');
  return url ? (
    <Input readOnly value={url} className="w-96" onFocus={(e) => e.target.select()} aria-label="iCal URL" />
  ) : (
    <Button variant="outline" onClick={() => timetableApi.icalToken().then((r) => { setUrl(r.data.url ?? ''); toast.success('Copy the link into your calendar app'); }).catch(fail)}>
      <CalendarPlus className="h-4 w-4" /> Subscribe (iCal)
    </Button>
  );
}

export function MyTimetablePage({ wardId }: { wardId?: string }) {
  useTitle('My timetable');
  const [search] = useSearchParams();
  const ward = wardId ?? search.get('ward') ?? undefined;
  const [week, setWeek] = useState(new Date().toISOString().slice(0, 10));
  const me = useMyWeek({ week, ward_id: ward });
  const today = useToday();
  const shift = (d: number) => {
    const dt = new Date(week);
    dt.setDate(dt.getDate() + d);
    setWeek(dt.toISOString().slice(0, 10));
  };
  return (
    <div className="space-y-4">
      <PageHeader
        title={me.data?.data.label ? `Timetable — ${me.data.data.label}` : 'My timetable'}
        description={me.data?.data.week_start ? `Week of ${me.data.data.week_start} (ISO week ${me.data.data.iso_week})` : undefined}
        actions={
          <div className="flex gap-2 print:hidden">
            <Button variant="outline" onClick={() => shift(-7)}>‹</Button>
            <Button variant="outline" onClick={() => setWeek(new Date().toISOString().slice(0, 10))}>This week</Button>
            <Button variant="outline" onClick={() => shift(7)}>›</Button>
            {!ward && <ICalButton />}
          </div>
        }
      />
      {me.error ? <p className="text-sm text-muted-foreground">{getApiError(me.error)}</p> : <WeekGrid view={me.data?.data} />}
      {!ward && (today.data?.data ?? []).length > 0 && (
        <section className="space-y-2">
          <h3 className="font-medium">Today</h3>
          <SessionsTable rows={today.data?.data ?? []} />
        </section>
      )}
    </div>
  );
}

// ---- /rooms/:id/today (kiosk) -------------------------------------------------------------------------------------------------
export function RoomKioskPage() {
  const { id } = useParams();
  const today = new Date().toISOString().slice(0, 10);
  const view = useWeekly({ scope: 'room', id }, !!id);
  useTitle(view.data?.data.label ?? 'Room');
  useEffect(() => {
    const t = setInterval(() => void view.refetch(), 60_000);
    return () => clearInterval(t);
  }, [view]);
  const sessions = (view.data?.data.sessions ?? []).filter((s) => s.session_date === today);
  const now = new Date().toTimeString().slice(0, 5);
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <h1 className="text-3xl font-bold">{view.data?.data.label}</h1>
      <p className="text-lg text-muted-foreground">{new Date().toDateString()}</p>
      {sessions.length === 0 && <p className="text-xl">No classes today.</p>}
      {sessions.map((s) => {
        const live = hhmm(s.start_time) <= now && now < hhmm(s.end_time);
        return (
          <div key={s.id} className={`rounded-lg border p-4 text-lg ${live ? 'border-primary bg-brand-50 dark:bg-slate-800' : ''}`}>
            <b>{hhmm(s.start_time)}–{hhmm(s.end_time)}</b> · {s.course_code} {s.course_title} · {s.staff_name} {s.status !== 'scheduled' && <StatusBadge status={s.status} />}
          </div>
        );
      })}
    </div>
  );
}
