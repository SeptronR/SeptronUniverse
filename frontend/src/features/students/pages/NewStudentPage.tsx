import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useFieldArray, useForm, type FieldPath } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Check, Plus, Trash2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FieldWrapper, FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useBatches, usePrograms } from '@/features/academics/hooks';
import { cn } from '@/utils/cn';
import { studentsApi } from '../api';
import { Field } from '../components/shared';
import { useStudentMutation } from '../hooks';
import { ENTRY_TYPES, GENDERS, RELATIONS, label, type StudentCreateResult } from '../types';

const PHONE = /^\+?[0-9]{10,15}$/;
const opt = (s: z.ZodString) => s.optional().or(z.literal(''));

const schema = z.object({
  first_name: z.string().trim().min(1, 'Required').max(100),
  middle_name: opt(z.string().max(100)),
  last_name: opt(z.string().max(100)),
  dob: z.string().min(1, 'Required').refine((d) => new Date(d) < new Date(), 'Must be in the past'),
  gender: z.enum(['M', 'F', 'O'], { errorMap: () => ({ message: 'Choose' }) }),
  category: opt(z.string().max(20)),
  blood_group: opt(z.string().max(5)),
  phone: opt(z.string().regex(PHONE, '10–15 digits')),
  email: opt(z.string().email('Invalid e-mail')),
  aadhaar: opt(z.string().regex(/^\d{12}$/, '12 digits')),
  apaar_id: opt(z.string().regex(/^\d{12}$/, '12 digits')),
  program_id: z.string().min(1, 'Choose a programme'),
  admission_year: z.coerce.number().int().min(1990).max(2100),
  batch_id: z.string().optional(),
  section: opt(z.string().max(10)),
  entry_type: z.enum(['regular', 'lateral', 'migrated', 'readmission']),
  admission_quota: opt(z.string().max(30)),
  admission_date: z.string().optional(),
  registration_number: opt(z.string().regex(/^[A-Za-z0-9/-]{1,30}$/, 'Letters, digits, / or -')),
  guardians: z
    .array(
      z.object({
        relation: z.enum(['father', 'mother', 'guardian', 'spouse', 'other']),
        name: z.string().trim().min(2, 'Required'),
        phone: opt(z.string().regex(PHONE, '10–15 digits')),
        email: opt(z.string().email('Invalid e-mail')),
        is_primary: z.boolean(),
        portal_access: z.boolean(),
      }),
    )
    .max(6),
});
type Values = z.infer<typeof schema>;
type DocDraft = { doc_type: string; file: File; expires_on: string };

const STEPS: { title: string; fields: FieldPath<Values>[] }[] = [
  { title: 'Personal', fields: ['first_name', 'middle_name', 'last_name', 'dob', 'gender', 'category', 'blood_group', 'phone', 'email', 'aadhaar', 'apaar_id'] },
  { title: 'Academic', fields: ['program_id', 'admission_year', 'batch_id', 'section', 'entry_type', 'admission_quota', 'admission_date', 'registration_number'] },
  { title: 'Guardians', fields: ['guardians'] },
  { title: 'Documents', fields: [] },
  { title: 'Review', fields: [] },
];

const clean = (o: Record<string, unknown>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== '' && v !== undefined && v !== null));

/** /admin/students/new — 5-step wizard (personal → academic → guardians → documents → review); batch, regulation,
 *  section and registration number are derived by the API when left blank. */
