import { Toaster as SonnerToaster, toast } from 'sonner';

/** Every async result surfaces a toast (frontend coding standard 2). Themed via the `.dark` class. */
export function Toaster() {
  return (
    <SonnerToaster
      position="top-right"
      richColors
      closeButton
      toastOptions={{ classNames: { toast: 'font-sans text-sm' } }}
    />
  );
}

export { toast };
