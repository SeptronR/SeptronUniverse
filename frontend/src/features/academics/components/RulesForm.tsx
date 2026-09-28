import { useEffect, useMemo, useState } from 'react';
import { Info, Save } from 'lucide-react';
import { getApiError, getApiErrorDetails } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Textarea } from '@/components/ui/Input';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { academicsApi } from '../api';
import { useAcMutation, useRulesSchema } from '../hooks';
import type { Regulation } from '../types';

/** Rules grouped for the form; every key of `RegulationRules` is listed exactly once (the rest land in "Other"). */
const GROUPS: { title: string; keys: string[] }[] = [
  { title: 'Attendance', keys: ['attendance_min_pct', 'condonation_floor_pct', 'condonation_fee_paise', 'attendance_mode'] },
  {
    title: 'Passing & grading',
    keys: ['ese_pass_min_pct', 'total_pass_min_pct', 'cia_pass_min_pct', 'include_failed_credits_in_sgpa', 'cgpa_attempt_policy', 'percentage_formula', 'class_rules'],
  },
  { title: 'Grace, valuation & revaluation', keys: ['grace', 'double_valuation', 'reval', 'print_grace_note'] },
  {
    title: 'Progression, exits & credits',
    keys: ['exit_points', 'minor_credits', 'honours_credits', 'mooc_max_credits', 'max_backlogs_for_promotion', 'min_cgpa_for_degree', 'standing_rules', 'mooc_grade_map'],
  },
];
const ENUMS: Record<string, string[]> = {
  attendance_mode: ['course_wise', 'aggregate'],
  cgpa_attempt_policy: ['latest', 'best'],
};

type Draft = Record<string, unknown>;

/** Rules tab — every rules key with its default and help text; JSON editors for the structured keys. */
export function RulesForm({ regulation }: { regulation: Regulation }) {
  const schema = useRulesSchema();
  const [draft, setDraft] = useState<Draft>(regulation.rules);
  const [json, setJson] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useAcMutation((rules: Draft) => academicsApi.updateRegulation(regulation.id, { rules, version: regulation.version }), ['regulations']);
  const locked = regulation.rules_locked;

  useEffect(() => {
    setDraft(regulation.rules);
    setJson({});
  }, [regulation.rules]);

  const help = useMemo(() => Object.fromEntries((schema.data?.data ?? []).map((h) => [h.key, h])), [schema.data]);
  const known = new Set(GROUPS.flatMap((g) => g.keys));
  const others = Object.keys(help).filter((k) => !known.has(k));

  const onSave = () => {
    const out: Draft = { ...draft };
    const parseErrors: Record<string, string> = {};
    for (const [k, text] of Object.entries(json)) {
      try {
        out[k] = JSON.parse(text);
      } catch {
        parseErrors[k] = 'Invalid JSON';
      }
    }
    setErrors(parseErrors);
    if (Object.keys(parseErrors).length) return;
    save.mutate(out, {
      onSuccess: () => toast.success('Rules saved'),
      onError: (e) => {
        const details = getApiErrorDetails(e) as { errors?: { loc: (string | number)[]; msg: string }[] };
        const fieldErrors: Record<string, string> = {};
        for (const err of details.errors ?? []) fieldErrors[String(err.loc[0])] = err.msg;
        setErrors(fieldErrors);
        toast.error(getApiError(e));
      },
    });
  };

  const field = (key: string) => {
    const value = draft[key];
    const def = help[key]?.default;
    const isObject = typeof (value ?? def) === 'object' && (value ?? def) !== null;
    const id = `rule-${key}`;
    let control;
    if (ENUMS[key]) {
      control = (
        <select id={id} disabled={locked} className="h-9 w-full rounded-md border bg-card px-2 text-sm" value={String(value ?? def)} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}>
          {ENUMS[key].map((o) => (
            <option key={o} value={o}>
              {o.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      );
    } else if (typeof (value ?? def) === 'boolean') {
      control = <Checkbox id={id} disabled={locked} checked={Boolean(value ?? def)} onCheckedChange={(c) => setDraft((d) => ({ ...d, [key]: c === true }))} />;
    } else if (isObject) {
      control = (
        <Textarea
          id={id}
          disabled={locked}
          className="font-mono text-xs"
          rows={Math.min(8, JSON.stringify(value ?? def, null, 2).split('\n').length)}
          value={json[key] ?? JSON.stringify(value ?? def, null, 2)}
          onChange={(e) => setJson((j) => ({ ...j, [key]: e.target.value }))}
        />
      );
    } else if (typeof (value ?? def) === 'number' || value === null || def === null) {
      control = (
        <Input
          id={id}
          type="number"
          step="any"
          disabled={locked}
          value={value === null || value === undefined ? '' : String(value)}
          placeholder={def === null ? 'no rule' : String(def)}
          onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value === '' ? null : Number(e.target.value) }))}
        />
      );
    } else {
      control = <Input id={id} disabled={locked} value={String(value ?? '')} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))} />;
    }
    return (
      <div key={key} className={isObject ? 'space-y-1 sm:col-span-2' : 'space-y-1'}>
        <label htmlFor={id} className="flex items-center gap-1 text-sm font-medium">
          {key.replace(/_/g, ' ')}
          {help[key]?.description && (
            <span title={`${help[key].description} (default: ${JSON.stringify(def)})`}>
              <Info className="h-3.5 w-3.5 text-muted-foreground" />
            </span>
          )}
        </label>
        {control}
        {errors[key] ? (
          <p role="alert" className="text-xs text-destructive">
            {errors[key]}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">{help[key]?.description}</p>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {[...GROUPS, ...(others.length ? [{ title: 'Other', keys: others }] : [])].map((g) => (
        <Card key={g.title}>
          <CardHeader>
            <CardTitle className="text-base">{g.title}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">{g.keys.filter((k) => k in help).map(field)}</CardContent>
        </Card>
      ))}
      {!locked && (
        <div className="flex justify-end">
          <Button onClick={onSave} loading={save.isPending}>
            <Save className="h-4 w-4" /> Save rules
          </Button>
        </div>
      )}
    </div>
  );
}
