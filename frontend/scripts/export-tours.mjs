// `npm run tours:export` — transpiles src/tours/*.ts with the TypeScript compiler and writes the registry snapshot the
// API serves (backend/app/core/tours_snapshot.json; revision 0039 stores it in platform_settings['tours']).
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, '..', 'src', 'tours');
const out = [];
for (const f of readdirSync(dir).filter((n) => n.endsWith('.ts') && !['index.ts', 'types.ts'].includes(n)).sort()) {
  const js = ts.transpileModule(readFileSync(join(dir, f), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const mod = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
  for (const v of Object.values(mod)) if (Array.isArray(v)) out.push(...v);
}
const target = join(here, '..', '..', 'backend', 'app', 'core', 'tours_snapshot.json');
writeFileSync(target, `${JSON.stringify(out, null, 2)}\n`);
console.log(`tours: ${out.length} → ${target}`);