export default function NewStudentPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [docs, setDocs] = useState<DocDraft[]>([]);
  const [doc, setDoc] = useState<{ doc_type: string; file: File | null; expires_on: string }>({ doc_type: '', file: null, expires_on: '' });
  const [result, setResult] = useState<StudentCreateResult | null>(null);
  const year = new Date().getFullYear();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    mode: 'onTouched',
    defaultValues: { entry_type: 'regular', admission_year: year, guardians: [{ relation: 'father', name: '', phone: '', email: '', is_primary: true, portal_access: true }] },
  });
  const { register, formState: { errors }, watch, control } = form;
  const guardians = useFieldArray({ control, name: 'guardians' });
  const programs = usePrograms({ page_size: 200, status: 'active' });
  const programId = watch('program_id');
  const admissionYear = Number(watch('admission_year'));
  const batches = useBatches({ page_size: 50, program_id: programId || undefined });
  const batch = (batches.data?.data ?? []).find((b) => b.program_id === programId && b.admission_year === admissionYear && b.entry_type === 'regular');
  const program = (programs.data?.data ?? []).find((p) => p.id === programId);
  const create = useStudentMutation((body: Record<string, unknown>) => studentsApi.create(body));

  const next = async () => {
    if (await form.trigger(STEPS[step].fields)) setStep((s) => s + 1);
  };
  const submit = form.handleSubmit(async (v) => {
    const body = clean({
      ...v,
      batch_id: batch?.id,
      guardians: v.guardians.map((g) => clean({ ...g, create_portal_user: g.portal_access })),
    });
    create.mutate(body, {
      onSuccess: async (r) => {
        const id = r.data.student.id;
        for (const d of docs) {
          try {
            await studentsApi.addDocument(id, d.file, { doc_type: d.doc_type, expires_on: d.expires_on || undefined });
          } catch (e) {
            toast.error(`${d.doc_type}: ${getApiError(e)}`);
          }
        }
        setResult(r.data);
      },
      onError: (e) => toast.error(getApiError(e)),
    });
  });
  const v = watch();

  return (
    <div className="space-y-4">
      <PageHeader title="New student" breadcrumbs={[{ label: 'Students', to: '/admin/students' }, { label: 'New' }]} />
      <ol className="flex flex-wrap gap-2" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className={cn('flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm', i === step ? 'border-primary bg-primary/10 font-medium' : i < step ? 'text-muted-foreground' : 'opacity-60')} aria-current={i === step ? 'step' : undefined}>
            {i < step ? <Check className="h-3.5 w-3.5" /> : <span className="text-xs">{i + 1}</span>} {s.title}
          </li>
        ))}
      </ol>
      <Card>
        <CardContent className="pt-5 sm:pt-5">
          {step === 0 && (
            <div className="grid gap-3 sm:grid-cols-3">
              <FormField label="First name" required {...register('first_name')} error={errors.first_name} />
              <FormField label="Middle name" {...register('middle_name')} error={errors.middle_name} />
              <FormField label="Last name" {...register('last_name')} error={errors.last_name} />
              <FormField label="Date of birth" type="date" required {...register('dob')} error={errors.dob} />
              <FieldWrapper label="Gender" required error={errors.gender}>
                {(id) => <Select id={id} placeholder="Select…" options={GENDERS} {...register('gender')} />}
              </FieldWrapper>
              <FormField label="Category" hint="Pack codes, e.g. GEN, OBC, SC, ST, EWS" {...register('category')} error={errors.category} />
              <FormField label="Blood group" {...register('blood_group')} error={errors.blood_group} />
              <FormField label="Phone" {...register('phone')} error={errors.phone} />
              <FormField label="E-mail" type="email" {...register('email')} error={errors.email} />
              <FormField label="Aadhaar" inputMode="numeric" {...register('aadhaar')} error={errors.aadhaar} />
              <FormField label="APAAR id" inputMode="numeric" hint="Checksum validated by the API" {...register('apaar_id')} error={errors.apaar_id} />
            </div>
          )}
          {step === 1 && (
            <div className="grid gap-3 sm:grid-cols-3">
              <FieldWrapper label="Programme" required error={errors.program_id} className="sm:col-span-2">
                {(id) => <Select id={id} placeholder="Select…" options={(programs.data?.data ?? []).map((p) => ({ value: p.id, label: `${p.code} · ${p.name}` }))} {...register('program_id')} />}
              </FieldWrapper>
              <FormField label="Admission year" type="number" required {...register('admission_year')} error={errors.admission_year} />
              <div className="rounded-md border bg-muted/40 p-3 text-sm sm:col-span-3">
                {!programId ? (
                  'Choose a programme to see the batch.'
                ) : batch ? (
                  <>Batch <b>{batch.code}</b> (term {batch.current_term_number}, regulation from the batch). Sections: {batch.sections.map((s) => s.name).join(', ') || '—'}.</>
                ) : (
                  <>No batch for {program?.code} {admissionYear} yet — it is created with the active regulation.</>
                )}
              </div>
              <FieldWrapper label="Section" hint="Blank = least-filled section">
                {(id) => <Select id={id} placeholder="Auto" options={(batch?.sections ?? []).map((s) => ({ value: s.name, label: s.name }))} {...register('section')} />}
              </FieldWrapper>
              <FieldWrapper label="Entry type">
                {(id) => <Select id={id} options={ENTRY_TYPES.map((t) => ({ value: t, label: label(t) }))} {...register('entry_type')} />}
              </FieldWrapper>
              <FormField label="Admission quota" {...register('admission_quota')} error={errors.admission_quota} />
              <FormField label="Admission date" type="date" {...register('admission_date')} />
              <FormField label="Registration no." hint="Blank = generated from the number sequence" {...register('registration_number')} error={errors.registration_number} />
            </div>
          )}
          {step === 2 && (
            <div className="space-y-3">
              {guardians.fields.map((g, i) => (
                <div key={g.id} className="grid items-end gap-3 rounded-md border p-3 sm:grid-cols-6">
                  <FieldWrapper label="Relation">
                    {(id) => <Select id={id} options={RELATIONS.map((r) => ({ value: r, label: label(r) }))} {...register(`guardians.${i}.relation`)} />}
                  </FieldWrapper>
                  <FormField label="Name" required className="sm:col-span-2" {...register(`guardians.${i}.name`)} error={errors.guardians?.[i]?.name} />
                  <FormField label="Phone" {...register(`guardians.${i}.phone`)} error={errors.guardians?.[i]?.phone} />
                  <FormField label="E-mail" {...register(`guardians.${i}.email`)} error={errors.guardians?.[i]?.email} />
                  <Button variant="ghost" size="icon" aria-label="Remove guardian" onClick={() => guardians.remove(i)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                  <label className="flex items-center gap-1.5 text-sm sm:col-span-2"><input type="checkbox" {...register(`guardians.${i}.is_primary`)} /> Primary contact</label>
                  <label className="flex items-center gap-1.5 text-sm sm:col-span-4"><input type="checkbox" {...register(`guardians.${i}.portal_access`)} /> Parent-portal account (reused when the phone / e-mail already has one)</label>
                </div>
              ))}
              {guardians.fields.length < 6 && (
                <Button variant="outline" onClick={() => guardians.append({ relation: 'mother', name: '', phone: '', email: '', is_primary: false, portal_access: true })}>
                  <Plus className="h-4 w-4" /> Add guardian
                </Button>
              )}
            </div>
          )}
          {step === 3 && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Documents are uploaded right after the student is created (optional; more can be added from the 360° page).</p>
              <div className="flex flex-wrap items-end gap-2">
                <FormField label="Document type" placeholder="e.g. tc, marks_12, photo_id" value={doc.doc_type} onChange={(e) => setDoc({ ...doc, doc_type: e.target.value })} />
                <FormField label="Expires on" type="date" value={doc.expires_on} onChange={(e) => setDoc({ ...doc, expires_on: e.target.value })} />
                <input type="file" aria-label="Document file" accept=".pdf,image/*" onChange={(e) => setDoc({ ...doc, file: e.target.files?.[0] ?? null })} />
                <Button variant="outline" disabled={!doc.doc_type || !doc.file} onClick={() => { setDocs([...docs, { doc_type: doc.doc_type, file: doc.file!, expires_on: doc.expires_on }]); setDoc({ doc_type: '', file: null, expires_on: '' }); }}>
                  <Plus className="h-4 w-4" /> Add
                </Button>
              </div>
              <ul className="space-y-1 text-sm">
                {docs.map((d, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="font-medium">{d.doc_type}</span> {d.file.name} {d.expires_on && <span className="text-muted-foreground">expires {d.expires_on}</span>}
                    <Button variant="ghost" size="icon" aria-label="Remove document" onClick={() => setDocs(docs.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {step === 4 && (
            <dl className="grid gap-3 sm:grid-cols-3">
              <Field k="Name" v={[v.first_name, v.middle_name, v.last_name].filter(Boolean).join(' ')} />
              <Field k="Date of birth" v={v.dob} />
              <Field k="Gender" v={GENDERS.find((g) => g.value === v.gender)?.label} />
              <Field k="Programme" v={program?.code} />
              <Field k="Batch" v={batch?.code ?? `${program?.code ?? ''} ${v.admission_year} (new)`} />
              <Field k="Section" v={v.section || 'auto'} />
              <Field k="Entry" v={label(v.entry_type)} />
              <Field k="Registration no." v={v.registration_number || 'generated'} />
              <Field k="Category" v={v.category} />
              <Field k="Guardians" v={v.guardians.map((g) => `${g.name} (${g.relation})`).join(', ')} />
              <Field k="Documents" v={docs.map((d) => d.doc_type).join(', ')} />
            </dl>
          )}
          <div className="mt-5 flex justify-between">
            <Button variant="outline" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>Back</Button>
            {step < STEPS.length - 1 ? <Button onClick={next}>Next</Button> : <Button loading={create.isPending} onClick={submit}>Create student</Button>}
          </div>
        </CardContent>
      </Card>

      <Modal
        open={result !== null}
        onOpenChange={(o) => { if (!o && result) navigate(`/admin/students/${result.student.id}`); }}
        title={`Created ${result?.student.registration_number ?? ''}`}
        description="Hand these over securely — passwords are shown only once."
        footer={<Button onClick={() => result && navigate(`/admin/students/${result.student.id}`)}>Open 360°</Button>}
      >
        <div className="space-y-1 text-sm">
          <p>Student <span className="font-mono font-semibold">{result?.username ?? '—'}</span> / <span className="font-mono font-semibold">{result?.temp_password ?? '—'}</span></p>
          {result?.guardian_accounts.map((g) => (
            <p key={g.guardian_id}>Guardian <span className="font-mono font-semibold">{g.username ?? '—'}</span> {g.reused ? '(existing account reused)' : <>/ <span className="font-mono font-semibold">{g.temp_password ?? '—'}</span></>}</p>
          ))}
        </div>
      </Modal>
    </div>
  );
}
