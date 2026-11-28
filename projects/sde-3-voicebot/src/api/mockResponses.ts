import {
  TranscribeResponse,
  ContextResponse,
  ChatResponse,
  AgentPlanResponse,
  ToolExecuteResponse,
  ApprovalResponse,
  SessionInfoResponse,
  HealthResponse,
} from './types';

export const MOCK_HEALTH_RESPONSE: HealthResponse = {
  status: 'ok',
  version: '1.0.0-mock',
  service: 'AI Voice Co-Pilot Core Gateway',
  timestamp: new Date().toISOString(),
};

export const MOCK_TRANSCRIBE_RESPONSE: TranscribeResponse = {
  request_id: 'req-transcribe-001',
  transcript: 'Why is this FastAPI application showing an error?',
  confidence: 0.98,
  is_final: true,
};

export const MOCK_CONTEXT_RESPONSE: ContextResponse = {
  context_id: 'ctx-vscode-001',
  application: 'Visual Studio Code',
  relevant_context: 'Active file: main.py. Traceback: ModuleNotFoundError: No module named fastapi. Terminal running bash.',
  confidence_score: 0.94,
  timestamp: new Date().toISOString(),
};

export const MOCK_CHAT_RESPONSE: ChatResponse = {
  request_id: 'req-chat-001',
  status: 'completed',
  response: 'The error indicates a missing import for FastAPI in your active environment. You can install it using pip.',
  requires_approval: false,
};

export const MOCK_PLAN_RESPONSE: AgentPlanResponse = {
  plan_id: 'plan-001',
  goal: 'Resolve FastAPI missing dependency and update project configuration',
  steps: [
    {
      step_number: 1,
      description: 'Search workspace for dependency file (requirements.txt)',
      tool: 'workspace_file_search',
      parameters: { query: 'requirements.txt' },
      risk_level: 'B',
      requires_approval: false,
    },
    {
      step_number: 2,
      description: 'Read contents of requirements.txt',
      tool: 'read_file',
      parameters: { path: './requirements.txt' },
      risk_level: 'A',
      requires_approval: false,
    },
    {
      step_number: 3,
      description: 'Append fastapi and uvicorn dependencies',
      tool: 'write_file',
      parameters: { path: './requirements.txt', append: true },
      risk_level: 'C',
      requires_approval: true,
    },
  ],
};

export const MOCK_TOOL_EXECUTE_RESPONSE: ToolExecuteResponse = {
  execution_id: 'exec-001',
  tool: 'write_file',
  status: 'success',
  result: {
    path: './requirements.txt',
    bytes_written: 42,
    updated: true,
  },
  message: 'Successfully updated ./requirements.txt with required dependencies.',
};

export const MOCK_APPROVAL_RESPONSE: ApprovalResponse = {
  approval_id: 'appr-901',
  status: 'confirmed',
  decision: 'approved',
  timestamp: new Date().toISOString(),
};

export const getMockSessionResponse = (sessionId: string): SessionInfoResponse => ({
  session_id: sessionId,
  status: 'active',
  created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
  turn_count: 4,
  active_application: 'VS Code',
  duration_seconds: 300,
});
