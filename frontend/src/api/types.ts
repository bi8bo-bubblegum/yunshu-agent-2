// frontend/src/api/types.ts —— 后端 API 类型定义

export interface User {
  id: string
  username: string
  display_name: string
  role_code: string
  department_id: string | null
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  current_trace_id?: string | null
}

// 结构化工具卡片元数据（role='tool' 消息）：tool/args/result/status 供前端渲染卡片
export interface MessageMetadata {
  agent?: string
  segment?: 'final' | 'step'
  kind?: 'tool'
  tool?: string
  args?: unknown
  result?: unknown
  status?: 'success' | 'error' | 'running'
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  created_at?: string
  // 分段落库元数据：{agent, segment} 助手消息；{kind:'tool', tool, args, result, status} 工具卡片
  metadata?: MessageMetadata | null
}

export interface DocumentItem {
  id: string
  title: string
  status: 'parsing' | 'ready' | 'failed'
  created_at?: string | null
}

export interface SearchHit {
  id: string
  content: string
  document_id: string
  score: number
}

export interface ExperienceItem {
  id: string
  title: string
  scope: string
  status: string
  summary: string
}

export interface ExperienceDetail {
  id: string
  title: string
  summary: string
  content: string
  tags: string[]
  scope: string
  status: string
  event_time: string | null
  result_metrics: Record<string, unknown> | null
  owner_id: string
  created_at: string | null
}

export interface ApprovalItem {
  id: string
  category: string
  risk: string | null
  mode: string
  title: string
  context: Record<string, unknown> | null
  requester_id: string
  requester_name: string
  status: string
  comment: string | null
  approver_id: string | null
  approver_name: string | null
  submitted_at: string | null
  decided_at: string | null
}

export interface Department {
  id: string
  name: string
}

export interface McpServer {
  name: string
  url: string
  auth_type: string
  default_risk: string
  config: Record<string, unknown>
  enabled: boolean
}

export interface McpToolInfo {
  name: string
  description: string
  risk: string
}

export interface AgentBinding {
  id: string
  agent_code: string
  mcp_server_name: string
  enabled: boolean
}

export interface AgentInfo {
  code: string
  name: string
}

export interface TraceItem {
  id: string
  status: string
  conversation_id: string | null
  supervisor_routes: string[] | null
}

export interface TraceEventItem {
  type: string
  payload: Record<string, unknown>
  created_at: string
}
