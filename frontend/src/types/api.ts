export type Role = 'owner' | 'admin' | 'developer' | 'operator' | 'viewer';
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface ApiErrorBody { error: { code: string; message: string; details?: Record<string, unknown>; request_id?: string } }

export interface TokenPair { access_token: string; refresh_token: string; token_type: 'bearer'; expires_in: number }
export interface User { id: string; email: string; full_name: string; status: 'active' | 'disabled'; created_at: string }
export interface Membership { organization_id: string; organization_name: string; organization_slug: string; role: Role }
export interface Me extends User { memberships: Membership[] }

export interface Organization { id: string; name: string; slug: string; status: 'active'; created_at: string }
export type OrganizationWithRole = Organization & { role: Role };
export interface Member { user_id: string; email: string; full_name: string; role: Role; joined_at: string }

export type ProviderKind = 'gemini' | 'azure_openai';
export type ConnectProvider =
  | { provider: 'gemini'; name?: string; api_key: string; default_model?: string }
  | { provider: 'azure_openai'; name?: string; api_key: string; endpoint: string; deployment_name: string; api_version: string; default_model?: string };
export interface LLMProvider {
  id: string; provider: ProviderKind; name: string;
  status: 'pending_validation' | 'valid' | 'invalid' | 'active' | 'inactive';
  is_default: boolean; default_model: string | null; key_hint: string;
  config: { endpoint?: string; deployment_name?: string; api_version?: string };
  last_validated_at: string | null; created_at: string;
}

export type CredentialKind = 'api_key' | 'bearer_token' | 'basic_auth' | 'generic';
export interface Credential { id: string; name: string; kind: CredentialKind; description: string; key_hint: string; created_at: string; rotated_at: string | null }

export interface AgentConfig {
  instructions: string; provider_id: string | null; model: string | null; temperature: number;
  tool_ids: string[]; memory: 'none' | 'conversation'; max_retries: number; timeout_seconds: number;
  guardrails: { block_pii: boolean; max_output_chars: number | null };
  input_schema: object | null; output_schema: object | null;
}
export type AgentStatus = 'draft' | 'configured' | 'testing' | 'approved' | 'published' | 'archived';
export interface Agent { id: string; name: string; description: string; status: AgentStatus; current_version: number; config: AgentConfig; created_by: string; created_at: string; updated_at: string }
export interface AgentVersion { id: string; agent_id: string; version: number; config: AgentConfig; created_at: string; created_by: string }
export interface AgentDraft { name: string; description: string; config: AgentConfig }

export interface Tool {
  id: string; name: string; description: string; status: 'draft' | 'tested' | 'published' | 'archived';
  current_version: number; source_code: string; input_schema: object; output_schema: object; requirements: string[];
  created_at: string; updated_at: string;
}
export interface ToolDraft { name: string; description: string; source_code: string; input_schema: object; output_schema: object; requirements: string[]; tests?: unknown }
export interface ToolGenerateResult { draft: ToolDraft; static_analysis: { ok: boolean; issues: string[] } }
export interface ToolVersion { id: string; version: number; source_code: string; created_at: string }

export type NodeType = 'start' | 'end' | 'agent' | 'tool' | 'llm' | 'rag' | 'api' | 'condition';
export interface WorkflowNode { id: string; type: NodeType; position: { x: number; y: number }; data: { label: string; config: Record<string, unknown> } }
export interface WorkflowEdge { id: string; source: string; target: string; source_handle?: 'true' | 'false' }
export interface WorkflowDefinition { schema_version: '1.0'; nodes: WorkflowNode[]; edges: WorkflowEdge[]; viewport: { x: number; y: number; zoom: number } }
export interface Workflow { id: string; name: string; description: string; status: 'draft' | 'valid' | 'published' | 'archived'; current_version: number; definition: WorkflowDefinition; created_at: string; updated_at: string }
export interface ValidationIssue { node_id: string | null; edge_id: string | null; code: string; message: string }
export interface ValidationResult { valid: boolean; issues: ValidationIssue[] }

export type ExecKind = 'agent' | 'agent_test' | 'workflow' | 'tool_test' | 'chat';
export type ExecStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export interface Execution {
  id: string; kind: ExecKind; status: ExecStatus; resource_id: string; resource_version: number; input: unknown;
  output: unknown | null; error: string | null; correlation_id: string; created_by: string; created_at: string;
  started_at: string | null; finished_at: string | null; duration_ms: number | null;
}
export type EventType = 'execution.queued' | 'execution.started' | 'node.started' | 'node.completed' | 'node.failed' | 'llm.token' | 'log' | 'execution.completed' | 'execution.failed' | 'execution.cancelled';
export interface ExecutionEvent { id: string; execution_id: string; sequence: number; event_type: EventType; node_id: string | null; payload: Record<string, unknown>; created_at: string }
export interface ExecutionLog { timestamp: string; level: string; message: string; node_id: string | null }

export interface ChatSession { id: string; title: string; target_type: 'agent' | 'workflow'; target_id: string; created_at: string; updated_at: string }
export interface ChatMessage { id: string; session_id: string; role: 'user' | 'assistant' | 'system'; content: string; execution_id: string | null; created_at: string }

export interface Deployment { id: string; resource_type: 'agent' | 'workflow'; resource_id: string; environment: 'dev' | 'staging' | 'production'; status?: string; created_at: string }

export interface MonitoringSummary {
  executions_24h: number; succeeded_24h: number; failed_24h: number; avg_duration_ms: number | null;
  by_status: Record<string, number>; by_kind: Record<string, number>; agents: number; tools: number; workflows: number;
  active_provider: LLMProvider | null;
}
export const TERMINAL_EVENTS: EventType[] = ['execution.completed', 'execution.failed', 'execution.cancelled'];
