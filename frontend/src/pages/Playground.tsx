import { useState } from 'react';
import { Plus, Send, X } from 'lucide-react';
import { API_BASE_URL, DEMO_MODE } from '@/config';
import { authHeaders } from '@/api/client';
import { mockRequest } from '@/api/mock/adapter';
import LazyEditor from '@/components/LazyEditor';
import { Badge, CopyButton, PageHeader } from '@/components/ui';
import { fmtMs, tryParseJSON } from '@/lib/format';

type KV = { k: string; v: string };
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
export const CATALOG: [string, string][] = [
  ['GET', '/health'], ['GET', '/auth/me'], ['GET', '/organizations'], ['GET', '/llm/providers'], ['GET', '/credentials'],
  ['GET', '/agents'], ['POST', '/agents/generate'], ['GET', '/tools'], ['POST', '/tools/generate'], ['GET', '/workflows'],
  ['GET', '/executions'], ['GET', '/chat/sessions'], ['GET', '/deployments'], ['GET', '/monitoring/summary'],
];

/** Builds curl and python httpx snippets for a request. */
export function snippets(method: string, url: string, headers: Record<string, string>, body: string | null) {
  const h = Object.entries(headers);
  const curl = [`curl -X ${method} '${url}'`, ...h.map(([k, v]) => `  -H '${k}: ${v}'`), ...(body ? [`  --data '${body.replace(/'/g, "'\\''")}'`] : [])].join(' \\\n');
  const py = [
    'import httpx', '',
    `resp = httpx.request(`, `    "${method}",`, `    "${url}",`,
    `    headers=${JSON.stringify(headers, null, 4).replace(/\n/g, '\n    ')},`,
    ...(body ? [`    json=${body.replace(/\btrue\b/g, 'True').replace(/\bfalse\b/g, 'False').replace(/\bnull\b/g, 'None')},`] : []),
    ')', 'print(resp.status_code, resp.json())',
  ].join('\n');
  return { curl, py };
}

export default function Playground() {
  const [method, setMethod] = useState('GET');
  const [url, setUrl] = useState(`${API_BASE_URL}/agents`);
  const [headers, setHeaders] = useState<KV[]>([{ k: 'Accept', v: 'application/json' }]);
  const [query, setQuery] = useState<KV[]>([]);
  const [body, setBody] = useState('{\n  \n}');
  const [useAuthHeaders, setUseAuth] = useState(true);
  const [res, setRes] = useState<{ status: number; ms: number; body: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const hasBody = method !== 'GET' && method !== 'DELETE';
  const parsed = tryParseJSON(body);

  const fullUrl = () => {
    const u = new URL(url, window.location.href);
    query.filter((q) => q.k).forEach((q) => u.searchParams.set(q.k, q.v));
    return u.toString();
  };
  const hdrs = () => ({ ...(hasBody ? { 'Content-Type': 'application/json' } : {}), ...Object.fromEntries(headers.filter((h) => h.k).map((h) => [h.k, h.v])), ...(useAuthHeaders ? authHeaders() : {}) });

  const sendReq = async () => {
    setBusy(true);
    const t0 = performance.now();
    try {
      const u = fullUrl();
      const data = hasBody && body.trim() ? body : undefined;
      if (DEMO_MODE && u.startsWith(API_BASE_URL)) {
        const r = await mockRequest({ method, url: u, data, headers: hdrs() });
        setRes({ status: r.status, ms: performance.now() - t0, body: JSON.stringify(r.data, null, 2) });
      } else {
        const r = await fetch(u, { method, headers: hdrs(), body: data });
        const txt = await r.text();
        const j = tryParseJSON(txt);
        setRes({ status: r.status, ms: performance.now() - t0, body: j.ok ? JSON.stringify(j.value, null, 2) : txt });
      }
    } catch (e) {
      setRes({ status: 0, ms: performance.now() - t0, body: `Request failed: ${(e as Error).message}` });
    } finally {
      setBusy(false);
    }
  };

  const kvEditor = (label: string, rows: KV[], set: (r: KV[]) => void) => (
    <div>
      <div className="mb-1 flex items-center justify-between"><span className="label">{label}</span><button className="btn-ghost !px-2 !py-0.5 text-xs" onClick={() => set([...rows, { k: '', v: '' }])}><Plus className="h-3 w-3" />Add</button></div>
      {rows.map((r, i) => (
        <div key={i} className="mb-1 flex gap-1">
          <input className="input" aria-label={`${label} key`} placeholder="key" value={r.k} onChange={(e) => set(rows.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} />
          <input className="input" aria-label={`${label} value`} placeholder="value" value={r.v} onChange={(e) => set(rows.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} />
          <button className="btn-ghost !px-2" aria-label="Remove" onClick={() => set(rows.filter((_, j) => j !== i))}><X className="h-3 w-3" /></button>
        </div>
      ))}
    </div>
  );
  const snip = snippets(method, (() => { try { return fullUrl(); } catch { return url; } })(), { ...hdrs(), ...(useAuthHeaders ? { Authorization: 'Bearer <token>' } : {}) }, hasBody && parsed.ok && parsed.value != null ? JSON.stringify(parsed.value) : null);

  return (
    <>
      <PageHeader title="API Playground" subtitle={DEMO_MODE ? 'Demo mode: API-base requests are served by the in-browser mock backend' : 'Send requests to the AgentForge API'} />
      <div className="grid gap-4 lg:grid-cols-4">
        <div className="card lg:col-span-3 space-y-3">
          <div className="flex gap-2">
            <select className="input max-w-[7rem]" aria-label="Method" value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map((m) => <option key={m}>{m}</option>)}</select>
            <input className="input font-mono" aria-label="URL" value={url} onChange={(e) => setUrl(e.target.value)} />
            <button className="btn-primary" onClick={sendReq} disabled={busy || (hasBody && !parsed.ok)}><Send className="h-4 w-4" />{busy ? 'Sending…' : 'Send'}</button>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={useAuthHeaders} onChange={(e) => setUseAuth(e.target.checked)} />Attach my auth + organization headers</label>
          <div className="grid gap-3 md:grid-cols-2">{kvEditor('Headers', headers, setHeaders)}{kvEditor('Query params', query, setQuery)}</div>
          {hasBody && <div><span className="label">JSON body</span><LazyEditor value={body} onChange={setBody} height={180} />{!parsed.ok && <span className="text-xs text-rose-500">{parsed.error}</span>}</div>}
          {res && (
            <div>
              <div className="mb-1 flex items-center gap-3 text-sm"><Badge>{res.status >= 200 && res.status < 300 ? 'succeeded' : 'failed'}</Badge><span>Status {res.status || 'network error'}</span><span className="text-slate-500">{fmtMs(res.ms)}</span><CopyButton text={res.body} /></div>
              <pre className="pre" data-testid="response">{res.body}</pre>
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            <div><div className="flex items-center justify-between"><span className="label">curl</span><CopyButton text={snip.curl} /></div><pre className="pre">{snip.curl}</pre></div>
            <div><div className="flex items-center justify-between"><span className="label">Python (httpx)</span><CopyButton text={snip.py} /></div><pre className="pre">{snip.py}</pre></div>
          </div>
        </div>
        <div className="card">
          <h2 className="mb-2 font-medium">Endpoint catalog</h2>
          <ul className="space-y-0.5 text-xs">
            {CATALOG.map(([m, p]) => (
              <li key={m + p}><button className="w-full rounded px-1 py-0.5 text-left font-mono hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => (setMethod(m), setUrl(`${API_BASE_URL}${p}`))}>
                <span className="inline-block w-10 text-brand-500">{m}</span>{p}</button></li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
