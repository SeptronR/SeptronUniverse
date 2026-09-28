import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { CheckCircle2, Copy, GitCompare, Lock, Plus, Rocket, ShieldCheck } from 'lucide-react';
import { getApiError, getApiErrorDetails } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { academicsApi } from '../api';
import { BasketsPanel } from '../components/BasketsPanel';
import { BulkImportButton } from '../components/BulkImportButton';
import { CourseDrawer } from '../components/CourseDrawer';
import { DiffView } from '../components/DiffView';
import { RulesForm } from '../components/RulesForm';
import { StructureEditor } from '../components/StructureEditor';
import { downloadBlob } from '../download';
import { useAcMutation, useCourses, usePrograms, useProgramRegulations, useRegulation } from '../hooks';
import { label, num, type Course } from '../types';

type Confirm = 'approve' | 'activate' | 'clone' | null;

/** /admin/academics/regulations/:id — Rules | Courses | Structure | Baskets | Diff, with Approve / Activate / Clone. */
export default function RegulationWorkspacePage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { can } = usePermission();
  const reg = useRegulation(id);
  const courses = useCourses({ regulation_id: id, page_size: 200, sort: 'code' }, !!id);
  const bindings = useProgramRegulations({ regulation_id: id, page_size: 50 }, !!id);
  const programs = usePrograms({ page_size: 200, scope: 'all' });
  const basketsOn = useFeature('academics.elective_baskets');
  const bosOn = useFeature('academics.bos_approval_workflow');
  const [tab, setTab] = useState('rules');
  const [pr, setPr] = useState<string>('');
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [issues, setIssues] = useState<{ program: string; message: string }[]>([]);
  const [drawer, setDrawer] = useState<string | 'new' | null>(null);
  const [clone, setClone] = useState({ code: '', name: '', effective_from_admission_year: new Date().getFullYear() });
  const [bind, setBind] = useState({ program_id: '', total_credits_required: 160 });
  const approve = useAcMutation(() => academicsApi.approveRegulation(id), ['regulations']);
  const activate = useAcMutation(() => academicsApi.activateRegulation(id), ['regulations', 'courses', 'program-regulations']);
  const doClone = useAcMutation(() => academicsApi.cloneRegulation(id, clone), ['regulations']);
  const createBinding = useAcMutation(() => academicsApi.createProgramRegulation({ ...bind, regulation_id: id }), ['program-regulations', 'regulations']);
  const r = reg.data?.data;

  useEffect(() => {
    // a clone navigates to another id on the same mounted page: start over on its Rules tab
    setTab('rules');
    setPr('');
    setIssues([]);
  }, [id]);

  useEffect(() => {
    const first = bindings.data?.data[0]?.id;
    if (!pr && first) setPr(first);
  }, [bindings.data, pr]);

  const courseColumns = useMemo<ColumnDef<Course, unknown>[]>(
    () => [
      { accessorKey: 'code', header: 'Code' },
      { accessorKey: 'title', header: 'Title' },
      { accessorKey: 'course_type', header: 'Type', cell: ({ getValue }) => label(String(getValue())) },
      { id: 'ltpc', header: 'L-T-P-C', cell: ({ row }) => row.original.ltpc },
      { accessorKey: 'department_code', header: 'Dept' },
      { accessorKey: 'scheme_code', header: 'Scheme' },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => {
          const c = row.original;
          const canApprove = c.status === 'draft' && can('courses', 'approve') && r?.status !== 'active';
          return (
            <span className="flex items-center gap-1">
              <StatusBadge status={c.status} />
              {canApprove && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    academicsApi
                      .courseStatus(c.id, 'approved')
                      .then(() => {
                        toast.success(`${c.code} approved`);
                        courses.refetch();
                      })
                      .catch((err) => toast.error(getApiError(err)));
                  }}
                >
                  Approve
                </Button>
              )}
            </span>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [r?.status],
  );

  if (reg.isLoading || !r) return <PageSkeleton />;
  const locked = r.structure_locked;
  const done = (msg: string, after?: () => void) => ({
    onSuccess: () => {
      toast.success(msg);
      setConfirm(null);
      setIssues([]);
      after?.();
    },
    onError: (e: unknown) => {
      const d = getApiErrorDetails(e) as { issues?: { program: string; message: string }[] };
      setIssues(d.issues ?? []);
      toast.error(getApiError(e));
    },
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title={`${r.code} · ${r.name}`}
        breadcrumbs={[{ label: 'Regulations', to: '/admin/academics/regulations' }, { label: r.code }]}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={r.status} /> from admission year {r.effective_from_admission_year} · {r.course_count} courses · {r.program_count} programmes
            {r.workflow_instance_id && r.status === 'draft' && (
              <Link className="text-primary underline" to={`/approvals/instances/${r.workflow_instance_id}`}>
                approval workflow
              </Link>
            )}
          </span>
        }
        actions={
          <div className="flex flex-wrap gap-2">
            {r.status === 'draft' && (can('regulations', 'approve') || (bosOn && can('regulations', 'update'))) && (
              <Button onClick={() => setConfirm('approve')}>
                <ShieldCheck className="h-4 w-4" /> {bosOn ? 'Submit for approval' : 'Approve'}
              </Button>
            )}
            {r.status === 'approved' && can('regulations', 'publish') && (
              <Button onClick={() => setConfirm('activate')}>
                <Rocket className="h-4 w-4" /> Activate
              </Button>
            )}
            {can('regulations', 'clone') && (
              <Button variant="outline" onClick={() => { setClone({ code: '', name: `${r.name} (revised)`, effective_from_admission_year: r.effective_from_admission_year + 1 }); setConfirm('clone'); }}>
                <Copy className="h-4 w-4" /> Clone
              </Button>
            )}
          </div>
        }
      />
      {locked && (
        <div className="flex items-center gap-2 rounded-md border border-status-pending/40 bg-status-pending/10 px-3 py-2 text-sm" role="status">
          <Lock className="h-4 w-4" /> {r.status === 'superseded' ? 'Superseded' : 'Active'} since {r.locked_at?.slice(0, 10)} — courses, structures and baskets are locked. Clone this regulation to revise it.
        </div>
      )}
      {!locked && r.rules_locked && (
        <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm" role="status">
          <CheckCircle2 className="h-4 w-4 text-status-approved" /> Approved — rules are locked; courses and structure stay editable until activation.
        </div>
      )}
      {issues.length > 0 && (
        <div className="rounded-md border border-status-rejected/40 p-3 text-sm" role="alert">
          <p className="font-medium">Resolve these before approval / activation:</p>
          <ul className="ml-5 list-disc">
            {issues.map((i, n) => (
              <li key={n}>
                {i.program}: {i.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="courses">Courses</TabsTrigger>
          <TabsTrigger value="structure">Structure</TabsTrigger>
          {basketsOn && <TabsTrigger value="baskets">Baskets</TabsTrigger>}
          <TabsTrigger value="diff">
            <GitCompare className="mr-1 h-4 w-4" /> Diff
          </TabsTrigger>
        </TabsList>
        <TabsContent value="rules">
          <RulesForm regulation={r} />
        </TabsContent>
        <TabsContent value="courses" className="space-y-3">
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={async () => { try { downloadBlob(await academicsApi.exportCourses({ regulation_id: id }), `${r.code}-courses.xlsx`); } catch (e) { toast.error(getApiError(e)); } }}>
              Export
            </Button>
            {!locked && can('courses', 'create') && <BulkImportButton regulationId={id} />}
            {!locked && can('courses', 'create') && (
              <Button onClick={() => setDrawer('new')}>
                <Plus className="h-4 w-4" /> New course
              </Button>
            )}
          </div>
          <DataTable columns={courseColumns} data={courses.data?.data ?? []} isLoading={courses.isLoading} onRowClick={(c) => setDrawer(c.id)} rowKey={(c) => c.id} />
        </TabsContent>
        <TabsContent value="structure" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Programme"
              className="w-72"
              placeholder={bindings.data?.data.length ? undefined : 'No programme bound yet'}
              options={(bindings.data?.data ?? []).map((b) => ({ value: b.id, label: `${b.program_code} · ${num(b.total_credits_required)} credits` }))}
              value={pr}
              onChange={(e) => setPr(e.target.value)}
            />
            {!locked && can('curriculum', 'manage') && (
              <>
                <Select aria-label="Programme to bind" className="w-56" placeholder="Bind a programme…" options={(programs.data?.data ?? []).filter((p) => !(bindings.data?.data ?? []).some((b) => b.program_id === p.id)).map((p) => ({ value: p.id, label: p.code }))} value={bind.program_id} onChange={(e) => setBind((b) => ({ ...b, program_id: e.target.value }))} />
                <Input aria-label="Credits required" type="number" className="w-28" value={bind.total_credits_required} onChange={(e) => setBind((b) => ({ ...b, total_credits_required: Number(e.target.value) }))} />
                <Button variant="outline" disabled={!bind.program_id} onClick={() => createBinding.mutate(undefined, done('Programme bound'))}>
                  Bind
                </Button>
              </>
            )}
          </div>
          {pr ? <StructureEditor key={pr} programRegulationId={pr} courses={(courses.data?.data ?? []).filter((c) => c.status !== 'retired')} /> : <p className="text-sm text-muted-foreground">Bind a programme to edit its structure.</p>}
        </TabsContent>
        {basketsOn && (
          <TabsContent value="baskets">
            {pr ? <BasketsPanel programRegulationId={pr} courses={courses.data?.data ?? []} locked={locked} /> : <p className="text-sm text-muted-foreground">Bind a programme first.</p>}
          </TabsContent>
        )}
        <TabsContent value="diff">
          <DiffView regulationId={id} active={tab === 'diff'} />
        </TabsContent>
      </Tabs>

      <Modal
        open={confirm === 'approve'}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={bosOn ? `Submit ${r.code} for approval?` : `Approve ${r.code}?`}
        description={bosOn ? 'Starts the regulation.approval workflow (dean → academic council). The regulation is approved when the last step approves.' : 'Every bound programme structure must validate. Rules are locked after approval.'}
        footer={<Button onClick={() => approve.mutate(undefined, done(bosOn ? 'Submitted for approval' : 'Regulation approved'))} loading={approve.isPending}>{bosOn ? 'Submit' : 'Approve'}</Button>}
      >
        <p className="text-sm text-muted-foreground">Structures are re-validated on the server; issues are listed if any remain.</p>
      </Modal>
      <Modal
        open={confirm === 'activate'}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={`Activate ${r.code}?`}
        description="Approved courses become active and everything is locked. A regulation it was cloned from becomes superseded."
        footer={<Button onClick={() => activate.mutate(undefined, done('Regulation activated'))} loading={activate.isPending}>Activate</Button>}
      >
        <p className="text-sm">
          <Badge variant="warning">irreversible</Badge> Changes after activation need a clone.
        </p>
      </Modal>
      <Modal
        open={confirm === 'clone'}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={`Clone ${r.code}`}
        description="Deep copy: rules, assessment schemes, courses (same codes), prerequisites, programme structures and baskets. The clone starts as a draft."
        footer={
          <Button
            disabled={!clone.code}
            loading={doClone.isPending}
            onClick={() =>
              doClone.mutate(undefined, {
                onSuccess: (res) => {
                  toast.success(`${res.data.code} created`);
                  setConfirm(null);
                  navigate(`/admin/academics/regulations/${res.data.id}`);
                },
                onError: (e) => toast.error(getApiError(e)),
              })
            }
          >
            Clone
          </Button>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="New code" required placeholder="R2026" value={clone.code} onChange={(e) => setClone((c) => ({ ...c, code: e.target.value.toUpperCase() }))} />
          <FormField label="From admission year" type="number" value={clone.effective_from_admission_year} onChange={(e) => setClone((c) => ({ ...c, effective_from_admission_year: Number(e.target.value) }))} />
          <FormField className="sm:col-span-2" label="Name" value={clone.name} onChange={(e) => setClone((c) => ({ ...c, name: e.target.value }))} />
        </div>
      </Modal>
      <CourseDrawer courseId={drawer} regulationId={id} open={drawer !== null} onClose={() => setDrawer(null)} />
    </div>
  );
}
