"use client";

import { logger } from "@/services/logger";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
}

export class GlobalErrorBoundary extends Component<Props, State> {
  state: State = {
    hasError: false,
  };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    logger.error({
      message: "Global UI boundary caught an error",
      error,
      context: { componentStack: errorInfo.componentStack },
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="grid min-h-[60vh] place-items-center px-6">
            <div className="max-w-xl rounded-2xl border border-rose-400/35 bg-rose-950/35 p-6 text-sm text-rose-100 backdrop-blur">
              <p className="mb-2 text-base font-semibold uppercase tracking-[0.12em]">
                Rendering fault detected
              </p>
              <p>
                The terminal UI recovered into safe mode. Refresh the page to
                re-establish all real-time streams.
              </p>
            </div>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
