"use client";
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { title: string; onClose?: () => void; closeLabel?: string; compact?: boolean; children: ReactNode };

/**
 * Keeps a failing part of the desktop to itself: a window, the board panel, an
 * editor or a single board card. Without it one malformed board or app takes the
 * whole desktop down, and because open windows and selections are remembered it
 * would crash again on every reload.
 */
export class WindowBoundary extends Component<Props, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(`${this.props.title} failed`, error, info.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    const { title, onClose, closeLabel = "Close window", compact } = this.props;
    if (compact) return <div className="dk-window-error is-compact" role="alert"><strong>{title} could not be shown</strong><button type="button" className="text-button" onClick={() => this.setState({ error: null })}>Try again</button></div>;
    return <div className="dk-window-error" role="alert">
      <strong>{title} stopped working</strong>
      <p>The rest of your desktop is fine. Your boards and saved work are unaffected.</p>
      <code>{this.state.error.message}</code>
      <div>
        <button type="button" className="primary-button" onClick={() => this.setState({ error: null })}>Try again</button>
        {onClose ? <button type="button" className="secondary-button" onClick={onClose}>{closeLabel}</button> : null}
      </div>
    </div>;
  }
}
