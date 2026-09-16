import { ToggleLeft } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { buttonVariants } from '@/components/ui/Button';

export default function FeatureDisabledPage({ feature }: { feature?: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center p-6 text-center">
      <ToggleLeft className="mb-3 h-10 w-10 text-muted-foreground" />
      <h1 className="text-lg font-semibold">Feature not enabled</h1>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{t('errors.featureDisabled')}</p>
      {feature && <code className="mt-2 rounded bg-muted px-2 py-0.5 text-xs">{feature}</code>}
      <Link to="/dashboard" className={buttonVariants({ variant: 'outline' }) + ' mt-4'}>
        {t('common.back')}
      </Link>
    </div>
  );
}
