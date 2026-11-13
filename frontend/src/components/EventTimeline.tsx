import type { ExecutionEvent } from '@/types/api';
import { Badge } from './ui';

export function EventTimeline({ events }: { events: ExecutionEvent[] }) {
  const tokens = events.filter((e) => e.event_type === 'llm.token').map((e) => String(e.payload.text ?? '')).join('');
  const rest = events.filter((e) => e.event_type !== 'llm.token');
  return (
    <div className="space-y-2">
      {tokens && <div className="rounded-md bg-slate-100 p-3 text-sm dark:bg-slate-800">{tokens}</div>}
      <ol className="space-y-1 text-xs" aria-label="Execution events">
        {rest.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-2 font-mono">
            <span className="text-slate-400">#{e.sequence}</span>
            <Badge>{e.event_type.replace('execution.', '').replace('completed', 'succeeded')}</Badge>
            {e.node_id && <span className="text-brand-400">{e.node_id}</span>}
            {Object.keys(e.payload).length > 0 && <span className="truncate text-slate-500">{JSON.stringify(e.payload)}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
