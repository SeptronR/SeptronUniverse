import type { HTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/utils/cn';
import { titleCase } from '@/utils/formatters';

export const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'text-foreground',
        success: 'border-transparent bg-status-approved/15 text-status-approved',
        warning: 'border-transparent bg-status-pending/15 text-status-pending',
        destructive: 'border-transparent bg-status-rejected/15 text-status-rejected',
        info: 'border-transparent bg-brand-100 text-brand-800 dark:bg-brand-900/40 dark:text-brand-200',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

/** Status strings (VARCHAR(30) + Python enums) map to a fixed, non-themed colour so "paid" never looks like "pending". */
const STATUS_VARIANT: Record<string, BadgeProps['variant']> = {
  active: 'success', approved: 'success', paid: 'success', present: 'success', succeeded: 'success', published: 'success',
  completed: 'success', verified: 'success', healthy: 'success',
  pending: 'warning', partial: 'warning', late: 'warning', running: 'warning', in_progress: 'warning', draft: 'secondary',
  queued: 'secondary', submitted: 'info', scheduled: 'info',
  rejected: 'destructive', absent: 'destructive', unpaid: 'destructive', failed: 'destructive', cancelled: 'destructive',
  suspended: 'destructive', dead: 'destructive', overdue: 'destructive',
  inactive: 'secondary', archived: 'secondary', closed: 'secondary', locked: 'secondary',
};

export function StatusBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  if (!status) return <span className="text-muted-foreground">—</span>;
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'outline'} className={className}>
      {titleCase(status)}
    </Badge>
  );
}
