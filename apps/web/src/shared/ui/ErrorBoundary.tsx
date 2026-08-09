import { Component, type ErrorInfo, type ReactNode } from 'react';
import { RefreshCw, TriangleAlert } from 'lucide-react';
import i18n from '@/shared/i18n';

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { void error; void info; console.error('Unhandled application error [UI_UNHANDLED]'); }
  render() {
    if (this.state.failed) return <main className="fatal-error">
      <span className="fatal-error-icon" aria-hidden="true"><TriangleAlert size={24} /></span>
      <h1>{i18n.t('fatalTitle')}</h1>
      <p>{i18n.t('fatalBody')}</p>
      <button className="button button-primary" onClick={() => window.location.reload()}><RefreshCw size={15} />{i18n.t('reload')}</button>
    </main>;
    return this.props.children;
  }
}
