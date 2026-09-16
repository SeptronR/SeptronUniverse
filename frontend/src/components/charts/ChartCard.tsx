import { useState, type ReactNode } from 'react';
import { BarChart3, Table2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/utils/cn';

export interface ChartTable {
  columns: string[];
  rows: (string | number | null)[][];
}

interface ChartCardProps {
  title: string;
  description?: string;
  /** Tabular twin of the chart — mandatory so every chart has an accessible table view (Orbit convention). */
  table: ChartTable;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
  height?: number;
}

/** Recharts wrapper with the mandatory chart/table toggle; series colours use the `--chart-N` tokens. */
export function ChartCard({ title, description, table, children, actions, className, height = 280 }: ChartCardProps) {
  const [view, setView] = useState<'chart' | 'table'>('chart');
  return (
    <Card className={className}>
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div>
          <CardTitle>{title}</CardTitle>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
        <div className="flex items-center gap-1">
          {actions}
          <Button
            variant="ghost"
            size="icon"
            aria-label={view === 'chart' ? 'Show as table' : 'Show as chart'}
            aria-pressed={view === 'table'}
            onClick={() => setView((v) => (v === 'chart' ? 'table' : 'chart'))}
          >
            {view === 'chart' ? <Table2 className="h-4 w-4" /> : <BarChart3 className="h-4 w-4" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {view === 'chart' ? (
          <div style={{ height }} role="img" aria-label={`${title} chart`}>
            {children}
          </div>
        ) : (
          <div className="overflow-x-auto" style={{ maxHeight: height }}>
            <table className="data-table">
              <thead>
                <tr>
                  {table.columns.map((c) => (
                    <th key={c} scope="col">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((r, i) => (
                  <tr key={i}>
                    {r.map((cell, j) => (
                      <td key={j} className={cn(typeof cell === 'number' && 'text-right tabular-nums')}>
                        {cell ?? '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export const CHART_COLORS = [1, 2, 3, 4, 5, 6].map((i) => `rgb(var(--chart-${i}))`);
