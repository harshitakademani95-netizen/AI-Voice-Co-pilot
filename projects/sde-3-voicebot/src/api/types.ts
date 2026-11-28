/**
 * AI Voice Co-Pilot - API Interface Types
 * Compliant with 04. API Specifications & Interface Contracts
 */

export type RiskLevel = 'A' | 'B' | 'C' | 'D';

export interface ApiStandardError {
  error: {
    code: 'INVALID_REQUEST' | 'PERMISSION_DENIED' | 'NOT_FOUND' | 'INTERNAL_ERROR' | 'TOOL_EXECUTION_FAILED' | 'MICROPHONE_DENIED';
    message: string;
    request_id: string;
  };
}

// 1. POST /api/v1/voice/transcribe
export interface TranscribeRequest {
  session_id: string;
  audio_data?: string; // base64 or mock blob
  format?: 'pcm' | 'wav' | 'webm';
}

export interface TranscribeResponse {
  request_id: string;
  transcript: string;
  confidence: number;
  is_final: boolean;
}

// 2. POST /api/v1/context
export interface ContextRequest {
  session_id: string;
  application: string;
  window_title?: string;
  visible_code?: string;
  user_query?: string;
  screen_summary?: string;
}

export interface ContextResponse {
  context_id: string;
  application: string;
  relevant_context: string;
  confidence_score: number;
  timestamp: string;
}

// 3. POST /api/v1/ai/chat
export interface ChatRequest {
  session_id: string;
  message: string;
  context_id?: string;
}

export interface ChatResponse {
  request_id: string;
  status: 'completed' | 'processing' | 'failed';
  response: string;
  requires_approval: boolean;
  approval_id?: string;
}

// 4. POST /api/v1/agent/plan
export interface AgentPlanStep {
  step_number: number;
  description: string;
  tool: string;
  parameters: Record<string, unknown>;
  risk_level: RiskLevel;
  requires_approval: boolean;
}

export interface AgentPlanRequest {
  session_id: string;
  user_request: string;
  context_id?: string;
}

export interface AgentPlanResponse {
  plan_id: string;
  goal: string;
  steps: AgentPlanStep[];
}

// 5. POST /api/v1/tools/execute
export interface ToolExecuteRequest {
  session_id: string;
  tool: string;
  parameters: Record<string, unknown>;
  approval_id?: string;
}

export interface ToolExecuteResponse {
  execution_id: string;
  tool: string;
  status: 'success' | 'failed';
  result: Record<string, unknown>;
  message: string;
}

// 6. POST /api/v1/approvals
export interface ApprovalRequest {
  session_id: string;
  approval_id: string;
  decision: 'approved' | 'rejected';
  user_notes?: string;
}

export interface ApprovalResponse {
  approval_id: string;
  status: 'confirmed';
  decision: 'approved' | 'rejected';
  timestamp: string;
}

// 7. GET /api/v1/sessions/{session_id}
export type SessionStatus = 'idle' | 'active' | 'paused' | 'ended';

export interface SessionInfoResponse {
  session_id: string;
  status: SessionStatus;
  created_at: string;
  turn_count: number;
  active_application?: string;
  duration_seconds: number;
}

// 8. GET /api/v1/health
export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  service: string;
  timestamp: string;
}

// Frontend UX Types for Timeline and UI State
export type MicrophonePermissionState = 'prompt' | 'granted' | 'denied';
export type MicrophoneActivityState = 'idle' | 'listening' | 'processing' | 'speaking' | 'muted';

export type TimelineEventType =
  | 'user_voice'
  | 'system_context'
  | 'ai_thought'
  | 'ai_response'
  | 'agent_plan'
  | 'approval_request'
  | 'tool_execution'
  | 'voice_output'
  | 'system_notification';

export interface TimelineEvent {
  id: string;
  timestamp: string;
  type: TimelineEventType;
  actor: 'user' | 'assistant' | 'context_engine' | 'safety_gate' | 'tool';
  title: string;
  content: string;
  metadata?: {
    confidence?: number;
    risk_level?: RiskLevel;
    approval_id?: string;
    approval_status?: 'pending' | 'approved' | 'rejected';
    application?: string;
    window_title?: string;
    tool_name?: string;
    tool_params?: Record<string, unknown>;
    tool_result?: Record<string, unknown>;
    plan_steps?: AgentPlanStep[];
    duration_ms?: number;
    audio_duration_seconds?: number;
  };
}
