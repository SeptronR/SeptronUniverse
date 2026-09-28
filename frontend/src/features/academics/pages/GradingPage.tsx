import { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Plus, Trash2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { cn } from '@/utils/cn';
import { academicsApi } from '../api';
import { useAcMutation, useRegulations, useScales, useSchemes } from '../hooks';
import { COMPONENT_CATEGORIES, label, num, type AssessmentComponent, type AssessmentScheme, type GradeRange, type GradingScale } from '../types';

/** Client mirror of GradingService rule 1: cover 0–100, no gaps/overlaps (inclusive bounds), exactly one fail grade. */
function rangeIssues(ranges: GradeRange[]): string[] {
  const items = [...ranges].sort((a, b) => b.min_pct - a.min_pct);
  const out: string[] = [];
  if (new Set(items.map((r) => r.grade.toUpperCase())).size !== items.length) out.push('Grades must be unique');
  let upper: number | null = null;
  for (const r of items) {
    const max = r.max_pct ?? (upper === null ? 100 : upper);
    if (max < r.min_pct) out.push(`${r.grade}: max below min`);
    if (upper === null && max !== 100) out.push('The highest grade must reach 100');
    if (upper !== null) {
      if (upper - max < 0) out.push(`${r.grade} overlaps the next grade`);
      else if (upper - max > 1) out.push(`Gap between ${max} and ${upper}`);
    }
    upper = r.min_pct;
  }
  if (items.length && items[items.length - 1].min_pct !== 0) out.push('The lowest grade must start at 0');
  const fails = items.filter((r) => (r.is_fail ?? r.points === 0)).length;
  if (fails !== 1) out.push(`Exactly one fail grade is required (found ${fails})`);
  return out;
}

function ScaleEditor({ scale, onClose }: { scale: GradingScale | 'new'; onClose: () => void }) {
  const [name, setName] = useState(scale === 'new' ? '' : scale.name);
  const [ranges, setRanges] = useState<GradeRange[]>(
    scale === 'new'
      ? [
          { grade: 'O', min_pct: 90, max_pct: 100, points: 10 },
          { grade: 'A', min_pct: 75, max_pct: 89, points: 8 },
          { grade: 'B', min_pct: 50, max_pct: 74, points: 6 },
          { grade: 'F', min_pct: 0, max_pct: 49, points: 0 },
        ]
      : scale.ranges.map((r) => ({ ...r })),
  );
  const issues = rangeIssues(ranges);
  const save = useAcMutation(
    () => (scale === 'new' ? academicsApi.createScale({ name, ranges }) : academicsApi.updateScale(scale.id, { name, ranges, version: scale.version })),
    ['grading-scales'],
  );
  const set = (i: number, patch: Partial<GradeRange>) => setRanges((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const sorted = [...ranges].sort((a, b) => a.min_pct - b.min_pct);
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      size="lg"
      title={scale === 'new' ? 'New grading scale' : `Edit ${scale.name}`}
      footer={
        <Button disabled={issues.length > 0 || name.length < 2} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => { toast.success('Scale saved'); onClose(); }, onError: (e) => toast.error(getApiError(e)) })}>
          Save
        </Button>
      }
    >
      <FormField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
      <table className="mt-3 w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th>Grade</th>
            <th>Min %</th>
            <th>Max %</th>
            <th>Points</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {ranges.map((r, i) => (
            <tr key={i}>
              <td><Input aria-label="Grade" className="h-8 w-16" value={r.grade} onChange={(e) => set(i, { grade: e.target.value })} /></td>
              <td><Input aria-label="Min %" type="number" className="h-8 w-20" value={r.min_pct} onChange={(e) => set(i, { min_pct: Number(e.target.value) })} /></td>
              <td><Input aria-label="Max %" type="number" className="h-8 w-20" value={r.max_pct ?? ''} onChange={(e) => set(i, { max_pct: e.target.value === '' ? null : Number(e.target.value) })} /></td>
              <td><Input aria-label="Points" type="number" className="h-8 w-20" value={r.points} onChange={(e) => set(i, { points: Number(e.target.value) })} /></td>
              <td>
                <Button size="sm" variant="ghost" aria-label={`Remove ${r.grade}`} onClick={() => setRanges((rs) => rs.filter((_, j) => j !== i))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Button className="mt-2" size="sm" variant="outline" onClick={() => setRanges((rs) => [...rs, { grade: '', min_pct: 0, max_pct: 0, points: 0 }])}>
        <Plus className="h-4 w-4" /> Grade
      </Button>
      <div className="mt-3" aria-label="Coverage preview">
        <div className="flex h-6 w-full overflow-hidden rounded border text-[10px]">
          {sorted.map((r, i) => {
            const max = r.max_pct ?? sorted[i + 1]?.min_pct ?? 100;
            return (
              <div key={i} className={cn('flex items-center justify-center border-r', (r.is_fail ?? r.points === 0) ? 'bg-status-rejected/20' : 'bg-status-approved/20')} style={{ width: `${Math.max(0, max - r.min_pct + 1)}%` }} title={`${r.grade}: ${r.min_pct}–${max}`}>
                {r.grade}
              </div>
            );
          })}
        </div>
      </div>
      {issues.length ? (
        <ul className="mt-2 space-y-0.5 text-xs text-destructive" role="alert">
          {issues.map((m) => (
            <li key={m} className="flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" /> {m}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 flex items-center gap-1 text-xs text-status-approved"><CheckCircle2 className="h-3.5 w-3.5" /> Covers 0–100 with one fail grade.</p>
      )}
    </Modal>
  );
}

/** Client mirror of rule 2: Σ scaled_to of CIA components (best-of groups count `take`) = cia_max. */
function ciaTotal(components: AssessmentComponent[]) {
  const seen = new Set<string>();
  let total = 0;
  for (const c of components.filter((x) => x.category === 'cia')) {
    const value = num(c.scaled_to ?? c.max_marks);
    if (c.best_of) {
      const key = c.best_of.group || c.code;
      if (seen.has(key)) continue;
      seen.add(key);
      const members = components.filter((m) => m.best_of && (m.best_of.group || m.code) === key);
      total += Math.max(...members.map((m) => num(m.scaled_to ?? m.max_marks))) * Math.min(c.best_of.take, members.length);
    } else total += value;
  }
  return total;
}

function SchemeEditor({ scheme, regulationId, onClose }: { scheme: AssessmentScheme | 'new'; regulationId: string; onClose: () => void }) {
  const base = scheme === 'new' ? { code: '', name: '', cia_weight: 40, ese_weight: 60, cia_max: 40, ese_max: 60 } : scheme;
  const [head, setHead] = useState({ code: base.code, name: base.name, cia_weight: base.cia_weight, ese_weight: base.ese_weight, cia_max: base.cia_max, ese_max: base.ese_max });
  const [components, setComponents] = useState<AssessmentComponent[]>(scheme === 'new' ? [{ code: 'CAT1', name: 'CAT 1', category: 'cia', max_marks: 50, scaled_to: 20, sequence: 1 }] : scheme.components.map((c) => ({ ...c })));
  const cia = ciaTotal(components);
  const errors = [
    head.cia_weight + head.ese_weight !== 100 && `weights add up to ${head.cia_weight + head.ese_weight}, not 100`,
    components.some((c) => c.category === 'cia') && cia !== head.cia_max && `Σ CIA scaled_to = ${cia}, cia_max = ${head.cia_max}`,
    components.some((c) => c.best_of && c.best_of.take > c.best_of.of) && 'best_of.take must be ≤ of',
  ].filter(Boolean) as string[];
  const save = useAcMutation(async () => {
    const comps = components.map((c, i) => ({ ...c, id: undefined, sequence: i + 1, scaled_to: c.scaled_to === '' ? null : c.scaled_to }));
    if (scheme === 'new') return academicsApi.createScheme({ ...head, regulation_id: regulationId, components: comps });
    await academicsApi.updateScheme(scheme.id, { ...head, code: undefined, version: scheme.version });
    return academicsApi.schemeComponents(scheme.id, comps);
  }, ['assessment-schemes']);
  const set = (i: number, patch: Partial<AssessmentComponent>) => setComponents((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      size="xl"
      title={scheme === 'new' ? 'New assessment scheme' : `Edit ${scheme.code}`}
      footer={<Button disabled={errors.length > 0} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => { toast.success('Scheme saved'); onClose(); }, onError: (e) => toast.error(getApiError(e)) })}>Save</Button>}
    >
      <div className="grid gap-3 sm:grid-cols-6">
        <FormField label="Code" disabled={scheme !== 'new'} value={head.code} onChange={(e) => setHead({ ...head, code: e.target.value.toUpperCase() })} />
        <FormField className="sm:col-span-5" label="Name" value={head.name} onChange={(e) => setHead({ ...head, name: e.target.value })} />
        {(['cia_weight', 'ese_weight', 'cia_max', 'ese_max'] as const).map((k) => (
          <FormField key={k} label={label(k)} type="number" value={head[k]} onChange={(e) => setHead({ ...head, [k]: Number(e.target.value) })} />
        ))}
      </div>
      <table className="mt-3 w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th>Code</th><th>Name</th><th>Category</th><th>Max</th><th>Scaled to</th><th>Best of (take/of/group)</th><th />
          </tr>
        </thead>
        <tbody>
          {components.map((c, i) => (
            <tr key={i}>
              <td><Input aria-label="Code" className="h-8 w-20" value={c.code} onChange={(e) => set(i, { code: e.target.value.toUpperCase() })} /></td>
              <td><Input aria-label="Name" className="h-8" value={c.name} onChange={(e) => set(i, { name: e.target.value })} /></td>
              <td><Select aria-label="Category" className="h-8" options={COMPONENT_CATEGORIES.map((x) => ({ value: x, label: label(x) }))} value={c.category} onChange={(e) => set(i, { category: e.target.value })} /></td>
              <td><Input aria-label="Max marks" type="number" className="h-8 w-16" value={c.max_marks} onChange={(e) => set(i, { max_marks: Number(e.target.value) })} /></td>
              <td><Input aria-label="Scaled to" type="number" className="h-8 w-16" value={c.scaled_to ?? ''} onChange={(e) => set(i, { scaled_to: e.target.value === '' ? null : Number(e.target.value) })} /></td>
              <td className="flex gap-1">
                <Input aria-label="Take" type="number" className="h-8 w-12" value={c.best_of?.take ?? ''} onChange={(e) => set(i, { best_of: e.target.value ? { take: Number(e.target.value), of: c.best_of?.of ?? Number(e.target.value), group: c.best_of?.group ?? null } : null })} />
                <Input aria-label="Of" type="number" className="h-8 w-12" value={c.best_of?.of ?? ''} onChange={(e) => c.best_of && set(i, { best_of: { ...c.best_of, of: Number(e.target.value) } })} />
                <Input aria-label="Group" className="h-8 w-16" value={c.best_of?.group ?? ''} onChange={(e) => c.best_of && set(i, { best_of: { ...c.best_of, group: e.target.value || null } })} />
              </td>
              <td><Button size="sm" variant="ghost" aria-label={`Remove ${c.code}`} onClick={() => setComponents((cs) => cs.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <Button className="mt-2" size="sm" variant="outline" onClick={() => setComponents((cs) => [...cs, { code: `C${cs.length + 1}`, name: '', category: 'cia', max_marks: 50, scaled_to: 10, sequence: cs.length + 1 }])}>
        <Plus className="h-4 w-4" /> Component
      </Button>
      <p className={cn('mt-2 text-xs', errors.length ? 'text-destructive' : 'text-status-approved')} role={errors.length ? 'alert' : 'status'}>
        {errors.length ? errors.join(' · ') : `Σ CIA scaled_to = ${cia} = cia_max`}
      </p>
    </Modal>
  );
}

/** /admin/academics/grading — grading scales (range editor + preview) and assessment schemes (component weights). */
export default function GradingPage() {
  const { can } = usePermission();
  const configure = can('exams', 'configure');
  const scales = useScales({ page_size: 100 });
  const regulations = useRegulations({ page_size: 100 });
  const [regId, setRegId] = useState('');
  const effectiveReg = regId || regulations.data?.data.find((r) => r.status === 'draft' || r.status === 'active')?.id || '';
  const schemes = useSchemes({ regulation_id: effectiveReg, page_size: 100 }, !!effectiveReg);
  const [scale, setScale] = useState<GradingScale | 'new' | null>(null);
  const [scheme, setScheme] = useState<AssessmentScheme | 'new' | null>(null);
  const reg = useMemo(() => regulations.data?.data.find((r) => r.id === effectiveReg), [regulations.data, effectiveReg]);
  const schemeLocked = reg?.structure_locked;

  return (
    <div className="space-y-4">
      <PageHeader title="Grading & assessment schemes" description="Configuration consumed by internal assessment, examinations and results." />
      <Tabs defaultValue="scales">
        <TabsList>
          <TabsTrigger value="scales">Grading scales</TabsTrigger>
          <TabsTrigger value="schemes">Assessment schemes</TabsTrigger>
        </TabsList>
        <TabsContent value="scales" className="space-y-3">
          {configure && (
            <div className="flex justify-end">
              <Button onClick={() => setScale('new')}><Plus className="h-4 w-4" /> New scale</Button>
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            {(scales.data?.data ?? []).map((s) => (
              <Card key={s.id} className={configure ? 'cursor-pointer' : undefined} onClick={() => configure && setScale(s)}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    {s.name} {s.is_default && <Badge variant="info">default</Badge>}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-1 text-xs">
                  {[...s.ranges].sort((a, b) => b.min_pct - a.min_pct).map((r) => (
                    <Badge key={r.grade} variant={(r.is_fail ?? r.points === 0) ? 'destructive' : 'secondary'}>
                      {r.grade} ≥{r.min_pct} · {r.points}
                    </Badge>
                  ))}
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
        <TabsContent value="schemes" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Select aria-label="Regulation" className="w-64" options={(regulations.data?.data ?? []).map((r) => ({ value: r.id, label: `${r.code} (${r.status})` }))} value={effectiveReg} onChange={(e) => setRegId(e.target.value)} />
            {configure && !schemeLocked && effectiveReg && <Button onClick={() => setScheme('new')}><Plus className="h-4 w-4" /> New scheme</Button>}
          </div>
          {schemeLocked && <p className="text-sm text-muted-foreground">{reg?.code} is {reg?.status}: its schemes are read-only.</p>}
          <div className="grid gap-3 md:grid-cols-2">
            {(schemes.data?.data ?? []).map((s) => (
              <Card key={s.id} className={configure && !schemeLocked ? 'cursor-pointer' : undefined} onClick={() => configure && !schemeLocked && setScheme(s)}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    {s.code} {s.is_default && <Badge variant="info">default</Badge>}
                  </CardTitle>
                  <p className="text-xs text-muted-foreground">{s.name} · CIA {s.cia_weight} / ESE {s.ese_weight} · {s.applies_to_course_types.map(label).join(', ') || 'default'}</p>
                </CardHeader>
                <CardContent className="text-xs">
                  {s.components.map((c) => (
                    <p key={c.code}>
                      {c.code} · {c.name} — {c.max_marks}{c.scaled_to !== null ? ` → ${num(c.scaled_to)}` : ''} {c.best_of && <Badge variant="outline">best {c.best_of.take}/{c.best_of.of}</Badge>}
                    </p>
                  ))}
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
      </Tabs>
      {scale && <ScaleEditor scale={scale} onClose={() => setScale(null)} />}
      {scheme && effectiveReg && <SchemeEditor scheme={scheme} regulationId={effectiveReg} onClose={() => setScheme(null)} />}
    </div>
  );
}
