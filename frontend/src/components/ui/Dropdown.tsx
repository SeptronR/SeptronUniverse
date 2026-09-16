import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import type { ReactNode } from 'react';
import { cn } from '@/utils/cn';

export interface DropdownItem {
  label: ReactNode;
  onSelect?: () => void;
  icon?: ReactNode;
  destructive?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean;
}

interface DropdownProps {
  trigger: ReactNode;
  items: DropdownItem[];
  align?: 'start' | 'end';
  className?: string;
}

/** Radix dropdown menu with keyboard navigation; used for row actions, user menus and switchers. */
export function Dropdown({ trigger, items, align = 'end', className }: DropdownProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align={align}
          sideOffset={6}
          className={cn('z-50 min-w-[10rem] rounded-md border bg-popover p-1 text-popover-foreground shadow-md', className)}
        >
          {items.map((item, i) => (
            <div key={i}>
              {item.separatorBefore && <DropdownMenu.Separator className="my-1 h-px bg-border" />}
              <DropdownMenu.Item
                disabled={item.disabled}
                onSelect={item.onSelect}
                className={cn(
                  'flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
                  item.destructive && 'text-destructive',
                )}
              >
                {item.icon}
                {item.label}
              </DropdownMenu.Item>
            </div>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
