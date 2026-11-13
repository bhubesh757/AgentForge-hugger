import { API_BASE_URL, DEMO_MODE } from '@/config';
import type { ExecutionEvent } from '@/types/api';
import { TERMINAL_EVENTS } from '@/types/api';
import { authHeaders, bootstrapSession } from './client';
import { session } from './session';
import { mockEventsAfter } from './mock/db';

export interface StreamOptions {
  onEvent: (e: ExecutionEvent) => void;
  signal: AbortSignal;
  afterSequence?: number;
  maxReconnects?: number;
}

/** Parses an SSE text buffer; returns complete messages and the unconsumed remainder. */
export function parseSSE(buffer: string): { messages: { id?: string; event?: string; data: string }[]; rest: string } {
  const parts = buffer.replace(/\r\n/g, '\n').split('\n\n');
  const rest = parts.pop() ?? '';
  const messages = parts
    .map((block) => {
      const m: { id?: string; event?: string; data: string } = { data: '' };
      const data: string[] = [];
      for (const line of block.split('\n')) {
        if (!line || line.startsWith(':')) continue;
        const idx = line.indexOf(':');
        const field = idx === -1 ? line : line.slice(0, idx);
        const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '');
        if (field === 'id') m.id = value;
        else if (field === 'event') m.event = value;
        else if (field === 'data') data.push(value);
      }
      m.data = data.join('\n');
      return m;
    })
    .filter((m) => m.data);
  return { messages, rest };
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => (clearTimeout(t), resolve()), { once: true });
  });

/** Streams execution events (fetch streaming, Last-Event-ID resume). Resolves when a terminal event arrives or aborted. */
export async function streamExecution(executionId: string, opts: StreamOptions): Promise<void> {
  let last = opts.afterSequence ?? 0;
  const emit = (e: ExecutionEvent) => {
    if (e.sequence <= last) return false;
    last = e.sequence;
    opts.onEvent(e);
    return TERMINAL_EVENTS.includes(e.event_type);
  };

  if (DEMO_MODE) {
    while (!opts.signal.aborted) {
      for (const e of mockEventsAfter(executionId, last)) if (emit(e)) return;
      await sleep(250, opts.signal);
    }
    return;
  }

  let attempts = 0;
  const max = opts.maxReconnects ?? 5;
  while (!opts.signal.aborted && attempts <= max) {
    try {
      const headers: Record<string, string> = { ...authHeaders(), Accept: 'text/event-stream' };
      if (last > 0) headers['Last-Event-ID'] = String(last);
      const res = await fetch(`${API_BASE_URL}/executions/${executionId}/stream?after_sequence=${last}`, { headers, signal: opts.signal });
      if (res.status === 401 && session.getRefresh()) {

        if (!(await bootstrapSession(true))) throw new Error("Session expired");
        attempts++;
        continue;
      }
      if (!res.ok || !res.body) throw new Error(`Stream failed: HTTP ${res.status}`);
      attempts = 0;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const { messages, rest } = parseSSE(buf);
        buf = rest;
        for (const m of messages) {
          try {
            if (emit(JSON.parse(m.data) as ExecutionEvent)) return;
          } catch {
            /* malformed message ignored */
          }
        }
      }
    } catch (e) {
      if (opts.signal.aborted) return;
      if (attempts >= max) throw e;
    }
    attempts++;
    await sleep(Math.min(1000 * 2 ** attempts, 10_000), opts.signal);
  }
}
