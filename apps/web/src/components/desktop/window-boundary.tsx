"use client";
import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Keeps a failing app inside its own window. Without it one broken window takes
 * the whole desktop down, and because open windows are remembered, it would
 * crash again on every reload.
 */
export class WindowBoundary extends Component<{ title: string; onClose: () => void; children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(`${this.props.title} window failed`, error, info.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="dk-window-error" role="alert">
      <strong>{this.props.title} stopped working</strong>
      <p>The rest of your desktop is fine. Your boards and saved work are unaffected.</p>
      <code>{this.state.error.message}</code>
      <div>
        <button type="button" className="primary-button" onClick={() => this.setState({ error: null })}>Try again</button>
        <button type="button" className="secondary-button" onClick={this.props.onClose}>Close window</button>
      </div>
    </div>;
  }
}
