import { useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { schemaToZod, type JsonSchema } from './reportParams';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

export type { JsonSchema };

const sel = 'h-9 w-full rounded-md border bg-background px-2 text-sm';

/**
 * Parameter form generated from a report's `params_schema`; `x-picker` fields (college / department / programme /
 * batch / term / offering …) accept an id — the API narrows any pick outside the caller's scopes silently.
 */
export function ReportParamsForm({
  schema,
  defaults,
  submitLabel = 'Run',
  onSubmit,
  busy,
  extra,
}: {
  schema: JsonSchema;
  defaults?: Record<string, unknown>;
  submitLabel?: string;
  onSubmit: (params: Record<string, unknown>) => void;
  busy?: boolean;
  extra?: React.ReactNode;
}) {
  const zs = useMemo(() => schemaToZod(schema), [schema]);
  const form = useForm<Record<string, Any>>({ resolver: zodResolver(zs), defaultValues: defaults ?? {} });
  const props = Object.entries(schema.properties ?? {}).filter(([, s]) => !s['x-dev']);
  const errors = form.formState.errors as Record<string, Any>;
  return (
    <form
      className="space-y-3"
      onSubmit={form.handleSubmit((v) => onSubmit(Object.fromEntries(Object.entries(v).filter(([, x]) => x !== undefined && x !== ''))))}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {props.map(([name, s]) => (
          <label key={name} className="space-y-1 text-sm">
            <span className="text-muted-foreground">
              {s.title ?? name}
              {(schema.required ?? []).includes(name) ? ' *' : ''}
              {s['x-picker'] ? <span className="ml-1 text-xs">({s['x-picker']})</span> : null}
            </span>
            {s.type === 'boolean' ? (
              <input type="checkbox" aria-label={name} {...form.register(name)} />
            ) : s.enum ? (
              <select aria-label={name} className={sel} {...form.register(name)}>
                <option value="">—</option>
                {(s.enum as string[]).map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <Input aria-label={name} type={s.format === 'date' ? 'date' : s.type === 'integer' || s.type === 'number' ? 'number' : 'text'} {...form.register(name)} />
            )}
            {errors[name]?.message && <span className="text-xs text-destructive">{String(errors[name].message)}</span>}
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {extra}
        <Button type="submit" size="sm" disabled={busy}>{submitLabel}</Button>
      </div>
    </form>
  );
}
