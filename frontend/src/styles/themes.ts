/**
 * Named themes + table styles (Prompts/00 §4.8). Each theme is a brand ramp (R G B channel triplets) applied as
 * CSS variables on <html data-theme>; semantic tokens in index.css derive from `--brand-*`.
 * Invariant: step 600 is the AA-safe primary action colour on white; 700 on dark surfaces.
 * Tokens are exported to styles/tokens.json for Flutter (shared design tokens).
 */
export type ThemeName = 'indigo' | 'ocean' | 'grove' | 'sunset' | 'plum';
export type ThemeMode = 'light' | 'dark' | 'system';
export type TableStyle = 'default' | 'striped' | 'bordered' | 'compact' | 'card' | 'minimal';

export const THEME_NAMES: ThemeName[] = ['indigo', 'ocean', 'grove', 'sunset', 'plum'];
export const TABLE_STYLES: TableStyle[] = ['default', 'striped', 'bordered', 'compact', 'card', 'minimal'];

type Ramp = Record<50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 950, string>;

export const BRAND_RAMPS: Record<ThemeName, { label: string; ramp: Ramp }> = {
  indigo: {
    label: 'Indigo',
    ramp: {
      50: '238 242 255', 100: '224 231 255', 200: '199 210 254', 300: '165 180 252', 400: '129 140 248',
      500: '99 102 241', 600: '79 70 229', 700: '67 56 202', 800: '55 48 163', 900: '49 46 129', 950: '30 27 75',
    },
  },
  ocean: {
    label: 'Ocean',
    ramp: {
      50: '236 254 255', 100: '207 250 254', 200: '165 243 252', 300: '103 232 249', 400: '34 211 238',
      500: '6 182 212', 600: '8 145 178', 700: '14 116 144', 800: '21 94 117', 900: '22 78 99', 950: '8 51 68',
    },
  },
  grove: {
    label: 'Grove',
    ramp: {
      50: '240 253 244', 100: '220 252 231', 200: '187 247 208', 300: '134 239 172', 400: '74 222 128',
      500: '34 197 94', 600: '22 163 74', 700: '21 128 61', 800: '22 101 52', 900: '20 83 45', 950: '5 46 22',
    },
  },
  sunset: {
    label: 'Sunset',
    ramp: {
      50: '255 247 237', 100: '255 237 213', 200: '254 215 170', 300: '253 186 116', 400: '251 146 60',
      500: '249 115 22', 600: '234 88 12', 700: '194 65 12', 800: '154 52 18', 900: '124 45 18', 950: '67 20 7',
    },
  },
  plum: {
    label: 'Plum',
    ramp: {
      50: '253 244 255', 100: '250 232 255', 200: '245 208 254', 300: '240 171 252', 400: '232 121 249',
      500: '217 70 239', 600: '192 38 211', 700: '162 28 175', 800: '134 25 143', 900: '112 26 117', 950: '74 4 78',
    },
  },
};

export const CHART_CATEGORICAL_LIGHT = ['79 70 229', '8 145 178', '22 163 74', '234 88 12', '192 38 211', '100 116 139'];
export const CHART_CATEGORICAL_DARK = ['129 140 248', '34 211 238', '74 222 128', '251 146 60', '232 121 249', '148 163 184'];

export interface ThemePrefs {
  theme: ThemeName;
  mode: ThemeMode;
  tableStyle: TableStyle;
}

export const DEFAULT_THEME_PREFS: ThemePrefs = { theme: 'indigo', mode: 'system', tableStyle: 'default' };
const STORAGE_KEY = 'universe-theme';

export function loadThemePrefs(): ThemePrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...DEFAULT_THEME_PREFS, ...(JSON.parse(raw) as Partial<ThemePrefs>) } : DEFAULT_THEME_PREFS;
  } catch {
    return DEFAULT_THEME_PREFS;
  }
}

export function applyThemePrefs(prefs: ThemePrefs, brandOverride?: Partial<Ramp>) {
  const root = document.documentElement;
  root.setAttribute('data-theme', prefs.theme);
  root.setAttribute('data-table-style', prefs.tableStyle);
  const dark = prefs.mode === 'dark' || (prefs.mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  root.classList.toggle('dark', dark);
  const ramp = { ...BRAND_RAMPS[prefs.theme].ramp, ...(brandOverride ?? {}) };
  (Object.keys(ramp) as unknown as (keyof Ramp)[]).forEach((step) => root.style.setProperty(`--brand-${step}`, ramp[step]));
  const chart = dark ? CHART_CATEGORICAL_DARK : CHART_CATEGORICAL_LIGHT;
  chart.forEach((c, i) => root.style.setProperty(`--chart-${i + 1}`, c));
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* storage may be unavailable */
  }
}
