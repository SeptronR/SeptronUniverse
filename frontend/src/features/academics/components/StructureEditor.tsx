import { useEffect, useMemo, useState } from 'react';
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { AlertTriangle, CheckCircle2, GripVertical, Plus, Save, ShieldCheck, Trash2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { cn } from '@/utils/cn';
import { academicsApi } from '../api';
import { useAcMutation, useStructure } from '../hooks';
import { BASKET_TYPES, label, num, type Course, type Structure, type StructureValidation } from '../types';
import { CreditMeter } from './CreditMeter';

interface TermDraft {
  term_number: number;
  min_credits: number;
  normal_credits: number;
  max_credits: number;
  is_exit_point: boolean;
}
interface BasketDraft {
  code: string;
  name: string;
  basket_type: string;
  term_number: number | null;
  min_choose: number;
  max_choose: number;
  credits_required: number;
}
type Placement = { term: number; basket: string | null };

function fromStructure(s: Structure) {
  const terms: TermDraft[] = Array.from({ length: s.total_terms }, (_, i) => {
    const t = s.terms.find((x) => x.term_number === i + 1);
    return {
      term_number: i + 1,
      min_credits: num(t?.min_credits),
      normal_credits: num(t?.normal_credits),
      max_credits: num(t?.max_credits ?? 30),
      is_exit_point: t?.is_exit_point ?? false,
    };
  });
  const placements: Record<string, Placement> = {};
  for (const c of s.courses) placements[c.course_id] = { term: c.term_number, basket: c.basket_code ?? null };
  const baskets: BasketDraft[] = s.baskets.map((b) => ({
    code: b.code,
    name: b.name,
    basket_type: b.basket_type,
    term_number: b.term_number,
    min_choose: b.min_choose,
    max_choose: b.max_choose,
    credits_required: num(b.credits_required),
  }));
  return { terms, placements, baskets };
}

function DraggableCourse({ course, placement, baskets, onBasket, onRemove, disabled }: {
  course: Course;
  placement?: Placement;
  baskets: BasketDraft[];
  onBasket?: (code: string | null) => void;
  onRemove?: () => void;
  disabled: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: course.id, disabled });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  const termBaskets = baskets.filter((b) => b.term_number === null || b.term_number === placement?.term);
  return (
    <div ref={setNodeRef} style={style} className={cn('rounded-md border bg-card p-2 text-xs shadow-xs', isDragging && 'z-10 opacity-70')}>
      <div className="flex items-start gap-1">
        {!disabled && (
          <button type="button" className="cursor-grab text-muted-foreground" aria-label={`Drag ${course.code}`} {...listeners} {...attributes}>
            <GripVertical className="h-3.5 w-3.5" />
          </button>
        )}
        <div className="min-w-0 flex-1">
          <p className="font-semibold">
            {course.code} <span className="font-normal text-muted-foreground">{course.ltpc}</span>
          </p>
          <p className="truncate text-muted-foreground" title={course.title}>
            {course.title}
          </p>
        </div>
        {onRemove && !disabled && (
          <button type="button" onClick={onRemove} aria-label={`Remove ${course.code}`} className="text-muted-foreground hover:text-destructive">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {placement && (
        <div className="mt-1 flex items-center gap-1">
          {disabled ? (
            placement.basket && <Badge variant="info">{placement.basket}</Badge>
          ) : (
            <select
              aria-label={`Basket of ${course.code}`}
              className="h-6 rounded border bg-card px-1 text-[11px]"
              value={placement.basket ?? ''}
              onChange={(e) => onBasket?.(e.target.value || null)}
            >
              <option value="">mandatory</option>
              {termBaskets.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.code}
                </option>
              ))}
            </select>
          )}
          {course.status !== 'approved' && course.status !== 'active' && <Badge variant="warning">{course.status}</Badge>}
        </div>
      )}
    </div>
  );
}

function TermColumn({ term, children, over }: { term: number | 'pool'; children: React.ReactNode; over?: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: `term-${term}` });
  return (
    <div ref={setNodeRef} className={cn('min-h-24 space-y-1.5 rounded-md border border-dashed p-2', (isOver || over) && 'border-primary bg-primary/5')}>
      {children}
    </div>
  );
}

