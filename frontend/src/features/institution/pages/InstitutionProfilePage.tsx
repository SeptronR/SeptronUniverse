import { useEffect, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { FormField } from '@/components/shared/FormField';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Textarea } from '@/components/ui/Input';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { institutionApi } from '../api';
import { useInstMutation, useProfile } from '../hooks';

const schema = z.object({
  name: z.string().min(2).max(200),
  short_name: z.string().max(60).optional().or(z.literal('')),
  code: z.string().max(20).optional().or(z.literal('')),
  timezone: z.string().min(3).max(60),
  locale: z.string().min(2).max(10),
  currency: z.string().length(3),
  aishe_code: z.string().max(20).optional().or(z.literal('')),
  aicte_pid: z.string().max(30).optional().or(z.literal('')),
  naac_id: z.string().max(30).optional().or(z.literal('')),
  ugc_status: z.string().max(40).optional().or(z.literal('')),
  gstin: z
    .string()
    .regex(/^(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])?$/, 'Invalid GSTIN')
    .optional()
    .or(z.literal('')),
  website_url: z.string().url().optional().or(z.literal('')),
  head_title: z.string().max(60).optional().or(z.literal('')),
  head_name: z.string().max(200).optional().or(z.literal('')),
  vision: z.string().optional().or(z.literal('')),
  mission: z.string().optional().or(z.literal('')),
});
type FormValues = z.infer<typeof schema>;

const blankToNull = (v: FormValues) =>
  Object.fromEntries(Object.entries(v).map(([k, val]) => [k, val === '' ? null : val]));

/** /admin/institution — profile, statutory ids, branding (logo upload + preview). Prompts/03 §03.9. */
export default function InstitutionProfilePage() {
  const { can } = usePermission();
  const profile = useProfile();
  const save = useInstMutation((body: Record<string, unknown>) => institutionApi.updateProfile(body), ['institution']);
  const upload = useInstMutation((f: File) => institutionApi.uploadLogo(f), ['institution']);
  const fileRef = useRef<HTMLInputElement>(null);
  const editable = can('institutions', 'manage');
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });
  const p = profile.data?.data;

  useEffect(() => {
    if (!p) return;
    form.reset(
      Object.fromEntries(Object.keys(schema.shape).map((k) => [k, (p as unknown as Record<string, unknown>)[k] ?? ''])) as FormValues,
    );
  }, [p, form]);

  if (profile.isLoading || !p) return <PageSkeleton />;
  const err = form.formState.errors;

  const onSubmit = form.handleSubmit((values) =>
    save.mutate(
      { ...blankToNull(values), version: p.version },
      { onSuccess: () => toast.success('Profile saved (audited)'), onError: (e) => toast.error(getApiError(e)) },
    ),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Institution"
        description={
          <span className="flex items-center gap-2">
            {p.slug} · {p.institution_type.replace(/_/g, ' ')} · pack {p.regulatory_pack} <Badge variant="outline">{p.status}</Badge>
          </span>
        }
        actions={
          editable && (
            <Button onClick={onSubmit} loading={save.isPending}>
              Save
            </Button>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
              <FormField label="Name" required {...form.register('name')} error={err.name} />
              <FormField label="Short name" {...form.register('short_name')} error={err.short_name} />
              <FormField label="Code" {...form.register('code')} error={err.code} />
              <FormField label="Website" {...form.register('website_url')} error={err.website_url} />
              <FormField
                label="Timezone"
                hint="Cannot change while a term is in progress"
                {...form.register('timezone')}
                error={err.timezone}
              />
              <FormField label="Locale" {...form.register('locale')} error={err.locale} />
              <FormField label="Currency" {...form.register('currency')} error={err.currency} />
              <FormField label="Head title" {...form.register('head_title')} error={err.head_title} />
              <FormField label="Head name" {...form.register('head_name')} error={err.head_name} />
              <div className="sm:col-span-2 grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5 text-sm font-medium">
                  Vision
                  <Textarea rows={2} {...form.register('vision')} />
                </label>
                <label className="space-y-1.5 text-sm font-medium">
                  Mission
                  <Textarea rows={2} {...form.register('mission')} />
                </label>
              </div>
            </fieldset>
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Branding</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex h-28 items-center justify-center rounded-md border bg-muted">
                {p.logo_url ? (
                  <img src={p.logo_url} alt={`${p.name} logo`} className="max-h-24 max-w-full object-contain" />
                ) : (
                  <span className="text-xs text-muted-foreground">No logo</span>
                )}
              </div>
              <div className="rounded-md bg-primary p-3 text-primary-foreground">
                <p className="text-sm font-semibold">{p.short_name ?? p.name}</p>
                <p className="text-xs opacity-80">Header preview (theme from Settings → General)</p>
              </div>
              {editable && (
                <>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f)
                        upload.mutate(f, {
                          onSuccess: () => toast.success('Logo uploaded'),
                          onError: (er) => toast.error(getApiError(er)),
                        });
                    }}
                  />
                  <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()} loading={upload.isPending}>
                    <Upload className="h-4 w-4" /> Upload logo
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Statutory ids</CardTitle>
            </CardHeader>
            <CardContent>
              <fieldset disabled={!editable} className="space-y-3">
                <FormField label="AISHE code" {...form.register('aishe_code')} error={err.aishe_code} />
                <FormField label="AICTE PID" {...form.register('aicte_pid')} error={err.aicte_pid} />
                <FormField label="NAAC id" {...form.register('naac_id')} error={err.naac_id} />
                <FormField label="UGC status" {...form.register('ugc_status')} error={err.ugc_status} />
                <FormField label="GSTIN" {...form.register('gstin')} error={err.gstin} />
              </fieldset>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
