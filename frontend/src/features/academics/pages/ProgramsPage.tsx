import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useColleges, useDepartments } from '@/features/institution/hooks';
import { academicsApi } from '../api';
import { useAcMutation, usePrograms } from '../hooks';
import { PROGRAM_LEVELS, PROGRAM_MODES, TERM_PATTERNS, label, type Program } from '../types';

const schema = z
  .object({
    college_id: z.string().uuid('Pick a college'),
    department_id: z.string().uuid('Pick a department'),
    code: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$/, '1–30 letters/digits'),
    name: z.string().min(2).max(200),
    degree_name: z.string().min(1).max(80),
    specialization: z.string().max(120).optional().or(z.literal('')),
    level: z.enum(PROGRAM_LEVELS),
    mode: z.enum(PROGRAM_MODES),
    term_pattern: z.enum(TERM_PATTERNS),
    duration_years: z.coerce.number().positive().max(10),
    total_terms: z.coerce.number().int().min(1).max(30),
    sanctioned_intake: z.coerce.number().int().min(0).optional().or(z.literal('')),
    approving_body: z.string().max(40).optional().or(z.literal('')),
    exam_authority: z.enum(['', 'university', 'autonomous_college']),
    is_open_enrolment: z.boolean(),
  })
  .refine((v) => !v.is_open_enrolment || ['certificate', 'diploma'].includes(v.level), {
    message: 'Open enrolment is only for certificate / diploma programmes',
    path: ['is_open_enrolment'],
  });
type FormValues = z.infer<typeof schema>;