/** Structure tab — per-term editor with drag-drop, credit meters, basket chips, exit toggles and the validate panel. */
export function StructureEditor({ programRegulationId, courses }: { programRegulationId: string; courses: Course[] }) {
  const structure = useStructure(programRegulationId);
  const [terms, setTerms] = useState<TermDraft[]>([]);
  const [placements, setPlacements] = useState<Record<string, Placement>>({});
  const [baskets, setBaskets] = useState<BasketDraft[]>([]);
  const [validation, setValidation] = useState<StructureValidation | null>(null);
  const [dirty, setDirty] = useState(false);
  const save = useAcMutation((body: Record<string, unknown>) => academicsApi.replaceStructure(programRegulationId, body), ['program-regulations', 'elective-baskets']);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const s = structure.data?.data;
  const locked = !!s?.locked;

  useEffect(() => {
    if (!s) return;
    const d = fromStructure(s);
    setTerms(d.terms);
    setPlacements(d.placements);
    setBaskets(d.baskets);
    setDirty(false);
  }, [s]);

  const byId = useMemo(() => Object.fromEntries(courses.map((c) => [c.id, c])), [courses]);
  const load = (term: number) => {
    let total = 0;
    for (const [cid, p] of Object.entries(placements)) {
      const c = byId[cid];
      if (p.term === term && !p.basket && c?.is_credit_bearing) total += num(c.credits);
    }
    for (const b of baskets) if (b.term_number === term) total += b.credits_required;
    return total;
  };
  const grand = terms.reduce((acc, t) => acc + load(t.term_number), 0) + baskets.filter((b) => b.term_number === null).reduce((a, b) => a + b.credits_required, 0);
  const exitTerms = new Set((s?.exit_points ?? []).map((e) => e.after_term));

  const touch = () => setDirty(true);
  const onDragEnd = (e: DragEndEvent) => {
    const target = String(e.over?.id ?? '');
    const cid = String(e.active.id);
    if (!target) return;
    if (target === 'term-pool') {
      setPlacements((p) => {
        const next = { ...p };
        delete next[cid];
        return next;
      });
    } else {
      const term = Number(target.replace('term-', ''));
      setPlacements((p) => ({ ...p, [cid]: { term, basket: p[cid]?.term === term ? p[cid].basket : null } }));
    }
    touch();
  };

  const onSave = () => {
    const body = {
      version: s?.version,
      terms: terms.map((t) => ({ ...t })),
      courses: Object.entries(placements).map(([course_id, p], i) => ({ term_number: p.term, course_id, basket_code: p.basket, sequence: i + 1 })),
      baskets: baskets.map((b) => ({
        ...b,
        course_ids: Object.entries(placements)
          .filter(([, p]) => p.basket === b.code)
          .map(([cid]) => cid),
      })),
    };
    save.mutate(body, {
      onSuccess: async () => {
        toast.success('Structure saved');
        setDirty(false);
        await onValidate();
      },
      onError: (e) => toast.error(getApiError(e)),
    });
  };
  const onValidate = async () => {
    try {
      const r = await academicsApi.validateStructure(programRegulationId, true);
      setValidation(r.data);
    } catch (e) {
      toast.error(getApiError(e));
    }
  };

  if (structure.isLoading || !s) return <p className="text-sm text-muted-foreground">Loading structure…</p>;
  const pool = courses.filter((c) => !placements[c.id] && c.status !== 'retired');

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm">
          Planned <span className="font-semibold">{grand}</span> of <span className="font-semibold">{num(s.total_credits_required)}</span> required credits
          {grand !== num(s.total_credits_required) && <Badge variant="warning" className="ml-2">mismatch</Badge>}
        </p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onValidate}>
            <ShieldCheck className="h-4 w-4" /> Validate
          </Button>
          {!locked && (
            <Button onClick={onSave} loading={save.isPending} disabled={!dirty}>
              <Save className="h-4 w-4" /> Save structure
            </Button>
          )}
        </div>
      </div>

      {validation && (
        <div className={cn('rounded-md border p-3 text-sm', validation.valid && validation.issues.length === 0 ? 'border-status-approved/40' : 'border-status-pending/50')} role="status">
          {validation.issues.length === 0 ? (
            <p className="flex items-center gap-2 text-status-approved">
              <CheckCircle2 className="h-4 w-4" /> Structure is valid for approval ({num(validation.total)} credits).
            </p>
          ) : (
            <ul className="space-y-1">
              {validation.issues.map((i, n) => (
                <li key={n} className="flex items-start gap-2">
                  <AlertTriangle className={cn('mt-0.5 h-4 w-4 shrink-0', i.severity === 'error' ? 'text-status-rejected' : 'text-status-pending')} />
                  <span>
                    <Badge variant={i.severity === 'error' ? 'destructive' : 'warning'}>{i.severity}</Badge> {i.message}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!locked && (
        <div className="rounded-md border p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Baskets</h3>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setBaskets((b) => [...b, { code: `PE-${b.length + 1}`, name: `Elective ${b.length + 1}`, basket_type: 'program_elective', term_number: 1, min_choose: 1, max_choose: 1, credits_required: 3 }]);
                touch();
              }}
            >
              <Plus className="h-4 w-4" /> Basket
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {baskets.map((b, i) => (
              <div key={i} className="flex flex-wrap items-center gap-1 rounded-md border bg-muted/40 p-1.5 text-xs">
                <Input aria-label="Basket code" className="h-7 w-20 text-xs" value={b.code} onChange={(e) => { const code = e.target.value.toUpperCase(); setBaskets((bs) => bs.map((x, j) => (j === i ? { ...x, code } : x))); touch(); }} />
                <select aria-label="Basket type" className="h-7 rounded border bg-card px-1" value={b.basket_type} onChange={(e) => { setBaskets((bs) => bs.map((x, j) => (j === i ? { ...x, basket_type: e.target.value } : x))); touch(); }}>
                  {BASKET_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {label(t)}
                    </option>
                  ))}
                </select>
                term
                <Input aria-label="Basket term" type="number" className="h-7 w-14 text-xs" value={b.term_number ?? ''} onChange={(e) => { const v = e.target.value ? Number(e.target.value) : null; setBaskets((bs) => bs.map((x, j) => (j === i ? { ...x, term_number: v } : x))); touch(); }} />
                credits
                <Input aria-label="Basket credits" type="number" className="h-7 w-14 text-xs" value={b.credits_required} onChange={(e) => { setBaskets((bs) => bs.map((x, j) => (j === i ? { ...x, credits_required: Number(e.target.value) } : x))); touch(); }} />
                <button type="button" aria-label={`Remove basket ${b.code}`} onClick={() => { setBaskets((bs) => bs.filter((_, j) => j !== i)); setPlacements((p) => Object.fromEntries(Object.entries(p).map(([k, v]) => [k, v.basket === b.code ? { ...v, basket: null } : v]))); touch(); }}>
                  <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              </div>
            ))}
            {baskets.length === 0 && <p className="text-xs text-muted-foreground">No baskets — add one for programme / open electives.</p>}
          </div>
        </div>
      )}

      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className={cn('grid gap-3', !locked && 'lg:grid-cols-[220px_1fr]')}>
          {!locked && (
            <div>
              <h3 className="mb-1 text-sm font-semibold">Unplaced courses ({pool.length})</h3>
              <TermColumn term="pool">
                {pool.map((c) => (
                  <DraggableCourse key={c.id} course={c} baskets={baskets} disabled={locked} />
                ))}
                {pool.length === 0 && <p className="text-xs text-muted-foreground">Every course is placed.</p>}
              </TermColumn>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {terms.map((t, i) => {
              const placed = Object.entries(placements).filter(([, p]) => p.term === t.term_number);
              return (
                <section key={t.term_number} className="space-y-2 rounded-md border p-2" aria-label={`Term ${t.term_number}`}>
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">{label(s.term_pattern)} {t.term_number}</h3>
                    <label className="flex items-center gap-1 text-xs" title={exitTerms.has(t.term_number) ? 'rules.exit_points lists an exit after this term' : 'rules.exit_points has no exit after this term'}>
                      <Checkbox disabled={locked || !exitTerms.has(t.term_number)} checked={t.is_exit_point} onCheckedChange={(c) => { setTerms((ts) => ts.map((x, j) => (j === i ? { ...x, is_exit_point: c === true } : x))); touch(); }} />
                      exit
                    </label>
                  </div>
                  <CreditMeter load={load(t.term_number)} min={t.min_credits} normal={t.normal_credits} max={t.max_credits} />
                  {!locked && (
                    <div className="grid grid-cols-3 gap-1">
                      {(['min_credits', 'normal_credits', 'max_credits'] as const).map((k) => (
                        <Input key={k} aria-label={`${k} of term ${t.term_number}`} type="number" className="h-7 text-xs" value={t[k]} onChange={(e) => { setTerms((ts) => ts.map((x, j) => (j === i ? { ...x, [k]: Number(e.target.value) } : x))); touch(); }} />
                      ))}
                    </div>
                  )}
                  <TermColumn term={t.term_number}>
                    {placed.map(([cid, p]) =>
                      byId[cid] ? (
                        <DraggableCourse
                          key={cid}
                          course={byId[cid]}
                          placement={p}
                          baskets={baskets}
                          disabled={locked}
                          onBasket={(code) => { setPlacements((pl) => ({ ...pl, [cid]: { ...pl[cid], basket: code } })); touch(); }}
                          onRemove={() => { setPlacements((pl) => { const n = { ...pl }; delete n[cid]; return n; }); touch(); }}
                        />
                      ) : null,
                    )}
                    {placed.length === 0 && <p className="text-xs text-muted-foreground">{locked ? 'No courses.' : 'Drop courses here.'}</p>}
                  </TermColumn>
                </section>
              );
            })}
          </div>
        </div>
      </DndContext>
      {locked && <p className="text-xs text-muted-foreground">The regulation is {s.regulation_status}: the structure is read-only — clone the regulation to change it.</p>}
    </div>
  );
}
