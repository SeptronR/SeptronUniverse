import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react';
import { type FieldError } from 'react-hook-form';
import { Input } from '@/components/ui/Input';
import { cn } from '@/utils/cn';
import { paiseToRupees, rupeesToPaise } from '@/utils/formatters';

interface FieldWrapperProps {
  label?: string;
  hint?: string;
  error?: FieldError | string;
  required?: boolean;
  className?: string;
  children: (id: string, describedBy: string | undefined, invalid: boolean) => ReactNode;
}

/** RHF + Zod field wrapper: label, hint, error message and aria wiring (frontend coding standard 2). */
export function FieldWrapper({ label, hint, error, required, className, children }: FieldWrapperProps) {
  const id = useId();
  const message = typeof error === 'string' ? error : error?.message;
  const describedBy = message ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn('space-y-1.5', className)}>
      {label && (
        <label htmlFor={id} className="text-sm font-medium">
          {label}
          {required && <span className="ml-0.5 text-destructive">*</span>}
        </label>
      )}
      {children(id, describedBy, !!message)}
      {message ? (
        <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
          {message}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

interface FormFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label?: string;
  hint?: string;
  error?: FieldError | string;
}

export const FormField = forwardRef<HTMLInputElement, FormFieldProps>(
  ({ label, hint, error, required, className, ...props }, ref) => (
    <FieldWrapper label={label} hint={hint} error={error} required={required} className={className}>
      {(id, describedBy, invalid) => (
        <Input ref={ref} id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} required={required} {...props} />
      )}
    </FieldWrapper>
  ),
);
FormField.displayName = 'FormField';

interface MoneyInputProps {
  label?: string;
  hint?: string;
  error?: FieldError | string;
  required?: boolean;
  /** Value in paise (the API unit); the input shows rupees. */
  value: number | null | undefined;
  onChange: (paise: number | null) => void;
  currencySymbol?: string;
  disabled?: boolean;
  className?: string;
}

/** Money is entered in rupees and stored/sent as INTEGER paise. */
export function MoneyInput({ label, hint, error, required, value, onChange, currencySymbol = '₹', disabled, className }: MoneyInputProps) {
  return (
    <FieldWrapper label={label} hint={hint} error={error} required={required} className={className}>
      {(id, describedBy, invalid) => (
        <div className="relative">
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-muted-foreground">
            {currencySymbol}
          </span>
          <Input
            id={id}
            type="number"
            inputMode="decimal"
            step="0.01"
            min={0}
            className="pl-7 text-right tabular-nums"
            aria-describedby={describedBy}
            aria-invalid={invalid || undefined}
            disabled={disabled}
            value={value === null || value === undefined ? '' : paiseToRupees(value)}
            onChange={(e) => onChange(e.target.value === '' ? null : rupeesToPaise(e.target.value))}
          />
        </div>
      )}
    </FieldWrapper>
  );
}

interface DateFieldProps {
  label?: string;
  hint?: string;
  error?: FieldError | string;
  required?: boolean;
  /** ISO date `YYYY-MM-DD` — academic dates are institution-local DATE columns, never shifted by browser TZ. */
  value: string | null | undefined;
  onChange: (iso: string | null) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  className?: string;
}

export function DateField({ label, hint, error, required, value, onChange, min, max, disabled, className }: DateFieldProps) {
  return (
    <FieldWrapper label={label} hint={hint} error={error} required={required} className={className}>
      {(id, describedBy, invalid) => (
        <Input
          id={id}
          type="date"
          min={min}
          max={max}
          disabled={disabled}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      )}
    </FieldWrapper>
  );
}
