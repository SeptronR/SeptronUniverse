import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { FileSpreadsheet, KeyRound, Plus, ShieldCheck, UserCog, VenetianMask } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable } from '@/components/shared/DataTable';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { FormField } from '@/components/shared/FormField';
import { PermissionGuard } from '@/components/shared/Guards';
import { Button } from '@/components/ui/Button';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useReadOnly } from '@/features/platform/hooks';
import { DEFAULT_PAGE_SIZE } from '@/utils/constants';
import { formatDateTime, titleCase } from '@/utils/formatters';
import type { ScopeName } from '@/utils/types';
import {
  useAssignRole,
  useCreateUser,
  useCredentialSheets,
  useImpersonate,
  useResetUserPassword,
  useRevokeRole,
  useRoles,
  useToggleUserActive,
  useUserRoles,
  useUsers,
} from '../hooks';
import type { UserRow } from '../types';

const USER_TYPES = ['staff', 'student', 'guardian', 'alumni', 'applicant', 'recruiter', 'external'];

const createSchema = z.object({
  username: z.string().min(3, 'At least 3 characters'),
  display_name: z.string().min(2, 'Required'),
  email: z.string().email('Enter a valid email').optional().or(z.literal('')),
  phone: z.string().optional(),
  user_type: z.string(),
  role_id: z.string().optional(),
  scope_type: z.string().optional(),
  scope_id: z.string().optional(),
});
type CreateForm = z.infer<typeof createSchema>;

/**
 * /admin/users — DataTable with Mine|All scope tabs, create (with role + scope), roles drawer, deactivate,
 * admin password reset and credential sheets (Prompts/02 §02.9).
 */
