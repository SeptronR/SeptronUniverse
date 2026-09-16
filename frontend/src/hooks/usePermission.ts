import { useAuthStore } from '@/store/authStore';

/** `can(module, action)` mirrors Principal.has(): super admin, exact `module:action`, or `module:manage`. */
export const usePermission = () => {
  const permissions = useAuthStore((s) => s.permissions);
  const currentUser = useAuthStore((s) => s.currentUser);
  const can = (m: string, a = 'view') =>
    !!currentUser?.is_super_admin || permissions.includes(`${m}:${a}`) || permissions.includes(`${m}:manage`);
  return { can, canAny: (pairs: [string, string][]) => pairs.some(([m, a]) => can(m, a)) };
};
