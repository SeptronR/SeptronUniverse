import { z } from 'zod';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
export type JsonSchema = { type?: string; properties?: Record<string, Any>; required?: string[] };

const UUID = /^[0-9a-fA-F-]{36}$/;

/** JSON Schema (`params_schema` of a report) → Zod (Prompts/36 §36.9 `ReportParamsForm`). Empty strings are dropped. */
export function schemaToZod(schema: JsonSchema) {
  const shape: Record<string, z.ZodTypeAny> = {};
  const required = new Set(schema.required ?? []);
  for (const [name, spec] of Object.entries(schema.properties ?? {})) {
    if (spec['x-dev']) continue;
    let f: z.ZodTypeAny;
    if (spec.type === 'boolean') f = z.boolean();
    else if (spec.type === 'integer' || spec.type === 'number') f = z.coerce.number();
    else if (spec.enum) f = z.enum(spec.enum as [string, ...string[]]);
    else if (spec.format === 'uuid') f = z.string().regex(UUID, `${name} must be an id`);
    else if (spec.format === 'date') f = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'yyyy-mm-dd');
    else if (spec.pattern) f = z.string().regex(new RegExp(spec.pattern), `must match ${spec.pattern}`);
    else f = z.string();
    shape[name] = required.has(name) ? f : z.preprocess((v) => (v === '' ? undefined : v), f.optional());
  }
  return z
    .object(shape)
    .refine((v: Any) => !(v.from && v.to && v.from > v.to), { message: 'from must not be after to', path: ['to'] });
}