export default function UsersPage() {
  const [params, setParams] = useSearchParams();
  const readOnly = useReadOnly();
  const [createOpen, setCreateOpen] = useState(false);
  const [rolesFor, setRolesFor] = useState<UserRow | null>(null);
  const [created, setCreated] = useState<{ username: string; password: string } | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  const page = Number(params.get('page') ?? 1);
  const pageSize = Number(params.get('page_size') ?? DEFAULT_PAGE_SIZE);
  const sort = params.get('sort');
  const scope = params.get('scope') ?? undefined;
  const q = params.get('q') ?? '';
  const userType = params.get('user_type') ?? undefined;

  const query = useUsers({ page, page_size: pageSize, sort: sort ?? undefined, scope, q: q || undefined, user_type: userType });
  const roles = useRoles({ page_size: 200 });
  const createUser = useCreateUser();
  const toggleActive = useToggleUserActive();
  const resetPassword = useResetUserPassword();
  const sheets = useCredentialSheets();
  const impersonate = useImpersonate();

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next, { replace: true });
  };

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { username: '', display_name: '', email: '', phone: '', user_type: 'staff' },
  });

  const onCreate = async (values: CreateForm) => {
    try {
      const res = await createUser.mutateAsync({
        username: values.username,
        display_name: values.display_name,
        email: values.email || undefined,
        phone: values.phone || undefined,
        user_type: values.user_type,
        roles: values.role_id
          ? [{ role_id: values.role_id, scope_type: values.scope_type || undefined, scope_id: values.scope_id || undefined }]
          : [],
      });
      setCreateOpen(false);
      form.reset();
      if (res.data.temporary_password) setCreated({ username: res.data.username, password: res.data.temporary_password });
      toast.success('User created');
    } catch (e) {
      toast.error(getApiError(e, 'Could not create the user'));
    }
  };

  const columns = useMemo<ColumnDef<UserRow, unknown>[]>(
    () => [
      {
        id: 'select',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <input
            type="checkbox"
            aria-label={`Select ${row.original.username}`}
            checked={selected.includes(row.original.id)}
            onChange={(e) =>
              setSelected((prev) => (e.target.checked ? [...prev, row.original.id] : prev.filter((id) => id !== row.original.id)))
            }
          />
        ),
      },
      {
        accessorKey: 'display_name',
        header: 'Name',
        cell: ({ row }) => (
          <div>
            <p className="font-medium">{row.original.display_name ?? row.original.username}</p>
            <p className="text-xs text-muted-foreground">{row.original.username}</p>
          </div>
        ),
      },
      { accessorKey: 'email', header: 'Email', cell: ({ row }) => row.original.email ?? '—' },
      { accessorKey: 'phone', header: 'Phone', cell: ({ row }) => row.original.phone ?? '—' },
      {
        id: 'roles',
        header: 'Roles',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.role_slugs.slice(0, 3).map((r) => (
              <Badge key={r} variant="secondary">
                {titleCase(r)}
              </Badge>
            ))}
            {row.original.role_slugs.length > 3 && <Badge variant="outline">+{row.original.role_slugs.length - 3}</Badge>}
          </div>
        ),
      },
      {
        accessorKey: 'is_active',
        header: 'Status',
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
            <StatusBadge status={row.original.is_active ? 'active' : 'inactive'} />
            {row.original.mfa_enabled && <ShieldCheck className="h-3.5 w-3.5 text-status-approved" aria-label="MFA enabled" />}
          </div>
        ),
      },
      {
        accessorKey: 'last_login_at',
        header: 'Last sign-in',
        cell: ({ row }) => (row.original.last_login_at ? formatDateTime(row.original.last_login_at) : '—'),
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <PermissionGuard module="roles" action="assign">
              <Button variant="ghost" size="sm" onClick={() => setRolesFor(row.original)}>
                <UserCog className="h-4 w-4" /> Roles
              </Button>
            </PermissionGuard>
            <PermissionGuard module="users" action="impersonate">
              <Button
                variant="ghost"
                size="sm"
                title="Impersonate (audited)"
                loading={impersonate.isPending && impersonate.variables?.id === row.original.id}
                onClick={() =>
                  impersonate.mutate(
                    { id: row.original.id, reason: `Support session for ${row.original.username}` },
                    {
                      onSuccess: () => toast.success(`Impersonating ${row.original.username}`),
                      onError: (e) => toast.error(getApiError(e)),
                    },
                  )
                }
              >
                <VenetianMask className="h-4 w-4" />
              </Button>
            </PermissionGuard>
            <PermissionGuard module="users" action="reset_password">
              <Button
                variant="ghost"
                size="sm"
                data-write
                disabled={readOnly}
                onClick={() =>
                  resetPassword.mutate(row.original.id, {
                    onSuccess: (res) => setCreated({ username: row.original.username, password: res.data.temporary_password }),
                    onError: (e) => toast.error(getApiError(e)),
                  })
                }
              >
                <KeyRound className="h-4 w-4" />
              </Button>
            </PermissionGuard>
            <PermissionGuard module="users" action="update">
              <Button
                variant="ghost"
                size="sm"
                data-write
                disabled={readOnly}
                onClick={() =>
                  toggleActive.mutate(
                    { id: row.original.id, active: !row.original.is_active },
                    {
                      onSuccess: () => toast.success(row.original.is_active ? 'User deactivated' : 'User reactivated'),
                      onError: (e) => toast.error(getApiError(e)),
                    },
                  )
                }
              >
                {row.original.is_active ? 'Deactivate' : 'Reactivate'}
              </Button>
            </PermissionGuard>
          </div>
        ),
      },
    ],
    [impersonate, readOnly, resetPassword, selected, toggleActive],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Users"
        description="Accounts, roles and scopes of this institution."
        actions={
          <div className="flex gap-2">
            <PermissionGuard module="users" action="create">
              <Button
                variant="outline"
                data-write
                disabled={readOnly || selected.length === 0}
                loading={sheets.isPending}
                onClick={() =>
                  sheets.mutate(
                    { audience: 'staff', ids: selected },
                    {
                      onSuccess: () => {
                        setSelected([]);
                        toast.success('Credential sheet queued — watch the jobs tray');
                      },
                      onError: (e) => toast.error(getApiError(e)),
                    },
                  )
                }
              >
                <FileSpreadsheet className="h-4 w-4" /> Credential sheets{selected.length ? ` (${selected.length})` : ''}
              </Button>
              <Button data-write disabled={readOnly} onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" /> New user
              </Button>
            </PermissionGuard>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <ScopeTabs visibility={query.data?.meta.visibility} value={scope} onChange={(s: ScopeName) => setParam('scope', s)} />
        <Input
          className="w-56"
          placeholder="Search name, username, email…"
          defaultValue={q}
          onChange={(e) => setParam('q', e.target.value || null)}
        />
        <Select
          className="w-40"
          aria-label="User type"
          placeholder="All types"
          value={userType ?? ''}
          onChange={(e) => setParam('user_type', e.target.value || null)}
          options={USER_TYPES.map((v) => ({ value: v, label: titleCase(v) }))}
        />
      </div>

      <DataTable
        columns={columns}
        data={query.data?.data ?? []}
        isLoading={query.isLoading}
        pagination={query.data?.meta.pagination}
        onPageChange={(p) => setParam('page', String(p))}
        onPageSizeChange={(s) => setParam('page_size', String(s))}
        sort={sort}
        onSortChange={(s) => setParam('sort', s)}
        rowKey={(r) => r.id}
        emptyTitle="No users"
        emptyDescription="Create the first account or adjust the filters."
      />

      <Modal
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New user"
        description="A temporary password is generated; the user must change it at first sign-in."
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={form.handleSubmit(onCreate)} loading={createUser.isPending}>
              Create
            </Button>
          </>
        }
      >
        <form className="space-y-3" onSubmit={form.handleSubmit(onCreate)} noValidate>
          <FormField label="Username" error={form.formState.errors.username} {...form.register('username')} />
          <FormField label="Display name" error={form.formState.errors.display_name} {...form.register('display_name')} />
          <FormField label="Email" type="email" error={form.formState.errors.email} {...form.register('email')} />
          <FormField label="Phone" error={form.formState.errors.phone} {...form.register('phone')} />
          <label className="block text-sm font-medium">
            User type
            <Select className="mt-1" options={USER_TYPES.map((v) => ({ value: v, label: titleCase(v) }))} {...form.register('user_type')} />
          </label>
          <label className="block text-sm font-medium">
            Role
            <Select
              className="mt-1"
              placeholder="No role yet"
              options={(roles.data?.data ?? []).map((r) => ({ value: r.id, label: `${r.name} (${r.default_scope_type})` }))}
              {...form.register('role_id')}
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Unit-scoped roles (dean, HOD, class advisor, college admin) need their scope — assign them from the roles
            drawer where the scope picker lists the institution's units.
          </p>
        </form>
      </Modal>

      <RolesDrawer user={rolesFor} onClose={() => setRolesFor(null)} />

      <Modal
        open={!!created}
        onOpenChange={() => setCreated(null)}
        title="Temporary password"
        description="Hand this over securely — it is shown once and must be changed at first sign-in."
        footer={<Button onClick={() => setCreated(null)}>Done</Button>}
      >
        <p className="font-mono text-sm">
          {created?.username}: <span className="rounded bg-muted px-2 py-1">{created?.password}</span>
        </p>
      </Modal>
    </div>
  );
}

