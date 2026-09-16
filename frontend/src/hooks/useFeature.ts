import { useAuthStore } from '@/store/authStore';

/** Effective feature keys come from /auth/me; `core.*` keys are never gated. */
export const useFeature = (key: string | undefined) =>
  useAuthStore((s) => !key || s.features.includes(key) || key.startsWith('core.'));

export const useFeatures = () => useAuthStore((s) => s.features);
