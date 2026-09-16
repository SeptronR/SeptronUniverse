import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { MessageSquarePlus, Star } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Select, Textarea } from '@/components/ui/Input';
import { FieldWrapper } from '@/components/shared/FormField';
import { toast } from '@/components/ui/Toaster';
import { getApiError } from '@/api/axios';
import { useFeature } from '@/hooks/useFeature';
import { cn } from '@/utils/cn';
import { useReadOnly, useSubmitFeedback } from '../hooks';

const schema = z.object({
  category: z.enum(['bug', 'idea', 'question', 'praise']),
  rating: z.number().int().min(1).max(5).nullable(),
  message: z.string().trim().min(3, 'Tell us a little more (at least 3 characters)').max(4000),
});
type FeedbackForm = z.infer<typeof schema>;

const CATEGORIES = [
  { value: 'bug', label: 'Something is broken' },
  { value: 'idea', label: 'Idea / improvement' },
  { value: 'question', label: 'Question' },
  { value: 'praise', label: 'Praise' },
];

/** In-app feedback widget (Prompts/01 §01.9): RHF + Zod form, submits POST /feedback and toasts the result. */
export function FeedbackDialog({ trigger }: { trigger?: React.ReactNode }) {
  const enabled = useFeature('platform.in_app_feedback');
  const readOnly = useReadOnly();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const submit = useSubmitFeedback();
  const form = useForm<FeedbackForm>({
    resolver: zodResolver(schema),
    defaultValues: { category: 'idea', rating: null, message: '' },
  });
  const rating = form.watch('rating');

  if (!enabled) return null;

  const onSubmit = (values: FeedbackForm) =>
    submit.mutate(
      { ...values, page: location.pathname, client: 'web' },
      {
        onSuccess: (res) => {
          toast.success(res.message ?? 'Thanks for the feedback');
          form.reset();
          setOpen(false);
        },
        onError: (e) => toast.error(getApiError(e, 'Could not send feedback')),
      },
    );

  return (
    <>
      <span onClick={() => setOpen(true)} role="presentation">
        {trigger ?? (
          <Button variant="outline" size="sm" data-write disabled={readOnly}>
            <MessageSquarePlus className="h-4 w-4" /> Send feedback
          </Button>
        )}
      </span>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Send feedback"
        description={`About ${location.pathname}`}
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button form="feedback-form" type="submit" data-write disabled={readOnly} loading={submit.isPending}>
              Send
            </Button>
          </>
        }
      >
        <form id="feedback-form" className="space-y-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <FieldWrapper label="Category" error={form.formState.errors.category}>
            {(id, describedBy, invalid) => (
              <Select
                id={id}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
                options={CATEGORIES}
                {...form.register('category')}
              />
            )}
          </FieldWrapper>
          <FieldWrapper label="How is this page working for you?" hint="Optional">
            {() => (
              <div className="flex gap-1" role="radiogroup" aria-label="Rating">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    role="radio"
                    aria-checked={rating === n}
                    aria-label={`${n} star${n > 1 ? 's' : ''}`}
                    onClick={() => form.setValue('rating', rating === n ? null : n, { shouldDirty: true })}
                    className="rounded p-1 hover:bg-accent"
                  >
                    <Star
                      className={cn(
                        'h-5 w-5',
                        rating && n <= rating ? 'fill-status-pending text-status-pending' : 'text-muted-foreground',
                      )}
                    />
                  </button>
                ))}
              </div>
            )}
          </FieldWrapper>
          <FieldWrapper label="Message" required error={form.formState.errors.message}>
            {(id, describedBy, invalid) => (
              <Textarea
                id={id}
                rows={5}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
                placeholder="What happened, or what would help?"
                {...form.register('message')}
              />
            )}
          </FieldWrapper>
        </form>
      </Modal>
    </>
  );
}
