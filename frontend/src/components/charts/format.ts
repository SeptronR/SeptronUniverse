/** Number display for chart / stat widgets (en-IN grouping, 2 decimals; '—' for empty). */
export const fmtNumber = (v: unknown) => (typeof v === 'number' ? v.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : v === null || v === undefined ? '—' : String(v));