/** Role assignments of one user with the scope picker (scopes are validated against the institution by the API). */
function RolesDrawer({ user, onClose }: { user: UserRow | null; onClose: () => void }) {
  const assignments = useUserRoles(user?.id);
  const roles = useRoles({ page_size: 200 });
  const assign = useAssignRole();
  const revoke = useRevokeRole();
  const [roleId, setRoleId] = useState('');
  const [scopeId, setScopeId] = useState('');

  const role = (roles.data?.data ?? []).find((r) => r.id === roleId);
  const needsScope = !!role && !['institution', 'self'].includes(role.default_scope_type);

  return (
    <Modal
      open={!!user}
      onOpenChange={(open) => !open && onClose()}
      title={`Roles — ${user?.display_name ?? user?.username ?? ''}`}
      description="A user holds the union of its role scopes; time-boxed roles carry a validity window."
      size="lg"
      footer={<Button onClick={onClose}>Close</Button>}
    >
      <div className="space-y-4">
        <ul className="space-y-2">
          {(assignments.data?.data ?? []).map((a) => (
            <li key={a.id} className="flex items-center justify-between rounded-md border p-2 text-sm">
              <div>
                <p className="font-medium">{a.role_name}</p>
                <p className="text-xs text-muted-foreground">
                  {a.scope_type}
                  {a.scope_label ? ` · ${a.scope_label}` : ''}
                  {a.valid_to ? ` · until ${formatDateTime(a.valid_to)}` : ''}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive"
                loading={revoke.isPending}
                onClick={() =>
                  user &&
                  revoke.mutate(
                    { id: user.id, assignmentId: a.id },
                    { onSuccess: () => toast.success('Role revoked'), onError: (e) => toast.error(getApiError(e)) },
                  )
                }
              >
                Revoke
              </Button>
            </li>
          ))}
          {assignments.data?.data.length === 0 && <li className="text-sm text-muted-foreground">No roles yet.</li>}
        </ul>

        <div className="space-y-2 border-t pt-3">
          <Select
            aria-label="Role"
            placeholder="Choose a role"
            value={roleId}
            onChange={(e) => setRoleId(e.target.value)}
            options={(roles.data?.data ?? []).map((r) => ({ value: r.id, label: `${r.name} (${r.default_scope_type})` }))}
          />
          {needsScope && (
            <Input
              placeholder={`${role?.default_scope_type} id`}
              value={scopeId}
              onChange={(e) => setScopeId(e.target.value)}
              aria-label="Scope id"
            />
          )}
          <Button
            disabled={!roleId || (needsScope && !scopeId)}
            loading={assign.isPending}
            onClick={() =>
              user &&
              assign.mutate(
                { id: user.id, role_id: roleId, scope_id: needsScope ? scopeId : undefined },
                {
                  onSuccess: () => {
                    setRoleId('');
                    setScopeId('');
                    toast.success('Role assigned');
                  },
                  onError: (e) => toast.error(getApiError(e)),
                },
              )
            }
          >
            Assign role
          </Button>
        </div>
      </div>
    </Modal>
  );
}
