import { describe, expect, it } from 'vitest';
import axios from 'axios';
import { mockAdapter } from '@/api/mock/adapter';
import { DEMO_USER } from '@/api/mock/db';

// Regression: the deployed demo failed with "AxiosHeaders.from(...).forEach is not a function"
// because tests only called mockRequest directly. These go through a real axios instance.
const http = axios.create({ baseURL: 'https://api.example.test/api/v1', adapter: mockAdapter });

describe('mockAdapter via axios', () => {
  it('logs in and calls an org-scoped endpoint with auth + org headers', async () => {
    const login = await http.post('/auth/login', { email: DEMO_USER.email, password: DEMO_USER.password });
    expect(login.status).toBe(200);
    const token = login.data.access_token as string;
    expect(token).toBeTruthy();

    const me = await http.get('/auth/me', { headers: { Authorization: `Bearer ${token}` } });
    const orgId = me.data.memberships[0].organization_id as string;

    const agents = await http.get('/agents', {
      headers: { Authorization: `Bearer ${token}`, 'X-Organization-ID': orgId },
      params: { page: 1, page_size: 5 },
    });
    expect(agents.status).toBe(200);
    expect(Array.isArray(agents.data.items)).toBe(true);
  });

  it('rejects org-scoped calls without the org header as an AxiosError', async () => {
    const login = await http.post('/auth/login', { email: DEMO_USER.email, password: DEMO_USER.password });
    await expect(
      http.get('/agents', { headers: { Authorization: `Bearer ${login.data.access_token}` } }),
    ).rejects.toMatchObject({ response: { status: 400 } });
  });
});
