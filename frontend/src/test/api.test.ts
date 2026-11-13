import { describe, expect, it } from 'vitest';
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import { ApiError, errorMessage, parseApiError } from '@/api/errors';
import { mockRequest } from '@/api/mock/adapter';
import { DEMO_USER } from '@/api/mock/db';
import { parseSSE } from '@/api/sse';

const cfg = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
const axErr = (status: number, data: unknown) =>
  new AxiosError('fail', 'ERR', cfg, {}, { status, data, statusText: '', headers: {}, config: cfg });

describe('API error parsing', () => {
  it('parses the contract error envelope', () => {
    const e = parseApiError(axErr(404, { error: { code: 'NOT_FOUND', message: 'Agent not found', request_id: 'r1' } }));
    expect(e).toBeInstanceOf(ApiError);
    expect([e.code, e.message, e.status, e.requestId]).toEqual(['NOT_FOUND', 'Agent not found', 404, 'r1']);
    expect(errorMessage(e)).toBe('Agent not found (NOT_FOUND, request r1)');
  });
  it('handles network and non-envelope errors', () => {
    expect(parseApiError(new AxiosError('net', 'ERR_NETWORK', cfg)).code).toBe('NETWORK_ERROR');
    expect(parseApiError(axErr(502, '<html>')).code).toBe('INTERNAL_ERROR');
    expect(parseApiError(new Error('boom')).code).toBe('CLIENT_ERROR');
    expect(parseApiError('x').message).toBe('x');
  });
});

describe('SSE parser', () => {
  it('splits complete messages and keeps the remainder', () => {
    const r = parseSSE('id: 1\nevent: log\ndata: {"a":1}\n\ndata: part');
    expect(r.messages).toHaveLength(1);
    expect(r.messages[0]).toMatchObject({ id: '1', event: 'log', data: '{"a":1}' });
    expect(r.rest).toContain('part');
  });
});

describe('mock backend', () => {
  it('serves health without auth', async () => {
    const r = await mockRequest({ method: 'GET', url: '/api/v1/health' });
    expect(r.status).toBe(200);
    expect(r.data).toMatchObject({ status: 'ok' });
  });
  it('rejects unauthenticated org routes with the error envelope', async () => {
    const r = await mockRequest({ method: 'GET', url: '/api/v1/agents' });
    expect(r.status).toBe(401);
    expect(r.data).toMatchObject({ error: { code: 'UNAUTHENTICATED' } });
  });
  it('logs in the demo user and lists agents in their org', async () => {
    const login = await mockRequest({ method: 'POST', url: '/api/v1/auth/login', data: DEMO_USER });
    expect(login.status).toBe(200);
    const token = (login.data as { access_token: string }).access_token;
    const me = await mockRequest({ method: 'GET', url: '/api/v1/auth/me', headers: { Authorization: `Bearer ${token}` } });
    const org = (me.data as { memberships: { organization_id: string }[] }).memberships[0].organization_id;
    const agents = await mockRequest({ method: 'GET', url: '/api/v1/agents', headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': org } });
    expect(agents.status).toBe(200);
    expect(agents.data).toHaveProperty('items');
    const missing = await mockRequest({ method: 'GET', url: '/api/v1/nope', headers: { Authorization: `Bearer ${token}` } });
    expect(missing.status).toBe(404);
  });
});
