import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { cn } from '@/utils/cn';

const base =
  'flex w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = 'text', ...props }, ref) => (
    <input ref={ref} type={type} className={cn(base, 'h-9', className)} {...props} />
  ),
);
Input.displayName = 'Input';

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn(base, 'min-h-[80px]', className)} {...props} />,
);
Textarea.displayName = 'Textarea';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface NativeSelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  options: SelectOption[];
  placeholder?: string;
}

/** Native select for forms and filters; use Radix Select (Dropdown) for rich menus. */
export const Select = forwardRef<HTMLSelectElement, NativeSelectProps>(
  ({ className, options, placeholder, ...props }, ref) => (
    <select ref={ref} className={cn(base, 'h-9', className)} {...props}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  ),
);
Select.displayName = 'Select';
