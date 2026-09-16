import type { ReactNode } from 'react';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';

interface PermissionGuardProps {
  module: string;
  action?: string;
  anyOf?: [string, string][];
  fallback?: ReactNode;
  children: ReactNode;
}

/** Inline permission gate for buttons/sections (route-level gating is PermissionRoute). */
export function PermissionGuard({ module, action = 'view', anyOf, fallback = null, children }: PermissionGuardProps) {
  const { can, canAny } = usePermission();
  if (!can(module, action) && !(anyOf && canAny(anyOf))) return <>{fallback}</>;
  return <>{children}</>;
}

interface FeatureGuardProps {
  feature?: string;
  fallback?: ReactNode;
  children: ReactNode;
}

/** Inline feature gate; disabled features are hidden (docs/Feature_Flags.md 1.4). */
export function FeatureGuard({ feature, fallback = null, children }: FeatureGuardProps) {
  const enabled = useFeature(feature);
  if (!enabled) return <>{fallback}</>;
  return <>{children}</>;
}
