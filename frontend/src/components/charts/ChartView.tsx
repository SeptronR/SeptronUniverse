import type { ReactNode } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ChartCard, type ChartTable } from './ChartCard';
import { fmtNumber } from './format';

/** `ChartData` from `/analytics/charts/{key}` and dashboard chart widgets (Prompts/35 §35.4). */
export interface ChartData {
  key: string;
  kind: string;
  title: string;
  series: Record<string, unknown>[];
  dims: Record<string, unknown> & { series?: string[] };
  table: ChartTable;
  generated_at: string;
  stale?: boolean;
  scope?: string;
  total?: number | null;
  drilldown?: { route: string; key: string; filters?: Record<string, unknown>; id_field?: string | null; label_field?: string | null; rows?: boolean } | null;
}

/** Series colours come from the theme tokens (`--chart-1…6`); WCAG: the table twin is always one click away. */
const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6, var(--chart-1))'];
const LEVEL_COLORS: Record<string, string> = { low: 'var(--chart-2)', medium: 'var(--chart-4)', high: 'var(--chart-5)' };
const color = (name: string, i: number) => LEVEL_COLORS[name] ?? COLORS[i % COLORS.length];


interface ChartViewProps {
  data: ChartData;
  title?: string;
  height?: number;
  actions?: ReactNode;
  className?: string;
  /** clicked point → `{ filter: value }` for drill-down navigation */
  onPoint?: (point: Record<string, unknown>) => void;
}

