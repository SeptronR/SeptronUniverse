import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Building2, Plus } from 'lucide-react';
import { getApiError, getApiErrorDetails } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { institutionApi } from '../api';
import { useInstMutation, usePlatformInstitutions } from '../hooks';
import { INSTITUTION_TYPES, type OnboardingPayload, type OnboardingResult } from '../types';

const STEPS = ['Institution', 'Admin', 'Plan', 'Pack', 'Demo data', 'Done'];
/** Wizard step that owns a payload path ("institution.slug", "admin.email", "plan_code", …). */
const stepOf = (path: string) => (path.startsWith('institution') ? 0 : path.startsWith('admin') ? 1 : path === 'plan_code' ? 2 : path === 'pack' ? 3 : 4);
const REQUIRED: Record<number, string[]> = { 0: ['institution.name', 'institution.slug'], 1: ['admin.username', 'admin.email', 'admin.display_name'] };

/** 422 details → { "admin.email": "value is not a valid email address…" } (FastAPI ``loc`` or service ``field``). */
function fieldErrorsOf(e: unknown): Record<string, string> {
  const errs = (getApiErrorDetails(e).errors ?? []) as { loc?: (string | number)[]; field?: string; msg?: string; reason?: string }[];
  return Object.fromEntries(
    errs.map((x) => [x.field ?? (x.loc ?? []).filter((l) => l !== 'body').join('.'), (x.msg ?? x.reason ?? 'invalid').replace(/^Value error, /, '')]),
  );
}

/** Onboarding wizard: institution → admin → plan → pack → demo data → done (Prompts/03 §03.9). */
function OnboardingWizard({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [result, setResult] = useState<OnboardingResult | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [data, setData] = useState<OnboardingPayload>({
    institution: { name: '', slug: '', institution_type: 'autonomous_college', timezone: 'Asia/Kolkata' },
    admin: { username: '', email: '', display_name: '' },
    plan_code: 'standard',
    pack: 'IN',
    seed_demo: false,
  });
  const onboard = useInstMutation((b: OnboardingPayload) => institutionApi.onboard(b), ['platform-institutions']);
  const inst = data.institution;
  const clear = (keys: string[]) => setErrors((prev) => Object.fromEntries(Object.entries(prev).filter(([key]) => !keys.includes(key))));
  const setInst = (p: Partial<OnboardingPayload['institution']>) => {
    setData({ ...data, institution: { ...inst, ...p } });
    clear(Object.keys(p).map((key) => `institution.${key}`));
  };
  const setAdmin = (p: Partial<OnboardingPayload['admin']>) => {
    setData({ ...data, admin: { ...data.admin, ...p } });
    clear(Object.keys(p).map((key) => `admin.${key}`));
  };
  const valueAt = (path: string) => path.split('.').reduce<unknown>((o, key) => (o as Record<string, unknown> | undefined)?.[key], data);
  const next = () => {
    const missing = (REQUIRED[step] ?? []).filter((path) => !String(valueAt(path) ?? '').trim());
    if (missing.length) return setErrors({ ...errors, ...Object.fromEntries(missing.map((path) => [path, 'Required'])) });
    setStep(step + 1);
  };

  const submit = () =>
    onboard.mutate(data, {
      onSuccess: (r) => {
        setResult(r.data);
        setStep(5);
        toast.success(`${r.data.institution.name} onboarded`);
      },
      onError: (e) => {
        const fe = fieldErrorsOf(e);
        const paths = Object.keys(fe);
        setErrors(fe);
        if (paths.length) {
          setStep(Math.min(...paths.map(stepOf)));
          toast.error(`${getApiError(e)} — fix the highlighted field${paths.length > 1 ? 's' : ''}`);
        } else toast.error(getApiError(e));
      },
    });

  return (
    <Modal
      open
      size="lg"
      onOpenChange={(o) => !o && onClose()}
      title="Onboard an institution"
      description={`Step ${step + 1} of ${STEPS.length} · ${STEPS[step]}`}
      footer={
        step === 5 ? (
          <Button onClick={() => result && navigate(`/super-admin/institutions/${result.institution.id}`)}>Open institution</Button>
        ) : (
          <>
            {step > 0 && <Button variant="outline" onClick={() => setStep(step - 1)}>Back</Button>}
            {step < 4 ? <Button onClick={next}>Next</Button> : <Button loading={onboard.isPending} onClick={submit}>Create institution</Button>}
          </>
        )
      }
    >
      {step === 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Name" required error={errors['institution.name']} value={inst.name} onChange={(e) => setInst({ name: e.target.value })} />
          <FormField label="Slug" required error={errors['institution.slug']} hint="lowercase, used in URLs" value={inst.slug} onChange={(e) => setInst({ slug: e.target.value.toLowerCase() })} />
          <FormField label="Code" error={errors['institution.code']} value={inst.code ?? ''} onChange={(e) => setInst({ code: e.target.value })} />
          <label className="space-y-1.5 text-sm font-medium">
            Type
            <Select value={inst.institution_type} options={INSTITUTION_TYPES.map((t) => ({ value: t, label: t.replace(/_/g, ' ') }))} onChange={(e) => setInst({ institution_type: e.target.value })} />
          </label>
          <FormField label="Timezone" error={errors['institution.timezone']} value={inst.timezone} onChange={(e) => setInst({ timezone: e.target.value })} />
        </div>
      )}
      {step === 1 && (
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Username" required error={errors['admin.username']} value={data.admin.username} onChange={(e) => setAdmin({ username: e.target.value })} />
          <FormField label="Email" required type="email" error={errors['admin.email']} value={data.admin.email} onChange={(e) => setAdmin({ email: e.target.value })} />
          <FormField label="Display name" required error={errors['admin.display_name']} value={data.admin.display_name} onChange={(e) => setAdmin({ display_name: e.target.value })} />
          <FormField label="Phone" error={errors['admin.phone']} value={data.admin.phone ?? ''} onChange={(e) => setAdmin({ phone: e.target.value })} />
        </div>
      )}
      {step === 2 && (
        <label className="space-y-1.5 text-sm font-medium">
          Plan
          <Select value={data.plan_code} options={['starter', 'standard', 'professional', 'university'].map((p) => ({ value: p, label: p }))} onChange={(e) => setData({ ...data, plan_code: e.target.value })} />
        </label>
      )}
      {step === 3 && (
        <label className="space-y-1.5 text-sm font-medium">
          Regulatory pack
          <Select value={data.pack} options={[{ value: 'IN', label: 'India (UGC / AICTE / NEP 2020)' }, { value: 'GENERIC', label: 'Generic' }]} onChange={(e) => setData({ ...data, pack: e.target.value })} />
        </label>
      )}
      {step === 4 && (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox aria-label="Seed demo data" checked={data.seed_demo} onCheckedChange={(c) => setData({ ...data, seed_demo: c === true })} />
          Seed demo data (current year, terms, a department per college, national holidays) as a background job
        </label>
      )}
      {step === 5 && result && (
        <div className="space-y-2 text-sm">
          <p>
            <b>{result.institution.name}</b> is active: {result.roles_created} roles, plan {result.plan_code} ({result.features_enabled} features).
          </p>
          <p>
            First admin <b>{result.admin_username}</b> — temporary password (shown once, also e-mailed):{' '}
            <code className="rounded bg-muted px-1">{result.admin_temp_password}</code>
          </p>
        </div>
      )}
    </Modal>
  );
}

