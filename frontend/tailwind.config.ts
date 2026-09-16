import type { Config } from 'tailwindcss';

/**
 * `brand` and `neutral` ramps are driven by CSS custom properties (R G B channel triplets) so an institution can
 * re-theme the whole app at runtime while opacity modifiers (`bg-brand-600/30`) keep working.
 * Named themes live in src/styles/themes.ts; semantic tokens in src/index.css (Prompts/00 §4.8).
 */
const rampVar = (name: string) =>
  Object.fromEntries(
    [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((step) => [
      step,
      `rgb(var(--${name}-${step}) / <alpha-value>)`,
    ]),
  ) as Record<number, string>;

const semantic = (name: string) => ({
  DEFAULT: `rgb(var(--${name}) / <alpha-value>)`,
  foreground: `rgb(var(--${name}-foreground) / <alpha-value>)`,
});

const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'rgb(var(--border) / <alpha-value>)',
        input: 'rgb(var(--input) / <alpha-value>)',
        ring: 'rgb(var(--ring) / <alpha-value>)',
        background: 'rgb(var(--background) / <alpha-value>)',
        foreground: 'rgb(var(--foreground) / <alpha-value>)',
        primary: semantic('primary'),
        secondary: semantic('secondary'),
        destructive: semantic('destructive'),
        muted: semantic('muted'),
        accent: semantic('accent'),
        popover: semantic('popover'),
        card: semantic('card'),
        success: semantic('success'),
        warning: semantic('warning'),
        brand: rampVar('brand'),
        slate: rampVar('neutral'),
        sidebar: {
          bg: 'rgb(var(--sidebar-bg) / <alpha-value>)',
          hover: 'rgb(var(--sidebar-hover) / <alpha-value>)',
          active: 'rgb(var(--sidebar-active) / <alpha-value>)',
          text: 'rgb(var(--sidebar-text) / <alpha-value>)',
          'text-active': 'rgb(var(--sidebar-text-active) / <alpha-value>)',
        },
        // Reserved status colours — never theme-driven (a "paid" badge must not turn purple)
        status: {
          present: '#16a34a',
          absent: '#dc2626',
          late: '#d97706',
          leave: '#7c3aed',
          paid: '#16a34a',
          unpaid: '#dc2626',
          partial: '#d97706',
          pending: '#d97706',
          approved: '#16a34a',
          rejected: '#dc2626',
        },
        chart: {
          1: 'rgb(var(--chart-1) / <alpha-value>)',
          2: 'rgb(var(--chart-2) / <alpha-value>)',
          3: 'rgb(var(--chart-3) / <alpha-value>)',
          4: 'rgb(var(--chart-4) / <alpha-value>)',
          5: 'rgb(var(--chart-5) / <alpha-value>)',
          6: 'rgb(var(--chart-6) / <alpha-value>)',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      boxShadow: {
        xs: '0 1px 2px 0 rgb(var(--shadow-rgb) / 0.04)',
        sm: '0 1px 2px 0 rgb(var(--shadow-rgb) / 0.04), 0 2px 6px -1px rgb(var(--shadow-rgb) / 0.06)',
        md: '0 2px 4px -1px rgb(var(--shadow-rgb) / 0.05), 0 6px 16px -2px rgb(var(--shadow-rgb) / 0.08)',
        lg: '0 4px 8px -2px rgb(var(--shadow-rgb) / 0.06), 0 12px 28px -4px rgb(var(--shadow-rgb) / 0.10)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};

export default config;