/** Renders any registered chart kind: bar | stacked | line | area | pie | donut | funnel | gauge | heatmap | number | table | sparkline. */
export function ChartView({ data, title, height = 260, actions, className, onPoint }: ChartViewProps) {
  const keys = (data.dims?.series as string[] | undefined) ?? ['value'];
  const points = data.series ?? [];
  const click = (p: unknown) => {
    const payload = (p as { payload?: Record<string, unknown> })?.payload ?? (p as Record<string, unknown>);
    if (payload && onPoint) onPoint(payload);
  };
  let body: ReactNode;
  switch (data.kind) {
    case 'number':
      body = <div className="flex h-full items-center justify-center text-4xl font-semibold tabular-nums">{fmtNumber(points[0]?.value ?? data.total ?? 0)}</div>;
      break;
    case 'gauge':
      body = <Gauge value={Number(points[0]?.value ?? 0)} />;
      break;
    case 'funnel':
      body = <Funnel points={points} onPoint={onPoint} />;
      break;
    case 'heatmap':
      body = <Heatmap points={points} keys={keys} onPoint={onPoint} />;
      break;
    case 'table':
      body = null;
      break;
    case 'pie':
    case 'donut':
      body = (
        <ResponsiveContainer>
          <PieChart>
            <Pie data={points} dataKey={keys[0] ?? 'value'} nameKey="label" innerRadius={data.kind === 'donut' ? '55%' : 0} outerRadius="80%" onClick={click}>
              {points.map((_, i) => <Cell key={i} fill={color(String(points[i]?.label), i)} />)}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      );
      break;
    case 'line':
    case 'sparkline':
      body = (
        <ResponsiveContainer>
          <LineChart data={points}>
            {data.kind === 'line' && <CartesianGrid strokeDasharray="3 3" />}
            <XAxis dataKey="label" hide={data.kind === 'sparkline'} />
            <YAxis hide={data.kind === 'sparkline'} />
            <Tooltip />
            {keys.length > 1 && <Legend />}
            {keys.map((k, i) => <Line key={k} type="monotone" dataKey={k} stroke={color(k, i)} dot={false} />)}
          </LineChart>
        </ResponsiveContainer>
      );
      break;
    case 'area':
      body = (
        <ResponsiveContainer>
          <AreaChart data={points}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis />
            <Tooltip />
            {keys.map((k, i) => <Area key={k} type="monotone" dataKey={k} stackId="a" stroke={color(k, i)} fill={color(k, i)} />)}
          </AreaChart>
        </ResponsiveContainer>
      );
      break;
    default:
      body = (
        <ResponsiveContainer>
          <BarChart data={points}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" interval={0} angle={points.length > 8 ? -30 : 0} textAnchor={points.length > 8 ? 'end' : 'middle'} height={points.length > 8 ? 60 : 30} tick={{ fontSize: 11 }} />
            <YAxis />
            <Tooltip />
            {keys.length > 1 && <Legend />}
            {keys.map((k, i) => (
              <Bar key={k} dataKey={k} stackId={data.kind === 'stacked' ? 's' : undefined} fill={color(k, i)} onClick={click} cursor={onPoint ? 'pointer' : undefined} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      );
  }
  const desc = [data.stale ? 'stale' : null, data.scope && data.scope !== 'all' ? `scope: ${data.scope}` : null, `updated ${new Date(data.generated_at).toLocaleTimeString()}`].filter(Boolean).join(' · ');
  if (data.kind === 'table') {
    return (
      <ChartCard title={title ?? data.title} description={desc} table={data.table} actions={actions} className={className} height={height}>
        <TableOnly table={data.table} onRow={onPoint ? (i) => onPoint(points[i] ?? {}) : undefined} />
      </ChartCard>
    );
  }
  return (
    <ChartCard title={title ?? data.title} description={desc} table={data.table} actions={actions} className={className} height={height}>
      {body}
    </ChartCard>
  );
}

function TableOnly({ table, onRow }: { table: ChartTable; onRow?: (i: number) => void }) {
  return (
    <div className="h-full overflow-auto">
      <table className="data-table">
        <thead>
          <tr>{table.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((r, i) => (
            <tr key={i} onClick={onRow ? () => onRow(i) : undefined} className={onRow ? 'cursor-pointer' : undefined}>
              {r.map((c, j) => <td key={j} className={typeof c === 'number' ? 'text-right tabular-nums' : undefined}>{fmtNumber(c)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Semi-circle gauge (0–100). */
export function Gauge({ value, target }: { value: number; target?: number | null }) {
  const v = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const angle = Math.PI * (1 - v / 100);
  const x = 100 + 80 * Math.cos(angle);
  const y = 100 - 80 * Math.sin(angle);
  return (
    <svg viewBox="0 0 200 120" className="h-full w-full" role="img" aria-label={`${v}%`}>
      <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--muted)" strokeWidth="16" />
      <path d={`M20 100 A80 80 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)}`} fill="none" stroke="var(--chart-1)" strokeWidth="16" />
      {target !== undefined && target !== null && (
        <line x1={100 + 66 * Math.cos(Math.PI * (1 - target / 100))} y1={100 - 66 * Math.sin(Math.PI * (1 - target / 100))} x2={100 + 94 * Math.cos(Math.PI * (1 - target / 100))} y2={100 - 94 * Math.sin(Math.PI * (1 - target / 100))} stroke="var(--foreground)" strokeWidth="2" />
      )}
      <text x="100" y="95" textAnchor="middle" className="fill-foreground" fontSize="26" fontWeight="600">{v.toFixed(1)}%</text>
    </svg>
  );
}

/** Horizontal funnel: one bar per stage, widths relative to the first stage. */
export function Funnel({ points, onPoint }: { points: Record<string, unknown>[]; onPoint?: (p: Record<string, unknown>) => void }) {
  const max = Math.max(1, ...points.map((p) => Number(p.value ?? 0)));
  return (
    <div className="flex h-full flex-col justify-center gap-1.5">
      {points.map((p, i) => {
        const v = Number(p.value ?? 0);
        return (
          <button key={i} type="button" onClick={onPoint ? () => onPoint(p) : undefined} className="flex items-center gap-2 text-left text-xs">
            <span className="w-28 shrink-0 truncate text-muted-foreground">{String(p.label)}</span>
            <span className="h-6 rounded-sm" style={{ width: `${Math.max(4, (100 * v) / max)}%`, background: COLORS[i % COLORS.length] }} />
            <span className="tabular-nums">{fmtNumber(v)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Group × series grid; cell shade ∝ value (risk cohort: department × level). */
export function Heatmap({ points, keys, onPoint }: { points: Record<string, unknown>[]; keys: string[]; onPoint?: (p: Record<string, unknown>) => void }) {
  const max = Math.max(1, ...points.flatMap((p) => keys.map((k) => Number(p[k] ?? 0))));
  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-separate border-spacing-1 text-xs">
        <thead>
          <tr>
            <th />
            {keys.map((k) => <th key={k} className="font-medium text-muted-foreground">{k}</th>)}
          </tr>
        </thead>
        <tbody>
          {points.map((p, i) => (
            <tr key={i}>
              <th className="pr-2 text-left font-medium">{String(p.label)}</th>
              {keys.map((k, j) => {
                const v = Number(p[k] ?? 0);
                return (
                  <td key={k} onClick={onPoint ? () => onPoint({ ...p, series: k }) : undefined} className="cursor-pointer rounded px-2 py-1 text-center tabular-nums" style={{ background: `color-mix(in srgb, ${color(k, j)} ${Math.round(15 + (85 * v) / max)}%, transparent)` }}>
                    {v}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Tiny inline trend for stat cards (`[[day, value], …]`). */
export function Sparkline({ points }: { points: [string, number | null][] }) {
  if (!points || points.length < 2) return null;
  const data = points.map(([label, value]) => ({ label, value: value ?? 0 }));
  return (
    <div className="h-8 w-24" aria-hidden>
      <ResponsiveContainer>
        <LineChart data={data}>
          <Line type="monotone" dataKey="value" stroke="var(--chart-1)" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
