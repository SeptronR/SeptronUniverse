import { useMemo, useState } from 'react';
import { AlertTriangle, ArrowRight, Plus, Save, Trash2 } from 'lucide-react';
import { getApiError, getApiErrorCode, getApiErrorDetails } from '@/api/axios';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { academicsApi } from '../api';
import { useAcMutation } from '../hooks';
import type { Course, Prerequisite } from '../types';

type Item = { related_course_id: string; relation: Prerequisite['relation']; is_hard: boolean };
const RELATIONS: Prerequisite['relation'][] = ['prerequisite', 'corequisite', 'antirequisite'];

/** Would adding ``course → related`` close a prerequisite cycle? (client preview of the server's DFS check) */
function cyclePath(course: Course, items: Item[], all: Course[]): string | null {
  const edges = new Map<string, string[]>();
  for (const c of all) {
    if (c.id === course.id) continue;
    edges.set(c.id, c.prerequisites.filter((p) => p.relation === 'prerequisite').map((p) => p.related_course_id));
  }
  edges.set(course.id, items.filter((i) => i.relation === 'prerequisite').map((i) => i.related_course_id));
  const code = (id: string) => all.find((c) => c.id === id)?.code ?? '?';
  const stack: [string, string[]][] = (edges.get(course.id) ?? []).map((n) => [n, [course.id, n]]);
  const seen = new Set<string>();
  while (stack.length) {
    const [node, path] = stack.pop()!;
    if (node === course.id) return path.map(code).join(' → ');
    if (seen.has(node)) continue;
    seen.add(node);
    for (const next of edges.get(node) ?? []) stack.push([next, [...path, next]]);
  }
  return null;
}

/** Prerequisite graph editor: related courses of the same regulation; blocks cycles with a message. */
export function PrerequisiteEditor({ course, regulationCourses, disabled }: { course: Course; regulationCourses: Course[]; disabled?: boolean }) {
  const [items, setItems] = useState<Item[]>(course.prerequisites.map((p) => ({ related_course_id: p.related_course_id, relation: p.relation, is_hard: p.is_hard })));
  const save = useAcMutation((body: Item[]) => academicsApi.prerequisites(course.id, body), ['courses']);
  const others = regulationCourses.filter((c) => c.id !== course.id);
  const cycle = useMemo(() => cyclePath(course, items, regulationCourses), [course, items, regulationCourses]);
  const code = (id: string) => others.find((c) => c.id === id)?.code ?? '—';

  const onSave = () =>
    save.mutate(items, {
      onSuccess: () => toast.success('Prerequisites saved'),
      onError: (e) => toast.error(getApiErrorCode(e) === 'RULE_VIOLATION' ? `Cycle: ${String(getApiErrorDetails(e).path ?? '')}` : getApiError(e)),
    });

  return (
    <div className="space-y-2">
      {items.length === 0 && <p className="text-sm text-muted-foreground">No prerequisites.</p>}
      {items.map((it, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
          <Badge variant="outline">{course.code}</Badge>
          <Select
            aria-label="Relation"
            className="w-36"
            disabled={disabled}
            options={RELATIONS.map((r) => ({ value: r, label: r }))}
            value={it.relation}
            onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, relation: e.target.value as Item['relation'] } : x)))}
          />
          <ArrowRight className="h-4 w-4 text-muted-foreground" />
          <Select
            aria-label="Related course"
            className="w-64"
            disabled={disabled}
            options={others.map((c) => ({ value: c.id, label: `${c.code} · ${c.title}` }))}
            value={it.related_course_id}
            onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, related_course_id: e.target.value } : x)))}
          />
          {!disabled && (
            <Button size="sm" variant="ghost" aria-label={`Remove ${code(it.related_course_id)}`} onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}>
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      ))}
      {cycle && (
        <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" /> This would create a prerequisite cycle: {cycle}
        </p>
      )}
      {!disabled && (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={others.length === 0} onClick={() => setItems((xs) => [...xs, { related_course_id: others[0]?.id ?? '', relation: 'prerequisite', is_hard: true }])}>
            <Plus className="h-4 w-4" /> Add
          </Button>
          <Button size="sm" onClick={onSave} loading={save.isPending} disabled={!!cycle}>
            <Save className="h-4 w-4" /> Save prerequisites
          </Button>
        </div>
      )}
    </div>
  );
}
