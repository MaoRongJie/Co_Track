import React from 'react';

interface AppErrorBoundaryProps {
  children: React.ReactNode;
  title?: string;
}

interface AppErrorBoundaryState {
  hasError: boolean;
  message: string;
}

class AppErrorBoundary extends React.Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
    message: '',
  };

  static getDerivedStateFromError(error: unknown): AppErrorBoundaryState {
    const message = error instanceof Error ? error.message : '未知渲染错误';
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown, errorInfo: React.ErrorInfo): void {
    // Keep a clear breadcrumb in console for local debugging.
    console.error('[AppErrorBoundary]', error, errorInfo);
  }

  render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        <p className="font-semibold">{this.props.title ?? '界面渲染失败'}</p>
        <p className="mt-1 text-xs">{this.state.message}</p>
      </div>
    );
  }
}

export default AppErrorBoundary;
