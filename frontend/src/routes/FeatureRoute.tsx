import type { ReactNode } from 'react';
import { useFeature } from '@/hooks/useFeature';
import FeatureDisabledPage from '@/pages/FeatureDisabledPage';

interface Props {
  feature?: string;
  children: ReactNode;
}

/** Route-level feature gate: a deep link to a disabled feature shows "feature not enabled" (docs/Feature_Flags.md 1.6). */
export default function FeatureRoute({ feature, children }: Props) {
  const enabled = useFeature(feature);
  if (!enabled) return <FeatureDisabledPage feature={feature} />;
  return <>{children}</>;
}
