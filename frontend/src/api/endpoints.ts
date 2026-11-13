import { api } from './client';
import type * as T from '@/types/api';

const get = <R,>(url: string, params?: object) => api.get<R>(url, { params }).then((r) => r.data);
const post = <R,>(url: string, body?: unknown) => api.post<R>(url, body ?? {}).then((r) => r.data);
const put = <R,>(url: string, body: unknown) => api.put<R>(url, body).then((r) => r.data);
const del = (url: string) => api.delete(url).then(() => undefined);
type Q = Record<string, string | number | undefined>;

export const Auth = {
  login: (email: string, password: string) => post<T.TokenPair>('/auth/login', { email, password }),
  register: (b: { email: string; password: string; full_name: string; organization_name?: string }) => post<T.TokenPair>('/auth/register', b),
  logout: (refresh_token: string) => post<void>('/auth/logout', { refresh_token }),
  me: () => get<T.Me>('/auth/me'),
};
export const Orgs = {
  list: () => get<T.Page<T.OrganizationWithRole>>('/organizations', { page_size: 100 }),
  create: (b: { name: string; slug?: string }) => post<T.Organization>('/organizations', b),
  update: (id: string, b: { name?: string }) => put<T.Organization>(`/organizations/${id}`, b),
  members: (id: string) => get<T.Page<T.Member>>(`/organizations/${id}/members`, { page_size: 100 }),
  addMember: (id: string, b: { email: string; role: T.Role }) => post<T.Member>(`/organizations/${id}/members`, b),
  removeMember: (id: string, userId: string) => del(`/organizations/${id}/members/${userId}`),
};
export const Providers = {
  list: () => get<T.Page<T.LLMProvider>>('/llm/providers', { page_size: 100 }),
  connect: (b: T.ConnectProvider) => post<T.LLMProvider>('/llm/providers/connect', b),
  validate: (id: string) => post<{ valid: boolean; message: string; provider: T.LLMProvider }>(`/llm/providers/${id}/validate`),
  models: (id: string) => get<{ models: { id: string; display_name: string }[] }>(`/llm/providers/${id}/models`),
  activate: (id: string, default_model?: string) => post<T.LLMProvider>(`/llm/providers/${id}/activate`, default_model ? { default_model } : {}),
  deactivate: (id: string) => post<T.LLMProvider>(`/llm/providers/${id}/deactivate`),
  remove: (id: string) => del(`/llm/providers/${id}`),
};
export const Credentials = {
  list: () => get<T.Page<T.Credential>>('/credentials', { page_size: 100 }),
  create: (b: { name: string; kind: T.CredentialKind; value: string; description?: string }) => post<T.Credential>('/credentials', b),
  validate: (id: string) => post<{ valid: boolean; message: string }>(`/credentials/${id}/validate`),
  rotate: (id: string, value: string) => post<T.Credential>(`/credentials/${id}/rotate`, { value }),
  remove: (id: string) => del(`/credentials/${id}`),
};
export const Agents = {
  list: (q: Q = {}) => get<T.Page<T.Agent>>('/agents', { page_size: 100, ...q }),
  get: (id: string) => get<T.Agent>(`/agents/${id}`),
  create: (b: { name: string; description?: string; config: T.AgentConfig }) => post<T.Agent>('/agents', b),
  update: (id: string, b: Partial<Pick<T.Agent, 'name' | 'description' | 'config'>>) => put<T.Agent>(`/agents/${id}`, b),
  generate: (prompt: string, provider_id?: string) => post<{ draft: T.AgentDraft }>('/agents/generate', { prompt, provider_id }),
  test: (id: string, input: unknown) => post<T.Execution>(`/agents/${id}/test`, { input }),
  execute: (id: string, input: unknown) => post<T.Execution>(`/agents/${id}/execute`, { input, stream: true }),
  publish: (id: string) => post<T.Agent>(`/agents/${id}/publish`),
  versions: (id: string) => get<T.Page<T.AgentVersion>>(`/agents/${id}/versions`, { page_size: 100 }),
  rollback: (id: string, version: number) => post<T.Agent>(`/agents/${id}/rollback`, { version }),
};
export const Tools = {
  list: (q: Q = {}) => get<T.Page<T.Tool>>('/tools', { page_size: 100, ...q }),
  get: (id: string) => get<T.Tool>(`/tools/${id}`),
  generate: (prompt: string, provider_id?: string) => post<T.ToolGenerateResult>('/tools/generate', { prompt, provider_id }),
  create: (b: Partial<T.Tool>) => post<T.Tool>('/tools', b),
  update: (id: string, b: Partial<T.Tool>) => put<T.Tool>(`/tools/${id}`, b),
  test: (id: string, input: unknown) => post<T.Execution>(`/tools/${id}/test`, { input }),
  publish: (id: string) => post<T.Tool>(`/tools/${id}/publish`),
  versions: (id: string) => get<T.Page<T.ToolVersion>>(`/tools/${id}/versions`, { page_size: 100 }),
};
export const Workflows = {
  list: (q: Q = {}) => get<T.Page<T.Workflow>>('/workflows', { page_size: 100, ...q }),
  get: (id: string) => get<T.Workflow>(`/workflows/${id}`),
  create: (b: { name: string; description?: string; definition: T.WorkflowDefinition }) => post<T.Workflow>('/workflows', b),
  update: (id: string, b: { name?: string; description?: string; definition?: T.WorkflowDefinition }) => put<T.Workflow>(`/workflows/${id}`, b),
  validate: (id: string, definition?: T.WorkflowDefinition) => post<T.ValidationResult>(`/workflows/${id}/validate`, definition ? { definition } : {}),
  publish: (id: string) => post<T.Workflow>(`/workflows/${id}/publish`),
  execute: (id: string, input: unknown) => post<T.Execution>(`/workflows/${id}/execute`, { input }),
};
export const Executions = {
  list: (q: Q = {}) => get<T.Page<T.Execution>>('/executions', { page_size: 50, ...q }),
  get: (id: string) => get<T.Execution>(`/executions/${id}`),
  events: (id: string, after_sequence = 0) => get<{ items: T.ExecutionEvent[] }>(`/executions/${id}/events`, { after_sequence }),
  logs: (id: string) => get<{ items: T.ExecutionLog[] }>(`/executions/${id}/logs`),
  cancel: (id: string) => post<T.Execution>(`/executions/${id}/cancel`),
};
export const Chat = {
  sessions: () => get<T.Page<T.ChatSession>>('/chat/sessions', { page_size: 100 }),
  create: (b: { target_type: 'agent' | 'workflow'; target_id: string; title?: string }) => post<T.ChatSession>('/chat/sessions', b),
  messages: (id: string) => get<T.Page<T.ChatMessage>>(`/chat/sessions/${id}/messages`, { page_size: 100 }),
  send: (id: string, content: string) => post<{ user_message: T.ChatMessage; execution: T.Execution }>(`/chat/sessions/${id}/messages`, { content }),
};
export const Deployments = {
  list: () => get<T.Page<T.Deployment>>('/deployments', { page_size: 100 }),
  create: (b: Pick<T.Deployment, 'resource_type' | 'resource_id' | 'environment'>) => post<T.Deployment>('/deployments', b),
};
export const Monitoring = { summary: () => get<T.MonitoringSummary>('/monitoring/summary') };
