import { useMemo, useState } from 'react';
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type VisibilityState,
} from '@tanstack/react-table';
import { ArrowDown, ArrowUp, ArrowUpDown, Columns3, Download } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Dropdown } from '@/components/ui/Dropdown';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { EmptyState } from '@/components/shared/EmptyState';
import { cn } from '@/utils/cn';
import { PAGE_SIZES } from '@/utils/constants';
import type { PaginationMeta } from '@/utils/types';

export interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  isLoading?: boolean;
  /** Server-side pagination meta from the envelope. */
  pagination?: PaginationMeta;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  /** Server-side sort: `-field` for descending (API convention). */
  sort?: string | null;
  onSortChange?: (sort: string | null) => void;
  /** Export hook: enqueues a report job (downloads always go job → signed URL). */
  onExport?: () => void;
  emptyTitle?: string;
  emptyDescription?: string;
  rowKey?: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  className?: string;
}

/**
 * Server-side DataTable on TanStack Table v8 — pagination, sort, column chooser and export hook.
 * Table visual style follows <html data-table-style> (6 styles, Prompts/00 §4.8).
 */
export function DataTable<T>({
  columns,
  data,
  isLoading,
  pagination,
  onPageChange,
  onPageSizeChange,
  sort,
  onSortChange,
  onExport,
  emptyTitle = 'No records',
  emptyDescription = 'Nothing matches the current filters.',
  rowKey,
  onRowClick,
  className,
}: DataTableProps<T>) {
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const sorting = useMemo<SortingState>(
    () => (sort ? [{ id: sort.replace(/^-/, ''), desc: sort.startsWith('-') }] : []),
    [sort],
  );

  const table = useReactTable({
    data,
    columns,
    state: { columnVisibility, sorting },
    onColumnVisibilityChange: setColumnVisibility,
    manualPagination: true,
    manualSorting: true,
    onSortingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater;
      const s = next[0];
      onSortChange?.(s ? `${s.desc ? '-' : ''}${s.id}` : null);
    },
    getCoreRowModel: getCoreRowModel(),
    pageCount: pagination?.total_pages ?? -1,
  });

  const page = pagination?.page ?? 1;
  const totalPages = pagination?.total_pages ?? 1;

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {onExport && (
          <Button variant="outline" size="sm" onClick={onExport}>
            <Download className="h-4 w-4" /> Export
          </Button>
        )}
        <Dropdown
          trigger={
            <Button variant="outline" size="sm" aria-label="Choose columns">
              <Columns3 className="h-4 w-4" /> Columns
            </Button>
          }
          items={table.getAllLeafColumns().map((col) => ({
            label: (
              <span className="flex items-center gap-2">
                <input type="checkbox" readOnly checked={col.getIsVisible()} className="h-3.5 w-3.5" />
                {typeof col.columnDef.header === 'string' ? col.columnDef.header : col.id}
              </span>
            ),
            onSelect: () => col.toggleVisibility(),
          }))}
        />
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card">
        {isLoading ? (
          <div className="p-4">
            <TableSkeleton cols={Math.min(columns.length, 6)} />
          </div>
        ) : data.length === 0 ? (
          <EmptyState title={emptyTitle} description={emptyDescription} />
        ) : (
          <table className="data-table">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((header) => {
                    const canSort = !!onSortChange && header.column.columnDef.enableSorting !== false;
                    const sorted = header.column.getIsSorted();
                    return (
                      <th key={header.id} scope="col">
                        {header.isPlaceholder ? null : canSort ? (
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 hover:text-foreground"
                            onClick={header.column.getToggleSortingHandler()}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === 'asc' ? (
                              <ArrowUp className="h-3 w-3" />
                            ) : sorted === 'desc' ? (
                              <ArrowDown className="h-3 w-3" />
                            ) : (
                              <ArrowUpDown className="h-3 w-3 opacity-40" />
                            )}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row, i) => (
                <tr
                  key={rowKey ? rowKey(row.original, i) : row.id}
                  className={cn(onRowClick && 'cursor-pointer hover:bg-accent/50')}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {pagination && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
          <span>
            {pagination.total === 0
              ? '0 records'
              : `${(page - 1) * pagination.page_size + 1}–${Math.min(page * pagination.page_size, pagination.total)} of ${pagination.total}`}
          </span>
          <div className="flex items-center gap-2">
            {onPageSizeChange && (
              <select
                className="h-8 rounded-md border bg-card px-2 text-sm"
                value={pagination.page_size}
                onChange={(e) => onPageSizeChange(Number(e.target.value))}
                aria-label="Rows per page"
              >
                {PAGE_SIZES.map((s) => (
                  <option key={s} value={s}>
                    {s} / page
                  </option>
                ))}
              </select>
            )}
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPageChange?.(page - 1)}>
              Previous
            </Button>
            <span className="tabular-nums">
              {page} / {totalPages}
            </span>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => onPageChange?.(page + 1)}>
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
