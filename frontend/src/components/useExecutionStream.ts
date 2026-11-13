import { useEffect, useState } from 'react';
import { streamExecution } from '@/api/sse';
import { errorMessage } from '@/api/errors';
import type { ExecutionEvent } from '@/types/api';

/** Subscribes to an execution's live event stream. */
export function useExecutionStream(executionId: string | null | undefined) {
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setEvents([]);
    setDone(false);
    setError(null);
    if (!executionId) return;
    const ac = new AbortController();
    streamExecution(executionId, { signal: ac.signal, onEvent: (e) => setEvents((prev) => [...prev, e]) })
      .then(() => !ac.signal.aborted && setDone(true))
      .catch((e) => setError(errorMessage(e)));
    return () => ac.abort();
  }, [executionId]);
  return { events, done, error };
}
