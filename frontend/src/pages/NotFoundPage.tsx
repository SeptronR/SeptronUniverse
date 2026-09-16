import { FileQuestion } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { buttonVariants } from '@/components/ui/Button';

export default function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-6 text-center">
      <FileQuestion className="mb-3 h-10 w-10 text-muted-foreground" />
      <h1 className="text-lg font-semibold">404</h1>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{t('errors.notFound')}</p>
      <Link to="/" className={buttonVariants({ variant: 'outline' }) + ' mt-4'}>
        {t('common.back')}
      </Link>
    </div>
  );
}
