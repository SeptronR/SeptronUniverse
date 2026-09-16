import { format, formatDistanceToNow, parseISO } from 'date-fns';

/** Money is INTEGER paise end-to-end; display in the institution currency (INR default) with Indian grouping. */
export const paiseToRupees = (paise: number | null | undefined) => (paise ?? 0) / 100;
export const rupeesToPaise = (rupees: number | string) => Math.round(Number(rupees || 0) * 100);

export const formatMoney = (paise: number | null | undefined, currency = 'INR', locale = 'en-IN') =>
  new Intl.NumberFormat(locale, { style: 'currency', currency, minimumFractionDigits: 2 }).format(paiseToRupees(paise));

export const formatNumber = (n: number | null | undefined, locale = 'en-IN') =>
  n === null || n === undefined ? '—' : new Intl.NumberFormat(locale).format(n);

export const formatPercent = (n: number | null | undefined, digits = 1) =>
  n === null || n === undefined ? '—' : `${n.toFixed(digits)}%`;

const toDate = (value: string | Date | null | undefined) =>
  !value ? null : value instanceof Date ? value : parseISO(value);

/** Academic dates are institution-local (DATE columns); timestamps are UTC and rendered in the browser TZ. */
export const formatDate = (value: string | Date | null | undefined, pattern = 'dd MMM yyyy') => {
  const d = toDate(value);
  return d ? format(d, pattern) : '—';
};
export const formatDateTime = (value: string | Date | null | undefined) => formatDate(value, 'dd MMM yyyy, HH:mm');
export const formatRelative = (value: string | Date | null | undefined) => {
  const d = toDate(value);
  return d ? formatDistanceToNow(d, { addSuffix: true }) : '—';
};

export const titleCase = (s: string | null | undefined) =>
  (s ?? '').replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export const initials = (name: string | null | undefined) =>
  (name ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('') || '?';

export const truncate = (s: string | null | undefined, n = 40) =>
  !s ? '' : s.length > n ? `${s.slice(0, n - 1)}…` : s;
