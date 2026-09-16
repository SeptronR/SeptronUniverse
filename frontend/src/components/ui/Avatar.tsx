import * as AvatarPrimitive from '@radix-ui/react-avatar';
import { cn } from '@/utils/cn';
import { initials } from '@/utils/formatters';

interface AvatarProps {
  name?: string | null;
  src?: string | null;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizes = { sm: 'h-7 w-7 text-xs', md: 'h-9 w-9 text-sm', lg: 'h-12 w-12 text-base' };

export function Avatar({ name, src, size = 'md', className }: AvatarProps) {
  return (
    <AvatarPrimitive.Root className={cn('relative flex shrink-0 overflow-hidden rounded-full', sizes[size], className)}>
      {src && <AvatarPrimitive.Image src={src} alt={name ?? ''} className="aspect-square h-full w-full object-cover" />}
      <AvatarPrimitive.Fallback
        delayMs={src ? 300 : 0}
        className="flex h-full w-full items-center justify-center rounded-full bg-brand-100 font-medium text-brand-800 dark:bg-brand-900/50 dark:text-brand-100"
      >
        {initials(name)}
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  );
}