/** /admin/academics/programs — programme master (code, level, mode, department, intake, exam authority, status). */
export default function ProgramsPage() {
  const { can } = usePermission();
  const [params, setParams] = useState<{ page: number; page_size: number; scope?: string; q?: string; level?: string; sort?: string | null }>({
    page: 1,
    page_size: 25,
  });
  const list = usePrograms(params);
  const colleges = useColleges({ scope: 'all', page_size: 200 });
  const departments = useDepartments({ scope: 'all', page_size: 200 });
  const [editing, setEditing] = useState<Program | 'new' | null>(null);
  const create = useAcMutation((b: Record<string, unknown>) => academicsApi.createProgram(b), ['programs']);
  const update = useAcMutation(({ id, ...b }: Record<string, unknown>) => academicsApi.updateProgram(String(id), b), ['programs']);
  const close = useAcMutation((id: string) => academicsApi.closeProgram(id), ['programs']);
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });
  const college = form.watch('college_id');

  const open = (p: Program | 'new') => {
    setEditing(p);
    form.reset(
      p === 'new'
        ? { level: 'ug', mode: 'regular', term_pattern: 'semester', duration_years: 4, total_terms: 8, exam_authority: '', is_open_enrolment: false, college_id: '', department_id: '', code: '', name: '', degree_name: '' }
        : {
            college_id: p.college_id,
            department_id: p.department_id,
            code: p.code,
            name: p.name,
            degree_name: p.degree_name,
            specialization: p.specialization ?? '',
            level: p.level as FormValues['level'],
            mode: p.mode as FormValues['mode'],
            term_pattern: p.term_pattern as FormValues['term_pattern'],
            duration_years: Number(p.duration_years),
            total_terms: p.total_terms,
            sanctioned_intake: p.sanctioned_intake ?? '',
            approving_body: p.approving_body ?? '',
            exam_authority: p.exam_authority as FormValues['exam_authority'],
            is_open_enrolment: p.is_open_enrolment,
          },
    );
  };

  const columns = useMemo<ColumnDef<Program, unknown>[]>(
    () => [
      { accessorKey: 'code', header: 'Code' },
      { accessorKey: 'name', header: 'Name', cell: ({ row }) => <span>{row.original.name}</span> },
      { accessorKey: 'level', header: 'Level', cell: ({ getValue }) => <Badge variant="outline">{label(String(getValue()))}</Badge> },
      { accessorKey: 'mode', header: 'Mode', cell: ({ getValue }) => label(String(getValue())) },
      { id: 'department', header: 'Department', enableSorting: false, cell: ({ row }) => `${row.original.college_code ?? ''} · ${row.original.department_code ?? ''}` },
      { accessorKey: 'total_terms', header: 'Terms' },
      { accessorKey: 'sanctioned_intake', header: 'Intake', cell: ({ getValue }) => (getValue() as number | null) ?? '—' },
      { accessorKey: 'exam_authority', header: 'Exam authority', cell: ({ getValue }) => label(String(getValue())) },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) =>
          row.original.can_edit && (
            <span className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => open(row.original)}>
                Edit
              </Button>
              {row.original.status !== 'closed' && can('programs', 'manage') && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    close.mutate(row.original.id, {
                      onSuccess: () => toast.success(`${row.original.code} closed`),
                      onError: (e) => toast.error(getApiError(e)),
                    })
                  }
                >
                  Close
                </Button>
              )}
            </span>
          ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const onSubmit = form.handleSubmit((v) => {
    const body: Record<string, unknown> = Object.fromEntries(Object.entries(v).map(([k, val]) => [k, val === '' ? null : val]));
    const done = {
      onSuccess: () => {
        toast.success(editing === 'new' ? 'Programme created' : 'Programme updated');
        setEditing(null);
      },
      onError: (e: unknown) => toast.error(getApiError(e)),
    };
    if (editing === 'new') create.mutate(body, done);
    else if (editing) {
      const { college_id: _c, department_id: _d, code: _code, level: _l, ...rest } = body;
      update.mutate({ id: editing.id, ...rest, version: editing.version }, done);
    }
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Programmes"
        description="Degree, diploma and certificate programmes with their duration, intake and examining authority."
        actions={
          can('programs', 'create') && (
            <Button onClick={() => open('new')}>
              <Plus className="h-4 w-4" /> New programme
            </Button>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope} onChange={(scope) => setParams((p) => ({ ...p, scope, page: 1 }))} />
        <Input className="w-60" placeholder="Search code or name…" value={params.q ?? ''} onChange={(e) => setParams((p) => ({ ...p, q: e.target.value || undefined, page: 1 }))} />
        <Select
          className="w-40"
          placeholder="All levels"
          options={PROGRAM_LEVELS.map((l) => ({ value: l, label: label(l) }))}
          value={params.level ?? ''}
          onChange={(e) => setParams((p) => ({ ...p, level: e.target.value || undefined, page: 1 }))}
        />
      </div>
      <DataTable
        columns={columns}
        data={list.data?.data ?? []}
        isLoading={list.isLoading}
        pagination={list.data?.meta.pagination}
        onPageChange={(page) => setParams((p) => ({ ...p, page }))}
        onPageSizeChange={(page_size) => setParams((p) => ({ ...p, page_size, page: 1 }))}
        sort={params.sort}
        onSortChange={(sort) => setParams((p) => ({ ...p, sort }))}
        rowKey={(r) => r.id}
      />

      <Modal
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        title={editing === 'new' ? 'New programme' : `Edit ${editing?.code ?? ''}`}
        size="lg"
        footer={
          <Button onClick={onSubmit} loading={create.isPending || update.isPending}>
            Save
          </Button>
        }
      >
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={onSubmit}>
          <label className="space-y-1.5 text-sm font-medium">
            College
            <Select disabled={editing !== 'new'} placeholder="Select…" options={(colleges.data?.data ?? []).map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))} {...form.register('college_id')} />
            {form.formState.errors.college_id && <span className="text-xs text-destructive">{form.formState.errors.college_id.message}</span>}
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Department
            <Select
              disabled={editing !== 'new'}
              placeholder="Select…"
              options={(departments.data?.data ?? []).filter((d) => !college || d.college_id === college).map((d) => ({ value: d.id, label: `${d.code} · ${d.name}` }))}
              {...form.register('department_id')}
            />
            {form.formState.errors.department_id && <span className="text-xs text-destructive">{form.formState.errors.department_id.message}</span>}
          </label>
          <FormField label="Code" required disabled={editing !== 'new'} {...form.register('code')} error={form.formState.errors.code} />
          <FormField label="Name" required {...form.register('name')} error={form.formState.errors.name} />
          <FormField label="Degree" required placeholder="B.Tech" {...form.register('degree_name')} error={form.formState.errors.degree_name} />
          <FormField label="Specialisation" {...form.register('specialization')} />
          <label className="space-y-1.5 text-sm font-medium">
            Level
            <Select disabled={editing !== 'new'} options={PROGRAM_LEVELS.map((l) => ({ value: l, label: label(l) }))} {...form.register('level')} />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Mode
            <Select options={PROGRAM_MODES.map((l) => ({ value: l, label: label(l) }))} {...form.register('mode')} />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Term pattern
            <Select options={TERM_PATTERNS.map((l) => ({ value: l, label: label(l) }))} {...form.register('term_pattern')} />
          </label>
          <FormField label="Duration (years)" type="number" step="0.5" {...form.register('duration_years')} error={form.formState.errors.duration_years} />
          <FormField label="Total terms" type="number" {...form.register('total_terms')} error={form.formState.errors.total_terms} />
          <FormField label="Sanctioned intake" type="number" {...form.register('sanctioned_intake')} />
          <FormField label="Approving body" placeholder="AICTE / UGC / NCTE …" {...form.register('approving_body')} />
          <label className="space-y-1.5 text-sm font-medium">
            Exam authority
            <Select
              options={[
                { value: '', label: 'Default for the institution type' },
                { value: 'university', label: 'University' },
                { value: 'autonomous_college', label: 'Autonomous college' },
              ]}
              {...form.register('exam_authority')}
            />
          </label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <Checkbox checked={form.watch('is_open_enrolment')} onCheckedChange={(c) => form.setValue('is_open_enrolment', c === true)} />
            Open enrolment (value-added / certificate programmes)
            {form.formState.errors.is_open_enrolment && <span className="text-xs text-destructive">{form.formState.errors.is_open_enrolment.message}</span>}
          </label>
        </form>
      </Modal>
    </div>
  );
}
