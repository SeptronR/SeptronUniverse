import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/Button';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}
interface State {
  error: Error | null;
}

/** Catches render errors per route so one broken page never blanks the whole shell. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) console.error('Render error', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.fallback) return this.props.fallback;
    return (
      <div role="alert" className="m-6 rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
        <AlertTriangle className="mx-auto mb-2 h-6 w-6 text-destructive" />
        <p className="font-medium">Something went wrong while rendering this page.</p>
        <p className="mt-1 text-sm text-muted-foreground">{this.state.error.message}</p>
        <Button className="mt-4" variant="outline" onClick={() => this.setState({ error: null })}>
          Try again
        </Button>
      </div>
    );
  }
}
