import { useState } from 'react';
import { Plus, UserCog, Users } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { StaffPicker } from '@/features/institution/components/StaffPicker';
import { academicsApi } from '../api';
import { useAcMutation, useBatches, usePrograms, useProgramRegulations } from '../hooks';
import type { Batch, BatchSection } from '../types';

/** /admin/academics/batches — batches per programme / admission year with sections and class advisors. */
export default function BatchesPage() {
  const { can } = usePermission();
  const [params, setParams] = useState<{ page: number; page_size: number; scope?: string; program_id?: string; q?: string }>({ page: 1, page_size: 50 });
  const list = useBatches(params);
  const programs = usePrograms({ page_size: 200, scope: 'all' });
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ program_id: '', program_regulation_id: '', admission_year: new Date().getFullYear(), section_count: 2, section_capacity: 60 });
  const bindings = useProgramRegulations({ program_id: draft.program_id, page_size: 20 }, !!draft.program_id);
  const [sectionsFor, setSectionsFor] = useState<Batch | null>(null);
  const [sectionText, setSectionText] = useState('');
  const [advisorFor, setAdvisorFor] = useState<{ batch: Batch; section: BatchSection } | null>(null);
  const create = useAcMutation(() => academicsApi.createBatch(draft), ['batches']);
  const sections = useAcMutation(({ id, rows }: { id: string; rows: { name: string; capacity: number | null }[] }) => academicsApi.replaceSections(id, rows), ['batches']);
  const advisor = useAcMutation(({ b, s, u }: { b: string; s: string; u: string }) => academicsApi.assignAdvisor(b, s, u), ['batches', 'users']);
  const manage = can('batches', 'manage');

  if (list.isLoading) return <PageSkeleton />;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Batches"
        description="An admission cohort of a programme, pinned to a programme-regulation; students join sections in Phase 07."
        actions={
          can('batches', 'create') && (
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> New batch
            </Button>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope} onChange={(scope) => setParams((p) => ({ ...p, scope }))} />
        <Select className="w-56" placeholder="All programmes" options={(programs.data?.data ?? []).map((p) => ({ value: p.id, label: `${p.code} · ${p.name}` }))} value={params.program_id ?? ''} onChange={(e) => setParams((p) => ({ ...p, program_id: e.target.value || undefined }))} />
        <Input className="w-48" placeholder="Search code…" value={params.q ?? ''} onChange={(e) => setParams((p) => ({ ...p, q: e.target.value || undefined }))} />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(list.data?.data ?? []).map((b) => (
          <Card key={b.id}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                <span>{b.code}</span>
                <StatusBadge status={b.status} />
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                {b.name} · {b.regulation_code} · term {b.current_term_number} · graduates {b.expected_graduation_year ?? '—'} {b.entry_type === 'lateral' && <Badge variant="outline">lateral</Badge>}
              </p>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {b.sections.map((s) => (
                <div key={s.id} className="flex items-center justify-between gap-2 rounded-md border px-2 py-1">
                  <span className="flex items-center gap-2">
                    <Users className="h-4 w-4 text-muted-foreground" /> Section {s.name}
                    <span className="text-xs text-muted-foreground">cap {s.capacity ?? '—'}</span>
                  </span>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    {s.class_advisor_name ?? 'no advisor'}
                    {manage && (
                      <Button size="sm" variant="ghost" aria-label={`Assign the class advisor of ${b.code} ${s.name}`} onClick={() => setAdvisorFor({ batch: b, section: s })}>
                        <UserCog className="h-4 w-4" />
                      </Button>
                    )}
                  </span>
                </div>
              ))}
              {can('batches', 'update') && (
                <Button size="sm" variant="outline" onClick={() => { setSectionsFor(b); setSectionText(b.sections.map((s) => `${s.name}:${s.capacity ?? ''}`).join(', ')); }}>
                  Edit sections
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
        {list.data?.data.length === 0 && <p className="text-sm text-muted-foreground">No batches.</p>}
      </div>

      <Modal open={creating} onOpenChange={setCreating} title="New batch" footer={<Button disabled={!draft.program_regulation_id} loading={create.isPending} onClick={() => create.mutate(undefined, { onSuccess: () => { toast.success('Batch created'); setCreating(false); }, onError: (e) => toast.error(getApiError(e)) })}>Create</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
            Programme
            <Select placeholder="Select…" options={(programs.data?.data ?? []).map((p) => ({ value: p.id, label: `${p.code} · ${p.name}` }))} value={draft.program_id} onChange={(e) => setDraft({ ...draft, program_id: e.target.value, program_regulation_id: '' })} />
          </label>
          <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
            Regulation
            <Select placeholder="Select…" options={(bindings.data?.data ?? []).map((b) => ({ value: b.id, label: `${b.regulation_code} (${b.regulation_status})` }))} value={draft.program_regulation_id} onChange={(e) => setDraft({ ...draft, program_regulation_id: e.target.value })} />
          </label>
          <FormField label="Admission year" type="number" value={draft.admission_year} onChange={(e) => setDraft({ ...draft, admission_year: Number(e.target.value) })} />
          <FormField label="Sections (A…)" type="number" min={1} max={26} value={draft.section_count} onChange={(e) => setDraft({ ...draft, section_count: Number(e.target.value) })} />
          <FormField label="Capacity per section" type="number" value={draft.section_capacity} onChange={(e) => setDraft({ ...draft, section_capacity: Number(e.target.value) })} />
        </div>
      </Modal>

      <Modal
        open={sectionsFor !== null}
        onOpenChange={(o) => !o && setSectionsFor(null)}
        title={`Sections of ${sectionsFor?.code ?? ''}`}
        description="Comma-separated NAME:capacity, e.g. A:60, B:60, C:45. Removing a section with a class advisor is refused."
        footer={
          <Button
            loading={sections.isPending}
            onClick={() =>
              sectionsFor &&
              sections.mutate(
                {
                  id: sectionsFor.id,
                  rows: sectionText.split(',').map((x) => x.trim()).filter(Boolean).map((x) => { const [name, cap] = x.split(':'); return { name: name.trim().toUpperCase(), capacity: cap ? Number(cap) : null }; }),
                },
                { onSuccess: () => { toast.success('Sections saved'); setSectionsFor(null); }, onError: (e) => toast.error(getApiError(e)) },
              )
            }
          >
            Save
          </Button>
        }
      >
        <Input aria-label="Sections" value={sectionText} onChange={(e) => setSectionText(e.target.value)} />
      </Modal>

      <Modal open={advisorFor !== null} onOpenChange={(o) => !o && setAdvisorFor(null)} title={`Class advisor · ${advisorFor?.batch.code ?? ''} ${advisorFor?.section.name ?? ''}`} description="Grants class_advisor scoped to this section (@offering); the previous advisor's assignment is revoked.">
        <StaffPicker
          onPick={(userId, name) =>
            advisorFor &&
            advisor.mutate(
              { b: advisorFor.batch.id, s: advisorFor.section.id, u: userId },
              { onSuccess: () => { toast.success(`${name} is the class advisor of ${advisorFor.section.name}`); setAdvisorFor(null); }, onError: (e) => toast.error(getApiError(e)) },
            )
          }
        />
      </Modal>
    </div>
  );
}
