import { useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Check, Palette } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import {
  applyThemePrefs,
  BRAND_RAMPS,
  loadThemePrefs,
  TABLE_STYLES,
  THEME_NAMES,
  type ThemeMode,
  type ThemePrefs,
} from '@/styles/themes';
import { cn } from '@/utils/cn';
import { titleCase } from '@/utils/formatters';

const MODES: { value: ThemeMode; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

/** Theme (5), mode and table style (6) switcher — preferences persist in localStorage via styles/themes.ts. */
export function AppearanceMenu() {
  const [prefs, setPrefs] = useState<ThemePrefs>(() => loadThemePrefs());
  const update = (patch: Partial<ThemePrefs>) => {
    const next = { ...prefs, ...patch };
    setPrefs(next);
    applyThemePrefs(next);
  };

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label="Appearance">
          <Palette className="h-5 w-5" />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 w-64 rounded-md border bg-popover p-3 text-sm shadow-md"
        >
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Theme</p>
          <div className="mb-3 flex gap-2">
            {THEME_NAMES.map((name) => (
              <button
                key={name}
                type="button"
                aria-label={BRAND_RAMPS[name].label}
                aria-pressed={prefs.theme === name}
                title={BRAND_RAMPS[name].label}
                onClick={() => update({ theme: name })}
                className={cn(
                  'flex h-7 w-7 items-center justify-center rounded-full border-2',
                  prefs.theme === name ? 'border-foreground' : 'border-transparent',
                )}
                style={{ backgroundColor: `rgb(${BRAND_RAMPS[name].ramp[600]})` }}
              >
                {prefs.theme === name && <Check className="h-4 w-4 text-white" />}
              </button>
            ))}
          </div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Mode</p>
          <div className="mb-3 inline-flex rounded-md border bg-muted p-0.5" role="radiogroup" aria-label="Colour mode">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                role="radio"
                aria-checked={prefs.mode === m.value}
                onClick={() => update({ mode: m.value })}
                className={cn(
                  'rounded-sm px-2.5 py-1 text-xs font-medium',
                  prefs.mode === m.value ? 'bg-card shadow-xs' : 'text-muted-foreground',
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Table style</p>
          <select
            aria-label="Table style"
            className="h-8 w-full rounded-md border bg-card px-2 text-sm"
            value={prefs.tableStyle}
            onChange={(e) => update({ tableStyle: e.target.value as ThemePrefs['tableStyle'] })}
          >
            {TABLE_STYLES.map((s) => (
              <option key={s} value={s}>
                {titleCase(s)}
              </option>
            ))}
          </select>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
