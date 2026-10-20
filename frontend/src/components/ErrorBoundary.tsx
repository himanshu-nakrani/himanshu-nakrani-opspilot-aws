import React from 'react';
import { AlertOctagon } from 'lucide-react';

interface Props {
  children: React.ReactNode;
  /** Shown in the fallback, e.g. "Evals report" */
  label?: string;
  onReset?: () => void;
  /** Inline fallback (inside a dialog) vs full page */
  inline?: boolean;
}

interface State {
  error: Error | null;
}

/** Stops a render error in one panel from blanking the whole dashboard. */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[OpsPilot] ${this.props.label ?? 'UI'} crashed:`, error, info.componentStack);
  }

  reset = () => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div
        role="alert"
        className={`${
          this.props.inline ? '' : 'min-h-screen flex items-center justify-center p-8'
        } text-slate-200`}
      >
        <div className="max-w-lg w-full p-5 rounded-xl bg-red-500/10 border border-red-500/30 space-y-3">
          <div className="flex items-center gap-2 text-red-300 font-semibold text-sm">
            <AlertOctagon className="w-4 h-4" aria-hidden="true" />
            {this.props.label ?? 'This view'} failed to render
          </div>
          <p className="text-xs text-red-200/90 font-mono break-words">{error.message}</p>
          <button
            type="button"
            onClick={this.reset}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
}
