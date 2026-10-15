import { useSearchParams } from 'react-router-dom';

/** Tenant slug of the public admissions pages: ?institution=<slug>, else the deployment default. */
export const useInstitutionSlug = () => {
  const [params] = useSearchParams();
  return params.get('institution') ?? import.meta.env.VITE_DEFAULT_INSTITUTION ?? 'demo-uni';
};
