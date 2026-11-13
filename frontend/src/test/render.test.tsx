import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/state/auth';
import { AppRoutes } from '@/App';
import Playground, { snippets } from '@/pages/Playground';
import { BarChart } from '@/pages/Ops';

describe('render smoke tests', () => {
  it('redirects unauthenticated users to the login page', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/agents']}>
          <AuthProvider><AppRoutes /></AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole('button', { name: /sign in|log in/i })).toBeInTheDocument();
  });
  it('renders the API playground with code snippets', () => {
    render(<Playground />);
    expect(screen.getByRole('heading', { name: 'API Playground' })).toBeInTheDocument();
    expect(screen.getByText(/curl -X GET/)).toBeInTheDocument();
  });
  it('renders an SVG bar chart', () => {
    render(<BarChart title="By status" data={{ succeeded: 3, failed: 1 }} />);
    expect(screen.getByRole('img', { name: 'By status' })).toBeInTheDocument();
  });
  it('builds curl and httpx snippets', () => {
    const s = snippets('POST', 'http://x/api/v1/agents', { A: 'b' }, '{"ok":true}');
    expect(s.curl).toContain("-H 'A: b'");
    expect(s.py).toContain('json={"ok":True}');
  });
});
