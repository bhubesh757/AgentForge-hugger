import { useState, type ReactNode } from 'react';
import { AlertTriangle, Check, Copy, Inbox, Loader2, X } from 'lucide-react';
import { errorMessage } from '@/api/errors';

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
export const Spinner = ({ label = 'Loading…' }: { label?: string }) => (
  <div role="status" className="flex items-center gap-2 p-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />{label}</div>
);
export const Empty = ({ children = 'Nothing here yet.' }: { children?: ReactNode }) => (
  <div className="flex flex-col items-center gap-2 p-8 text-sm text-slate-500"><Inbox className="h-6 w-6" />{children}</div>
);
export const ErrorState = ({ error }: { error: unknown }) => (
  <div role="alert" className="flex items-start gap-2 rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{errorMessage(error)}
  </div>
);
/** Renders loading / error / empty for a query, otherwise children. */
export function QueryState({ q, empty, children }: { q: { isLoading: boolean; error: unknown }; empty?: boolean; children: ReactNode }) {
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} />;
  if (empty) return <Empty />;
  return <>{children}</>;
}
const COLORS: Record<string, string> = {
  succeeded: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  published: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  active: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  valid: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
  running: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
  queued: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  failed: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  invalid: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
};
export const Badge = ({ children }: { children: string }) => (
  <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${COLORS[children] ?? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'}`}>{children}</span>
);
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`card mt-12 w-full ${wide ? 'max-w-4xl' : 'max-w-lg'}`}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">{title}</h2>
          <button className="btn-ghost !p-1" onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block"><span className="label">{label}</span>{children}</label>;
}
export function CopyButton({ text }: { text: string }) {
  const [ok, setOk] = useState(false);
  return (
    <button type="button" className="btn-ghost !px-2 !py-1 text-xs" aria-label="Copy to clipboard"
      onClick={() => navigator.clipboard?.writeText(text).then(() => (setOk(true), setTimeout(() => setOk(false), 1200))).catch(() => undefined)}>
      {ok ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{ok ? 'Copied' : 'Copy'}
    </button>
  );
}
export const Json = ({ value }: { value: unknown }) => <pre className="pre">{JSON.stringify(value, null, 2)}</pre>;
