import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Executions } from '@/api/endpoints';
import { tryParseJSON } from '@/lib/format';
import { EventTimeline } from './EventTimeline';
import { useExecutionStream } from './useExecutionStream';
import { Badge, ErrorState, Field, Json } from './ui';

/** Live event timeline + final output for one execution. */
export function ExecutionPanel({ id }: { id: string | null }) {
  const { events, done, error } = useExecutionStream(id);
  const ex = useQuery({ queryKey: ['execution', id], queryFn: () => Executions.get(id!), enabled: !!id && done });
  if (!id) return null;
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        Execution <Link className="font-mono text-brand-500" to={`/executions/${id}`}>{id.slice(0, 8)}</Link>
        {ex.data ? <Badge>{ex.data.status}</Badge> : <Badge>{done ? 'finished' : 'running'}</Badge>}
      </div>
      {error && <ErrorState error={new Error(error)} />}
      <EventTimeline events={events} />
      {ex.data?.output != null && <Json value={ex.data.output} />}
      {ex.data?.error && <ErrorState error={new Error(ex.data.error)} />}
    </div>
  );
}

/** JSON textarea that reports parse errors inline. */
export function JsonInput({ label, value, onChange, rows = 4 }: { label: string; value: string; onChange: (v: string) => void; rows?: number }) {
  const parsed = tryParseJSON(value);
  return (
    <Field label={label}>
      <textarea className="input font-mono" rows={rows} value={value} onChange={(e) => onChange(e.target.value)} />
      {!parsed.ok && <span className="text-xs text-rose-500">Invalid JSON: {parsed.error}</span>}
    </Field>
  );
}

export function useJsonState(initial: unknown) {
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2));
  const p = tryParseJSON(text);
  return { text, setText, ok: p.ok, value: p.ok ? p.value : undefined };
}

export const Search = ({ value, onChange, placeholder = 'Search…' }: { value: string; onChange: (v: string) => void; placeholder?: string }) => (
  <input className="input max-w-xs" type="search" aria-label="Search" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
);
