import { AlertTriangle, Clapperboard, LoaderCircle, RefreshCw } from "lucide-react";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state-card" role="status">
      <LoaderCircle className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-card state-error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <strong>Couldn’t reach Darius</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button className="text-button" onClick={onRetry} type="button">
          <RefreshCw size={14} aria-hidden="true" /> Retry
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><Clapperboard aria-hidden="true" /></span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
