import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Building, ChevronRight, Plus, UserCog } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { institutionApi } from '../api';
import { StaffPicker } from '../components/StaffPicker';
import { useColleges, useDepartments, useFaculties, useInstMutation } from '../hooks';
import { DEPARTMENT_TYPES, type Department } from '../types';

const schema = z.object({
  college_id: z.string().uuid('Pick a college'),
  faculty_id: z.string().optional(),
  code: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,19}$/, '1–20 letters/digits'),
  name: z.string().min(2).max(200),
  department_type: z.enum(DEPARTMENT_TYPES),
});
type FormValues = z.infer<typeof schema>;

/** /admin/departments — tree college → faculty → department; HOD picker grants hod @department. */
export default function DepartmentsPage() {
  const { can } = usePermission();
  const facultiesOn = useFeature('institution.faculties');
  const [scope, setScope] = useState<string | undefined>();
  const [q, setQ] = useState('');
  const depts = useDepartments({ scope, q: q || undefined, page_size: 200 });
  const colleges = useColleges({ scope: 'all', page_size: 200 });
  const faculties = useFaculties({ page_size: 200 }, facultiesOn);
  const [creating, setCreating] = useState(false);
  const [hodFor, setHodFor] = useState<Department | null>(null);
  const create = useInstMutation((b: Record<string, unknown>) => institutionApi.createDepartment(b), ['departments']);
  const hod = useInstMutation(({ id, user }: { id: string; user: string }) => institutionApi.assignHod(id, user), ['departments', 'users']);
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { department_type: 'academic' } });
  const manage = can('departments', 'manage');

  const tree = useMemo(() => {
    const byCollege = new Map<string, Map<string, Department[]>>();
    for (const d of depts.data?.data ?? []) {
      const c = byCollege.get(d.college_id) ?? new Map<string, Department[]>();
      const key = d.faculty_id ?? '';
      c.set(key, [...(c.get(key) ?? []), d]);
      byCollege.set(d.college_id, c);
    }
    return byCollege;
  }, [depts.data]);

  if (depts.isLoading || colleges.isLoading) return <PageSkeleton />;
  const collegeName = (id: string) => colleges.data?.data.find((c) => c.id === id);
  const facultyName = (id: string) => faculties.data?.data.find((f) => f.id === id);

  const onSubmit = form.handleSubmit((v) =>
    create.mutate(
      { ...v, faculty_id: v.faculty_id || null },
      {
        onSuccess: () => {
          toast.success('Department created');
          setCreating(false);
        },
        onError: (e) => toast.error(getApiError(e)),
      },
    ),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Departments"
        description={facultiesOn ? 'Grouped by college and faculty.' : 'Grouped by college.'}
        actions={
          manage && (
            <Button onClick={() => { form.reset({ department_type: 'academic', code: '', name: '', college_id: '' }); setCreating(true); }}>
              <Plus className="h-4 w-4" /> New department
            </Button>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={depts.data?.meta.visibility} value={scope} onChange={setScope} />
        <Input className="w-60" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="space-y-4">
        {[...tree.entries()].map(([collegeId, groups]) => (
          <section key={collegeId} className="rounded-md border">
            <h2 className="flex items-center gap-2 border-b bg-muted/50 px-3 py-2 text-sm font-semibold">
              <Building className="h-4 w-4" /> {collegeName(collegeId)?.code} · {collegeName(collegeId)?.name}
            </h2>
            {[...groups.entries()].map(([facultyId, rows]) => (
              <div key={facultyId || 'none'} className="px-3 py-2">
                {facultyId && (
                  <p className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground">
                    <ChevronRight className="h-3 w-3" /> {facultyName(facultyId)?.name ?? 'Faculty'}
                  </p>
                )}
                <ul className="divide-y">
                  {rows.map((d) => (
                    <li key={d.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                      <span className="min-w-0">
                        <span className="font-medium">{d.code}</span> · {d.name}{' '}
                        <Badge variant="outline">{d.department_type.replace(/_/g, ' ')}</Badge>
                      </span>
                      <span className="flex items-center gap-2 text-muted-foreground">
                        HOD: {d.hod_name ?? '—'}
                        {manage && (
                          <Button size="sm" variant="ghost" onClick={() => setHodFor(d)} aria-label={`Assign HOD of ${d.code}`}>
                            <UserCog className="h-4 w-4" />
                          </Button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>
        ))}
        {tree.size === 0 && <p className="text-sm text-muted-foreground">No departments.</p>}
      </div>

      <Modal open={creating} onOpenChange={setCreating} title="New department" footer={<Button onClick={onSubmit} loading={create.isPending}>Create</Button>}>
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={onSubmit}>
          <label className="space-y-1.5 text-sm font-medium">
            College
            <Select
              placeholder="Select…"
              options={(colleges.data?.data ?? []).filter((c) => c.can_edit).map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))}
              {...form.register('college_id')}
            />
            {form.formState.errors.college_id && <span className="text-xs text-destructive">{form.formState.errors.college_id.message}</span>}
          </label>
          {facultiesOn && (
            <label className="space-y-1.5 text-sm font-medium">
              Faculty
              <Select
                placeholder="None"
                options={(faculties.data?.data ?? [])
                  .filter((f) => f.college_id === form.watch('college_id'))
                  .map((f) => ({ value: f.id, label: f.name }))}
                {...form.register('faculty_id')}
              />
            </label>
          )}
          <FormField label="Code" required {...form.register('code')} error={form.formState.errors.code} />
          <FormField label="Name" required {...form.register('name')} error={form.formState.errors.name} />
          <label className="space-y-1.5 text-sm font-medium">
            Type
            <Select options={DEPARTMENT_TYPES.map((t) => ({ value: t, label: t.replace(/_/g, ' ') }))} {...form.register('department_type')} />
          </label>
        </form>
      </Modal>

      <Modal open={hodFor !== null} onOpenChange={(o) => !o && setHodFor(null)} title={`HOD of ${hodFor?.code ?? ''}`} description="Grants the hod role scoped to this department; the previous HOD's assignment is revoked.">
        <StaffPicker
          onPick={(id, name) =>
            hodFor &&
            hod.mutate(
              { id: hodFor.id, user: id },
              {
                onSuccess: () => {
                  toast.success(`${name} is now HOD of ${hodFor.code}`);
                  setHodFor(null);
                },
                onError: (e) => toast.error(getApiError(e)),
              },
            )
          }
        />
      </Modal>
    </div>
  );
}
