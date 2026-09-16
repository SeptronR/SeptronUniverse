import { ShieldOff } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { buttonVariants } from '@/components/ui/Button';

export default function AccessDeniedPage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center p-6 text-center">
      <ShieldOff className="mb-3 h-10 w-10 text-muted-foreground" />
      <h1 className="text-lg font-semibold">403</h1>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{t('errors.accessDenied')}</p>
      <Link to="/dashboard" className={buttonVariants({ variant: 'outline' }) + ' mt-4'}>
        {t('common.back')}
      </Link>
    </div>
  );
}
