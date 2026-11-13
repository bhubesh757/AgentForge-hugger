import { Component, type ErrorInfo, type ReactNode } from 'react';

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI error', error, info.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="card m-6">
        <h2 className="font-semibold text-rose-600">Something went wrong</h2>
        <p className="mt-1 text-sm text-slate-500">{this.state.error.message}</p>
        <button className="btn-ghost mt-3" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
