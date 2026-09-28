import { useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { academicsApi } from '../api';
import { useAcMutation, useBaskets } from '../hooks';
import { ALLOCATION_MODES, BASKET_TYPES, label, num, type Basket, type Course } from '../types';

type Draft = {
  code: string;
  name: string;
  basket_type: string;
  term_number: number | '';
  min_choose: number;
  max_choose: number;
  credits_required: number;
  allocation_mode: string;
  course_ids: string[];
};
const empty: Draft = { code: '', name: '', basket_type: 'program_elective', term_number: '', min_choose: 1, max_choose: 1, credits_required: 3, allocation_mode: 'priority_cgpa', course_ids: [] };

/** Baskets tab — PE / OE / minor / honours / MOOC / vertical baskets with allocation mode and course membership. */
export function BasketsPanel({ programRegulationId, courses, locked }: { programRegulationId: string; courses: Course[]; locked: boolean }) {
  const list = useBaskets({ program_regulation_id: programRegulationId, page_size: 100 });
  const [editing, setEditing] = useState<Basket | 'new' | null>(null);
  const [d, setD] = useState<Draft>(empty);
  const roots = ['elective-baskets', 'program-regulations'];
  const create = useAcMutation((b: Draft) => academicsApi.createBasket({ ...b, program_regulation_id: programRegulationId, term_number: b.term_number || null }), roots);
  const update = useAcMutation(async ({ id, b }: { id: string; b: Draft }) => {
    const { course_ids, code: _code, ...rest } = b;
    await academicsApi.updateBasket(id, { ...rest, term_number: rest.term_number || null });
    return academicsApi.basketCourses(id, course_ids.map((course_id) => ({ course_id })));
  }, roots);
  const remove = useAcMutation((id: string) => academicsApi.deleteBasket(id), roots);
  const electives = courses.filter((c) => c.status !== 'retired');

  const open = (b: Basket | 'new') => {
    setEditing(b);
    setD(
      b === 'new'
        ? empty
        : {
            code: b.code,
            name: b.name,
            basket_type: b.basket_type,
            term_number: b.term_number ?? '',
            min_choose: b.min_choose,
            max_choose: b.max_choose,
            credits_required: num(b.credits_required),
            allocation_mode: b.allocation_mode,
            course_ids: b.courses.map((c) => c.course_id),
          },
    );
  };
  const onSave = () => {
    if (d.min_choose > d.max_choose) return toast.error('min choose must be ≤ max choose');
    const opts = { onSuccess: () => { toast.success('Basket saved'); setEditing(null); }, onError: (e: unknown) => toast.error(getApiError(e)) };
    if (editing === 'new') create.mutate(d, opts);
    else if (editing) update.mutate({ id: editing.id, b: d }, opts);
  };

  return (
    <div className="space-y-3">
      {!locked && (
        <div className="flex justify-end">
          <Button onClick={() => open('new')}>
            <Plus className="h-4 w-4" /> New basket
          </Button>
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {(list.data?.data ?? []).map((b) => (
          <Card key={b.id}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">
                {b.code} · {b.name}
              </CardTitle>
              {!locked && (
                <span className="flex gap-1">
                  <Button size="sm" variant="ghost" aria-label={`Edit ${b.code}`} onClick={() => open(b)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="ghost" aria-label={`Delete ${b.code}`} onClick={() => remove.mutate(b.id, { onError: (e) => toast.error(getApiError(e)) })}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </span>
              )}
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p className="flex flex-wrap gap-1">
                <Badge variant="outline">{label(b.basket_type)}</Badge>
                <Badge variant="secondary">term {b.term_number ?? 'any'}</Badge>
                <Badge variant="secondary">
                  choose {b.min_choose}–{b.max_choose}
                </Badge>
                <Badge variant="secondary">{num(b.credits_required)} credits</Badge>
                <Badge variant="info">{label(b.allocation_mode)}</Badge>
              </p>
              <ul className="text-muted-foreground">
                {b.courses.map((c) => (
                  <li key={c.course_id}>
                    {c.code} · {c.title} ({num(c.credits)})
                  </li>
                ))}
                {b.courses.length === 0 && <li>No courses yet.</li>}
              </ul>
            </CardContent>
          </Card>
        ))}
        {list.data?.data.length === 0 && <p className="text-sm text-muted-foreground">No baskets for this programme.</p>}
      </div>
      <Modal open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} size="lg" title={editing === 'new' ? 'New basket' : `Edit ${d.code}`} footer={<Button onClick={onSave} loading={create.isPending || update.isPending}>Save</Button>}>
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Code" required disabled={editing !== 'new'} value={d.code} onChange={(e) => setD({ ...d, code: e.target.value.toUpperCase() })} />
          <FormField className="sm:col-span-2" label="Name" required value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} />
          <label className="space-y-1.5 text-sm font-medium">
            Type
            <Select options={BASKET_TYPES.map((t) => ({ value: t, label: label(t) }))} value={d.basket_type} onChange={(e) => setD({ ...d, basket_type: e.target.value })} />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Allocation
            <Select options={ALLOCATION_MODES.map((t) => ({ value: t, label: label(t) }))} value={d.allocation_mode} onChange={(e) => setD({ ...d, allocation_mode: e.target.value })} />
          </label>
          <FormField label="Term" type="number" value={d.term_number} onChange={(e) => setD({ ...d, term_number: e.target.value ? Number(e.target.value) : '' })} />
          <FormField label="Min choose" type="number" value={d.min_choose} onChange={(e) => setD({ ...d, min_choose: Number(e.target.value) })} />
          <FormField label="Max choose" type="number" value={d.max_choose} onChange={(e) => setD({ ...d, max_choose: Number(e.target.value) })} error={d.min_choose > d.max_choose ? 'min ≤ max' : undefined} />
          <FormField label="Credits required" type="number" value={d.credits_required} onChange={(e) => setD({ ...d, credits_required: Number(e.target.value) })} />
        </div>
        <fieldset className="mt-3 max-h-64 space-y-1 overflow-auto rounded-md border p-2">
          <legend className="px-1 text-sm font-medium">Courses (this regulation)</legend>
          {electives.map((c) => (
            <label key={c.id} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={d.course_ids.includes(c.id)}
                onCheckedChange={(on) => setD({ ...d, course_ids: on === true ? [...d.course_ids, c.id] : d.course_ids.filter((x) => x !== c.id) })}
              />
              {c.code} · {c.title} <span className="text-muted-foreground">({label(c.course_type)}, {num(c.credits)})</span>
            </label>
          ))}
        </fieldset>
      </Modal>
    </div>
  );
}
