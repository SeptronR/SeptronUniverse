import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Lock } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useDepartments } from '@/features/institution/hooks';
import { academicsApi } from '../api';
import { useAcMutation, useCourse, useCourses } from '../hooks';
import { COURSE_TYPES, label, num, type Course, type SyllabusUnit } from '../types';
import { PrerequisiteEditor } from './PrerequisiteEditor';
import { SyllabusEditor } from './SyllabusEditor';

const schema = z.object({
  regulation_id: z.string().uuid('Pick a regulation'),
  department_id: z.string().uuid('Pick a department'),
  code: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$/, '1–30 letters/digits'),
  title: z.string().min(2).max(200),
  course_type: z.enum(COURSE_TYPES),
  lecture_hours: z.coerce.number().int().min(0).max(40),
  tutorial_hours: z.coerce.number().int().min(0).max(40),
  practical_hours: z.coerce.number().int().min(0).max(40),
  credits: z.coerce.number().min(0).max(40),
  is_public_catalog: z.boolean(),
});
type FormValues = z.infer<typeof schema>;

/** Course detail drawer: L-T-P-C, syllabus units, prerequisites (cycle-checked) and status moves. */
export function CourseDrawer({ courseId, regulationId, open, onClose }: { courseId: string | 'new' | null; regulationId?: string; open: boolean; onClose: () => void }) {
  const { can } = usePermission();
  const isNew = courseId === 'new';
  const detail = useCourse(!isNew && courseId ? courseId : undefined);
  const course = detail.data?.data;
  const regId = course?.regulation_id ?? regulationId;
  const siblings = useCourses({ regulation_id: regId, page_size: 200 }, !!regId);
  const departments = useDepartments({ scope: 'all', page_size: 200 });
  const [syllabus, setSyllabus] = useState<SyllabusUnit[]>([]);
  const create = useAcMutation((b: Record<string, unknown>) => academicsApi.createCourse(b), ['courses', 'regulations']);
  const update = useAcMutation((b: Record<string, unknown>) => academicsApi.updateCourse(course!.id, b), ['courses']);
  const status = useAcMutation((s: string) => academicsApi.courseStatus(course!.id, s), ['courses']);
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });
  const editable = isNew || !!course?.can_edit;

  useEffect(() => {
    if (!open) return;
    if (isNew) {
      form.reset({ regulation_id: regulationId ?? '', department_id: '', code: '', title: '', course_type: 'core', lecture_hours: 3, tutorial_hours: 0, practical_hours: 0, credits: 3, is_public_catalog: true });
      setSyllabus([]);
    } else if (course) {
      form.reset({
        regulation_id: course.regulation_id,
        department_id: course.department_id,
        code: course.code,
        title: course.title,
        course_type: course.course_type as FormValues['course_type'],
        lecture_hours: course.lecture_hours,
        tutorial_hours: course.tutorial_hours,
        practical_hours: course.practical_hours,
        credits: num(course.credits),
        is_public_catalog: course.is_public_catalog,
      });
      setSyllabus(course.syllabus ?? []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isNew, course?.id, course?.version]);

  const onSubmit = form.handleSubmit((v) => {
    const done = { onSuccess: () => { toast.success(isNew ? 'Course created' : 'Course saved'); if (isNew) onClose(); }, onError: (e: unknown) => toast.error(getApiError(e)) };
    if (isNew) create.mutate({ ...v, syllabus }, done);
    else {
      const { regulation_id: _r, code: _c, ...rest } = v;
      update.mutate({ ...rest, syllabus, version: course!.version }, done);
    }
  });
  const move = (s: string) => status.mutate(s, { onSuccess: () => toast.success(`Course ${s}`), onError: (e) => toast.error(getApiError(e)) });
  const [l, t, p] = [form.watch('lecture_hours'), form.watch('tutorial_hours'), form.watch('practical_hours')];

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="xl" title={isNew ? 'New course' : `${course?.code ?? ''} · ${course?.title ?? ''}`} description={course ? `${course.regulation_code} · ${course.department_code} · L-T-P-C ${course.ltpc}` : undefined}>
      {course && !course.can_edit && (
        <p className="mb-3 flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm">
          <Lock className="h-4 w-4" /> {course.regulation_status === 'active' || course.regulation_status === 'superseded' ? `Regulation ${course.regulation_code} is ${course.regulation_status} — clone it to change this course.` : 'Read-only for you (department scope).'}
        </p>
      )}
      <Tabs defaultValue="details">
        <TabsList>
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="syllabus">Syllabus</TabsTrigger>
          {!isNew && <TabsTrigger value="prereq">Prerequisites</TabsTrigger>}
        </TabsList>
        <TabsContent value="details">
          <form className="grid gap-3 sm:grid-cols-4" onSubmit={onSubmit}>
            <FormField className="sm:col-span-1" label="Code" required disabled={!isNew} {...form.register('code')} error={form.formState.errors.code} />
            <FormField className="sm:col-span-3" label="Title" required disabled={!editable} {...form.register('title')} error={form.formState.errors.title} />
            <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
              Type
              <Select disabled={!editable} options={COURSE_TYPES.map((c) => ({ value: c, label: label(c) }))} {...form.register('course_type')} />
            </label>
            <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
              Owning department
              <Select disabled={!editable} placeholder="Select…" options={(departments.data?.data ?? []).map((d) => ({ value: d.id, label: `${d.code} · ${d.name}` }))} {...form.register('department_id')} />
              {form.formState.errors.department_id && <span className="text-xs text-destructive">{form.formState.errors.department_id.message}</span>}
            </label>
            <FormField label="Lecture (L)" type="number" disabled={!editable} {...form.register('lecture_hours')} />
            <FormField label="Tutorial (T)" type="number" disabled={!editable} {...form.register('tutorial_hours')} />
            <FormField label="Practical (P)" type="number" disabled={!editable} {...form.register('practical_hours')} />
            <FormField label="Credits (C)" type="number" step="0.5" disabled={!editable} {...form.register('credits')} error={form.formState.errors.credits} />
            <p className="text-xs text-muted-foreground sm:col-span-4">
              Contact hours per week: {Number(l || 0) + Number(t || 0) + Number(p || 0)} · audit / mandatory non-credit courses carry no credits.
            </p>
            <label className="flex items-center gap-2 text-sm sm:col-span-4">
              <Checkbox disabled={!editable} checked={form.watch('is_public_catalog')} onCheckedChange={(c) => form.setValue('is_public_catalog', c === true)} /> Show in the public course catalogue
            </label>
          </form>
        </TabsContent>
        <TabsContent value="syllabus">
          <SyllabusEditor value={syllabus} onChange={setSyllabus} disabled={!editable} />
        </TabsContent>
        {course && (
          <TabsContent value="prereq">
            <PrerequisiteEditor key={`${course.id}-${course.version}`} course={course} regulationCourses={siblings.data?.data ?? ([] as Course[])} disabled={!course.can_edit} />
          </TabsContent>
        )}
      </Tabs>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3">
        <div className="flex items-center gap-2 text-sm">
          {course && <StatusBadge status={course.status} />}
          {course?.status === 'draft' && can('courses', 'approve') && course.regulation_status !== 'active' && (
            <Button size="sm" variant="outline" onClick={() => move('approved')}>Approve</Button>
          )}
          {course?.status === 'approved' && course.can_edit && <Button size="sm" variant="outline" onClick={() => move('draft')}>Back to draft</Button>}
          {course && course.status !== 'retired' && can('courses', 'update') && <Button size="sm" variant="ghost" onClick={() => move('retired')}>Retire</Button>}
        </div>
        {editable && (
          <Button onClick={onSubmit} loading={create.isPending || update.isPending}>
            {isNew ? 'Create course' : 'Save'}
          </Button>
        )}
      </div>
    </Modal>
  );
}
