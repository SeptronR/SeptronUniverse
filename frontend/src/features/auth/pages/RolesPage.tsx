import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { Copy, Lock, ShieldQuestion } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable } from '@/components/shared/DataTable';
import { PermissionGuard } from '@/components/shared/Guards';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useReadOnly } from '@/features/platform/hooks';
import { DEFAULT_PAGE_SIZE } from '@/utils/constants';
import { titleCase } from '@/utils/formatters';
import { useCloneRole, useRoles } from '../hooks';
import type { Role } from '../types';
import { PermissionMatrix } from '../components/PermissionMatrix';

/** /admin/roles — the institution's roles with the permission matrix (rows = modules, columns = actions). */
export default function RolesPage() {
  const [params, setParams] = useSearchParams();
  const readOnly = useReadOnly();
  const [matrixFor, setMatrixFor] = useState<Role | null>(null);
  const [cloneFor, setCloneFor] = useState<Role | null>(null);
  const [cloneName, setCloneName] = useState('');
  const clone = useCloneRole();

  const page = Number(params.get('page') ?? 1);
  const pageSize = Number(params.get('page_size') ?? DEFAULT_PAGE_SIZE);
  const q = params.get('q') ?? '';
  const query = useRoles({ page, page_size: pageSize, q: q || undefined });

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next, { replace: true });
  };

  const columns = useMemo<ColumnDef<Role, unknown>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Role',
        cell: ({ row }) => (
          <div>
            <p className="flex items-center gap-1 font-medium">
              {row.original.name}
              {row.original.is_system && <Lock className="h-3 w-3 text-muted-foreground" aria-label="System role" />}
            </p>
            <p className="text-xs text-muted-foreground">{row.original.slug}</p>
          </div>
        ),
      },
      {
        accessorKey: 'default_scope_type',
        header: 'Default scope',
        cell: ({ row }) => <Badge variant="secondary">{titleCase(row.original.default_scope_type)}</Badge>,
      },
      { accessorKey: 'portal', header: 'Portal', cell: ({ row }) => row.original.portal ?? '—' },
      { accessorKey: 'permission_count', header: 'Permissions', cell: ({ row }) => row.original.permission_count ?? 0 },
      { accessorKey: 'assignment_count', header: 'Users', cell: ({ row }) => row.original.assignment_count ?? 0 },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button variant="ghost" size="sm" onClick={() => setMatrixFor(row.original)}>
              <ShieldQuestion className="h-4 w-4" /> Permissions
            </Button>
            <PermissionGuard module="roles" action="clone">
              <Button
                variant="ghost"
                size="sm"
                data-write
                disabled={readOnly}
                onClick={() => {
                  setCloneFor(row.original);
                  setCloneName(`${row.original.name} (copy)`);
                }}
              >
                <Copy className="h-4 w-4" />
              </Button>
            </PermissionGuard>
          </div>
        ),
      },
    ],
    [readOnly],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Roles & permissions"
        description="System roles are seeded from the platform templates: they can be re-permissioned but not renamed or deleted."
      />
      <Input
        className="w-64"
        placeholder="Search roles…"
        defaultValue={q}
        onChange={(e) => setParam('q', e.target.value || null)}
      />
      <DataTable
        columns={columns}
        data={query.data?.data ?? []}
        isLoading={query.isLoading}
        pagination={query.data?.meta.pagination}
        onPageChange={(p) => setParam('page', String(p))}
        onPageSizeChange={(s) => setParam('page_size', String(s))}
        rowKey={(r) => r.id}
        emptyTitle="No roles"
      />

      <Modal
        open={!!matrixFor}
        onOpenChange={(open) => !open && setMatrixFor(null)}
        title={`Permissions — ${matrixFor?.name ?? ''}`}
        description="Toggle cells, review the diff and save. Changes take effect at the user's next sign-in."
        size="xl"
      >
        {matrixFor && <PermissionMatrix role={matrixFor} onSaved={() => setMatrixFor(null)} />}
      </Modal>

      <Modal
        open={!!cloneFor}
        onOpenChange={(open) => !open && setCloneFor(null)}
        title={`Clone ${cloneFor?.name ?? ''}`}
        description="The copy starts with the same permissions and can be edited freely."
        footer={
          <>
            <Button variant="ghost" onClick={() => setCloneFor(null)}>
              Cancel
            </Button>
            <Button
              loading={clone.isPending}
              onClick={() =>
                cloneFor &&
                clone.mutate(
                  {
                    id: cloneFor.id,
                    name: cloneName,
                    slug: cloneName
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, '_')
                      .replace(/^_+|_+$/g, '')
                      .slice(0, 60),
                  },
                  {
                    onSuccess: () => {
                      setCloneFor(null);
                      toast.success('Role cloned');
                    },
                    onError: (e) => toast.error(getApiError(e)),
                  },
                )
              }
            >
              Clone
            </Button>
          </>
        }
      >
        <Input value={cloneName} onChange={(e) => setCloneName(e.target.value)} aria-label="New role name" />
      </Modal>
    </div>
  );
}
