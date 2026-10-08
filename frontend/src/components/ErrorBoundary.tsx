import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

export class ErrorBoundary extends Component<
  { children: ReactNode; resetKey?: string },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="card mx-auto mt-10 max-w-md text-center">
        <h2 className="text-lg font-semibold">Something went wrong</h2>
        <p className="mt-1 text-sm text-muted">This page hit an unexpected problem.</p>
        <button className="btn-primary mt-4" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
