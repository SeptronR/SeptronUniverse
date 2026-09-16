import type { ReactNode } from 'react';
import { usePermission } from '@/hooks/usePermission';
import AccessDeniedPage from '@/pages/AccessDeniedPage';

interface Props {
  module: string;
  action?: string;
  /** Any of these `[module, action]` pairs also grants access (e.g. `students:view_all`). */
  anyOf?: [string, string][];
  children: ReactNode;
}

/** Route-level permission gate: renders AccessDeniedPage (403) instead of the page. */
export default function PermissionRoute({ module, action = 'view', anyOf, children }: Props) {
  const { can, canAny } = usePermission();
  if (!can(module, action) && !(anyOf && canAny(anyOf))) return <AccessDeniedPage />;
  return <>{children}</>;
}
