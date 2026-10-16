import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Download, Layers, Plus, Users } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { academicsApi } from '@/features/academics/api';
import { SimpleTable } from '@/features/hr/components/shared';
import { registrationApi } from '../api';
import { useCurrentTerm, useOfferings, useRegistrationMutation, useRoster, useTerms } from '../hooks';
import { OFFERING_STATUSES, label, type BulkPreview, type FacultyOut, type Offering } from '../types';

/** Term picker defaulting to the current term. */
export function TermPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const terms = useTerms();
  const current = useCurrentTerm();
  const list = useMemo(() => (terms.data?.data ?? []) as { id: string; name: string; start_date?: string }[], [terms.data]);
  useEffect(() => {
    const cur = (current.data?.data as { id: string } | null | undefined)?.id;
    if (!value && cur) onChange(cur);
  }, [value, current.data, onChange]);
  return (
    <Select
      className="w-60"
      aria-label="Term"
      options={list.map((t) => ({ value: t.id, label: `${t.name}${t.start_date ? ` (${t.start_date.slice(0, 4)})` : ''}` }))}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function LoadBadge({ f }: { f: FacultyOut }) {
  if (f.total_hours == null) return null;
  const tone = f.load_status === 'over' ? 'destructive' : f.load_status === 'within' ? 'success' : 'info';
  return (
    <Badge variant={tone} title={`Workload ${f.total_hours} h vs norm ${f.norm_hours ?? '—'} h`}>
      {f.total_hours}/{f.norm_hours ?? '—'} h
    </Badge>
  );
}

/** /admin/academics/offerings — term offerings grid, create, faculty with workload badges, bulk wizard, status. */
export default function OfferingsPage() {
  const { can } = usePermission();
  const [term, setTerm] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [scope, setScope] = useState('');
  const [page, setPage] = useState(1);
  const list = useOfferings({ term_id: term || undefined, q: q || undefined, status: status || undefined, scope: scope || undefined, page, page_size: 50 });
  const [facultyFor, setFacultyFor] = useState<Offering | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  useEffect(() => {
    document.title = 'Course offerings';
  }, []);
  const setStatusMut = useRegistrationMutation((v: { id: string; status: string }) => registrationApi.offeringStatus(v.id, v.status));
  const rows = list.data?.data ?? [];
  const pg = list.data?.meta.pagination;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Course offerings"
        description="Offerings of the term with faculty, seats and target batches."
        actions={
          <div className="flex flex-wrap gap-2">
            <TermPicker value={term} onChange={setTerm} />
            {(can('offerings', 'bulk_create') || can('offerings', 'manage')) && (
              <Button variant="outline" onClick={() => setBulkOpen(true)}><Layers className="h-4 w-4" /> From curriculum</Button>
            )}
            {(can('offerings', 'create') || can('offerings', 'manage')) && (
              <Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> New offering</Button>
            )}
          </div>
        }
      />
      <div className="flex flex-wrap gap-2">
        <Input className="w-56" placeholder="Search course code / title" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select className="w-44" aria-label="Status" placeholder="All statuses" options={OFFERING_STATUSES.map((s) => ({ value: s, label: label(s) }))} value={status} onChange={(e) => setStatus(e.target.value)} />
        <Select className="w-40" aria-label="Scope" placeholder="All" options={[{ value: 'mine', label: 'Mine' }, { value: 'department', label: 'My department' }]} value={scope} onChange={(e) => setScope(e.target.value)} />
      </div>
      <SimpleTable
        head={['Course', 'Sec', 'Dept', 'Faculty', 'Seats', 'Targets', 'Status', '']}
        rows={rows.map((o) => [
          <div key="c"><div className="font-medium">{o.course_code}</div><div className="text-xs text-muted-foreground">{o.course_title} · {o.credits} cr</div></div>,
          o.section_code,
          o.department_code,
          <div key="f" className="space-y-1">
            {o.faculty.map((f) => <div key={f.staff_id} className="flex items-center gap-1 text-xs">{f.name} <span className="text-muted-foreground">({label(f.role)}, {f.hours_per_week} h)</span> <LoadBadge f={f} /></div>)}
            {!o.faculty.length && <span className="text-xs text-muted-foreground">Not allocated</span>}
          </div>,
          `${o.enrolled_count}/${o.max_seats ?? '∞'}${o.waitlist_count ? ` (+${o.waitlist_count} wl)` : ''}`,
          <span key="t" className="text-xs">{o.targets.map((t) => `${t.batch_code}${t.section_name ? `/${t.section_name}` : ''}`).join(', ') || '—'}</span>,
          <StatusBadge key="s" status={o.status} />,
          <div key="a" className="flex flex-wrap gap-1">
            <Link className="text-xs text-primary hover:underline" to={`/admin/academics/offerings/${o.id}/roster`}>Roster</Link>
            {(can('offerings', 'allocate_faculty') || can('offerings', 'manage')) && <Button size="sm" variant="ghost" onClick={() => setFacultyFor(o)}><Users className="h-3 w-3" /> Faculty</Button>}
            {(can('offerings', 'update') || can('offerings', 'manage')) && o.status === 'planned' && (
              <Button size="sm" variant="ghost" onClick={() => setStatusMut.mutateAsync({ id: o.id, status: 'open' }).then(() => toast.success('Opened')).catch((e) => toast.error(getApiError(e)))}>Open</Button>
            )}
            {(can('offerings', 'update') || can('offerings', 'manage')) && o.status === 'open' && (
              <Button size="sm" variant="ghost" onClick={() => setStatusMut.mutateAsync({ id: o.id, status: 'closed' }).then(() => toast.success('Closed')).catch((e) => toast.error(getApiError(e)))}>Close</Button>
            )}
          </div>,
        ])}
        empty={list.isLoading ? 'Loading…' : 'No offerings for this term.'}
      />
      {pg && pg.total_pages > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          Page {pg.page} of {pg.total_pages} · {pg.total} offerings
          <Button size="sm" variant="outline" disabled={page >= pg.total_pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
      {facultyFor && <FacultyDialog offering={facultyFor} onClose={() => setFacultyFor(null)} />}
      {createOpen && <CreateOfferingDialog termId={term} onClose={() => setCreateOpen(false)} />}
      {bulkOpen && <BulkDialog termId={term} onClose={() => setBulkOpen(false)} />}
    </div>
  );
}

function FacultyDialog({ offering, onClose }: { offering: Offering; onClose: () => void }) {
  const staff = useQuery({ queryKey: ['staff', 'teaching'], queryFn: () => import('@/features/hr/api').then((m) => m.hrApi.staff({ staff_category: 'teaching', page_size: 200 })) });
  const [items, setItems] = useState(offering.faculty.map((f) => ({ staff_id: f.staff_id, role: f.role, hours_per_week: f.hours_per_week })));
  const [cross, setCross] = useState(false);
  const save = useRegistrationMutation(() => registrationApi.offeringFaculty(offering.id, items, cross));
  const options = ((staff.data?.data ?? []) as { id: string; full_name?: string; first_name?: string; employee_id: string }[]).map((s) => ({ value: s.id, label: `${s.full_name ?? s.first_name} (${s.employee_id})` }));
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Faculty — ${offering.course_code} ${offering.section_code}`}
      footer={
        <Button disabled={save.isPending} onClick={async () => {
          try {
            const r = await save.mutateAsync(undefined);
            if (r.data.warnings.length) toast.warning(`Above the workload norm: ${r.data.warnings.map((w) => `${w.name} ${w.total_hours}/${w.norm_hours} h`).join(', ')}`);
            else toast.success('Faculty saved');
            onClose();
          } catch (e) {
            toast.error(getApiError(e));
          }
        }}>Save</Button>
      }
    >
      <div className="space-y-2">
        {items.map((it, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Select className="w-56" aria-label="Staff" placeholder="Select…" options={options} value={it.staff_id} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, staff_id: e.target.value } : x)))} />
            <Select className="w-40" aria-label="Role" options={['coordinator', 'instructor', 'lab_instructor', 'teaching_assistant'].map((r) => ({ value: r, label: label(r) }))} value={it.role} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))} />
            <Input className="w-20" type="number" aria-label="Hours per week" value={it.hours_per_week} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, hours_per_week: Number(e.target.value) } : x)))} />
            <Button size="sm" variant="ghost" onClick={() => setItems(items.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => setItems([...items, { staff_id: '', role: 'instructor', hours_per_week: 3 }])}>Add faculty</Button>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cross} onChange={(e) => setCross(e.target.checked)} /> Allow another department (dean / registrar)</label>
      </div>
    </Modal>
  );
}

function CreateOfferingDialog({ termId, onClose }: { termId: string; onClose: () => void }) {
  const [courseQ, setCourseQ] = useState('');
  const courses = useQuery({ queryKey: ['courses', 'pick', courseQ], queryFn: () => academicsApi.courses({ q: courseQ || undefined, status: 'active', page_size: 50 }) });
  const [form, setForm] = useState({ course_id: '', section_code: 'A', max_seats: '60' });
  const create = useRegistrationMutation(() => registrationApi.createOffering({ term_id: termId, course_id: form.course_id, section_code: form.section_code, max_seats: Number(form.max_seats) || undefined }));
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New offering" footer={
      <Button disabled={!form.course_id || create.isPending} onClick={() => create.mutateAsync(undefined).then(() => { toast.success('Offering created'); onClose(); }).catch((e) => toast.error(getApiError(e)))}>Create</Button>
    }>
      <div className="grid gap-3">
        <Input placeholder="Search courses" value={courseQ} onChange={(e) => setCourseQ(e.target.value)} />
        <Select aria-label="Course" placeholder="Select a course…" options={((courses.data?.data ?? []) as { id: string; code: string; title: string }[]).map((c) => ({ value: c.id, label: `${c.code} — ${c.title}` }))} value={form.course_id} onChange={(e) => setForm({ ...form, course_id: e.target.value })} />
        <FormField label="Section code" value={form.section_code} onChange={(e) => setForm({ ...form, section_code: e.target.value.toUpperCase() })} />
        <FormField label="Max seats" type="number" value={form.max_seats} onChange={(e) => setForm({ ...form, max_seats: e.target.value })} />
      </div>
    </Modal>
  );
}

function BulkDialog({ termId, onClose }: { termId: string; onClose: () => void }) {
  const batches = useQuery({ queryKey: ['batches', 'active'], queryFn: () => academicsApi.batches({ status: 'active', page_size: 100 }) });
  const [picked, setPicked] = useState<string[]>([]);
  const [sections, setSections] = useState(2);
  const [baskets, setBaskets] = useState(true);
  const [preview, setPreview] = useState<BulkPreview | null>(null);
  const body = { term_id: termId, batch_ids: picked, sections_per_course: sections, include_baskets: baskets };
  const run = useRegistrationMutation((dry: boolean) => registrationApi.bulk(body, dry));
  const list = (batches.data?.data ?? []) as { id: string; code: string; current_term_number: number }[];
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Offerings from the curriculum" footer={
      <div className="flex gap-2">
        <Button variant="outline" disabled={!picked.length || run.isPending} onClick={() => run.mutateAsync(true).then((r) => setPreview(r.data)).catch((e) => toast.error(getApiError(e)))}>Preview</Button>
        <Button disabled={!preview || run.isPending} onClick={() => run.mutateAsync(false).then((r) => { toast.success(r.data.job_id ? 'Queued — see the jobs tray' : `${r.data.to_create} offering(s) created`); onClose(); }).catch((e) => toast.error(getApiError(e)))}>Apply</Button>
      </div>
    }>
      <div className="space-y-3">
        <div className="grid max-h-40 grid-cols-2 gap-1 overflow-y-auto text-sm">
          {list.map((b) => (
            <label key={b.id} className="flex items-center gap-2"><input type="checkbox" checked={picked.includes(b.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, b.id] : picked.filter((x) => x !== b.id))} />{b.code} (term {b.current_term_number})</label>
          ))}
        </div>
        <div className="flex items-center gap-3 text-sm">
          <FormField label="Sections per course" type="number" value={String(sections)} onChange={(e) => setSections(Math.max(1, Number(e.target.value)))} />
          <label className="flex items-center gap-2"><input type="checkbox" checked={baskets} onChange={(e) => setBaskets(e.target.checked)} /> Include elective baskets</label>
        </div>
        {preview && (
          <div className="space-y-1 text-sm">
            <div><b>{preview.to_create}</b> to create · {preview.existing} already exist</div>
            {preview.warnings.map((w) => <div key={w} className="text-xs text-amber-600">{w}</div>)}
            <div className="max-h-48 overflow-y-auto text-xs">
              {preview.items.map((i, k) => <div key={k} className={i.exists ? 'text-muted-foreground' : ''}>{i.course_code} {i.section_code} — {i.batch_codes.join(', ')} {i.basket_code ? `(${i.basket_code})` : ''} {i.exists ? '· exists' : ''}</div>)}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

/** /admin/academics/offerings/:id/roster and /faculty/offerings/:id — roster with XLSX export (job). */
export function OfferingRosterPage() {
  const { id } = useParams();
  const [wl, setWl] = useState(false);
  const roster = useRoster(id, wl);
  const offering = useQuery({ queryKey: ['registration', 'offering', id], queryFn: () => registrationApi.offering(id!), enabled: !!id });
  const o = offering.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader
        title={o ? `${o.course_code} · section ${o.section_code}` : 'Roster'}
        description={o ? `${o.course_title} — ${o.enrolled_count}/${o.max_seats ?? '∞'} seats` : undefined}
        actions={<Button variant="outline" onClick={() => registrationApi.rosterExport(id!).then(() => toast.success('Export queued — see the jobs tray')).catch((e) => toast.error(getApiError(e)))}><Download className="h-4 w-4" /> Export XLSX</Button>}
      />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={wl} onChange={(e) => setWl(e.target.checked)} /> Include waitlist</label>
      <SimpleTable
        head={['Reg. no.', 'Name', 'Programme', 'Batch', 'Section', 'Type', 'Attempt', 'Status']}
        rows={(roster.data?.data ?? []).map((r) => [r.registration_number, r.name, r.program_code, r.batch_code, r.section_name ?? '—', label(r.registration_type), r.attempt_number, <StatusBadge key="s" status={r.status} />])}
        empty={roster.isLoading ? 'Loading…' : 'No students yet.'}
      />
    </div>
  );
}