/** /super-admin/institutions — tenants list + onboarding wizard. */
export default function PlatformInstitutionsPage() {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const list = usePlatformInstitutions({ q: q || undefined, status: status || undefined, page_size: 100 });
  const [wizard, setWizard] = useState(false);
  return (
    <div className="space-y-4">
      <PageHeader title="Institutions" description="Tenants of the platform." actions={<Button onClick={() => setWizard(true)}><Plus className="h-4 w-4" /> Onboard</Button>} />
      <div className="flex gap-2">
        <Input className="w-64" placeholder="Search name or slug…" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-44" placeholder="All statuses" value={status} options={['active', 'pending', 'suspended', 'archived'].map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="p-2">Institution</th>
            <th className="p-2">Type</th>
            <th className="p-2">Plan</th>
            <th className="p-2">Colleges</th>
            <th className="p-2">Users</th>
            <th className="p-2">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {(list.data?.data ?? []).map((i) => (
            <tr key={i.id}>
              <td className="p-2">
                <Link to={`/super-admin/institutions/${i.id}`} className="flex items-center gap-2 font-medium hover:underline">
                  <Building2 className="h-4 w-4" /> {i.name}
                </Link>
                <span className="text-xs text-muted-foreground">{i.slug}</span>
              </td>
              <td className="p-2">{i.institution_type.replace(/_/g, ' ')}</td>
              <td className="p-2">{i.plan_code ?? '—'}</td>
              <td className="p-2">{i.college_count}</td>
              <td className="p-2">{i.user_count}</td>
              <td className="p-2"><StatusBadge status={i.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {wizard && <OnboardingWizard onClose={() => setWizard(false)} />}
    </div>
  );
}
