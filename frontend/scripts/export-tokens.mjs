// Copies the shared design tokens into the Flutter bundle so web and app themes stay identical (Prompts/42 §42.9).
// `npm run tokens:export`; CI checks the hash with backend/scripts/check_tokens_sync.py.
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, '../src/styles/tokens.json');
const dst = resolve(here, '../../flutter/assets/theme/tokens.json');
mkdirSync(dirname(dst), { recursive: true });
copyFileSync(src, dst);
console.log(`tokens: ${src} → ${dst}`);
