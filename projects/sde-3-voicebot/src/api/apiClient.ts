import {
  TranscribeRequest,
  TranscribeResponse,
  ContextRequest,
  ContextResponse,
  ChatRequest,
  ChatResponse,
  AgentPlanRequest,
  AgentPlanResponse,
  ToolExecuteRequest,
  ToolExecuteResponse,
  ApprovalRequest,
  ApprovalResponse,
  SessionInfoResponse,
  HealthResponse,
  ApiStandardError,
} from './types';
import {
  MOCK_HEALTH_RESPONSE,
  MOCK_TRANSCRIBE_RESPONSE,
  MOCK_CONTEXT_RESPONSE,
  MOCK_PLAN_RESPONSE,
  MOCK_TOOL_EXECUTE_RESPONSE,
  getMockSessionResponse,
} from './mockResponses';

export class ApiClientError extends Error {
  code: ApiStandardError['error']['code'];
  requestId: string;
  statusCode: number;

  constructor(code: ApiStandardError['error']['code'], message: string, requestId: string, statusCode = 400) {
    super(message);
    this.name = 'ApiClientError';
    this.code = code;
    this.requestId = requestId;
    this.statusCode = statusCode;
  }

  toJSON(): ApiStandardError {
    return {
      error: {
        code: this.code,
        message: this.message,
        request_id: this.requestId,
      },
    };
  }
}

export interface ApiClientConfig {
  mockMode: boolean;
  baseUrl?: string;
  simulatedLatencyMs?: number;
  simulatedErrorCode?: ApiStandardError['error']['code'] | null;
}

export interface IApiClient {
  transcribeAudio(req: TranscribeRequest): Promise<TranscribeResponse>;
  submitContext(req: ContextRequest): Promise<ContextResponse>;
  sendChatMessage(req: ChatRequest): Promise<ChatResponse>;
  generateAgentPlan(req: AgentPlanRequest): Promise<AgentPlanResponse>;
  executeTool(req: ToolExecuteRequest): Promise<ToolExecuteResponse>;
  submitApproval(req: ApprovalRequest): Promise<ApprovalResponse>;
  getSession(sessionId: string): Promise<SessionInfoResponse>;
  checkHealth(): Promise<HealthResponse>;
  setMockLatency(ms: number): void;
  setSimulatedError(code: ApiStandardError['error']['code'] | null): void;
}

export class MockApiClient implements IApiClient {
  private config: ApiClientConfig;

  constructor(config: Partial<ApiClientConfig> = {}) {
    this.config = {
      mockMode: config.mockMode ?? true,
      baseUrl: config.baseUrl ?? 'http://localhost:8000',
      simulatedLatencyMs: config.simulatedLatencyMs ?? 80,
      simulatedErrorCode: config.simulatedErrorCode ?? null,
    };
  }

  public setMockLatency(ms: number): void {
    this.config.simulatedLatencyMs = Math.max(0, ms);
  }

  public setSimulatedError(code: ApiStandardError['error']['code'] | null): void {
    this.config.simulatedErrorCode = code;
  }

  public getMockMode(): boolean {
    return this.config.mockMode;
  }

  private async simulateNetwork(): Promise<void> {
    if (this.config.simulatedLatencyMs && this.config.simulatedLatencyMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, this.config.simulatedLatencyMs));
    }

    if (this.config.simulatedErrorCode) {
      const code = this.config.simulatedErrorCode;
      const reqId = `err-${Date.now()}`;
      switch (code) {
        case 'INVALID_REQUEST':
          throw new ApiClientError('INVALID_REQUEST', 'The request is invalid.', reqId, 400);
        case 'PERMISSION_DENIED':
          throw new ApiClientError('PERMISSION_DENIED', 'Missing required permissions for this action.', reqId, 403);
        case 'NOT_FOUND':
          throw new ApiClientError('NOT_FOUND', 'Requested resource was not found.', reqId, 404);
        case 'TOOL_EXECUTION_FAILED':
          throw new ApiClientError('TOOL_EXECUTION_FAILED', 'Tool execution failed or was denied.', reqId, 422);
        default:
          throw new ApiClientError('INTERNAL_ERROR', 'An unexpected mock server error occurred.', reqId, 500);
      }
    }
  }

  public async checkHealth(): Promise<HealthResponse> {
    await this.simulateNetwork();
    return {
      ...MOCK_HEALTH_RESPONSE,
      timestamp: new Date().toISOString(),
    };
  }

  public async transcribeAudio(req: TranscribeRequest): Promise<TranscribeResponse> {
    if (!req.session_id) {
      throw new ApiClientError('INVALID_REQUEST', 'Session ID is required for audio transcription', 'req-err-transcribe', 400);
    }
    await this.simulateNetwork();
    return {
      ...MOCK_TRANSCRIBE_RESPONSE,
      request_id: `req-transcribe-${Date.now()}`,
    };
  }

  public async submitContext(req: ContextRequest): Promise<ContextResponse> {
    if (!req.session_id || !req.application) {
      throw new ApiClientError('INVALID_REQUEST', 'session_id and application are mandatory', 'req-err-ctx', 400);
    }
    await this.simulateNetwork();
    return {
      ...MOCK_CONTEXT_RESPONSE,
      application: req.application,
      context_id: `ctx-${Date.now()}`,
      relevant_context: req.visible_code
        ? `Application: ${req.application}. Window: ${req.window_title ?? 'Active'}. Code context: ${req.visible_code}`
        : MOCK_CONTEXT_RESPONSE.relevant_context,
      timestamp: new Date().toISOString(),
    };
  }

  public async sendChatMessage(req: ChatRequest): Promise<ChatResponse> {
    if (!req.session_id || !req.message) {
      throw new ApiClientError('INVALID_REQUEST', 'session_id and message are mandatory', 'req-err-chat', 400);
    }
    await this.simulateNetwork();

    const isSensitive = req.message.toLowerCase().includes('delete') || req.message.toLowerCase().includes('update');

    return {
      request_id: `req-chat-${Date.now()}`,
      status: 'completed',
      response: `[Mock AI Response to: "${req.message}"] I analyzed the context. The issue can be resolved with standard dependency configuration.`,
      requires_approval: isSensitive,
      approval_id: isSensitive ? `appr-${Date.now()}` : undefined,
    };
  }

  public async generateAgentPlan(req: AgentPlanRequest): Promise<AgentPlanResponse> {
    if (!req.session_id || !req.user_request) {
      throw new ApiClientError('INVALID_REQUEST', 'session_id and user_request are required', 'req-err-plan', 400);
    }
    await this.simulateNetwork();
    return {
      ...MOCK_PLAN_RESPONSE,
      plan_id: `plan-${Date.now()}`,
      goal: req.user_request,
    };
  }

  public async executeTool(req: ToolExecuteRequest): Promise<ToolExecuteResponse> {
    if (!req.session_id || !req.tool) {
      throw new ApiClientError('INVALID_REQUEST', 'session_id and tool are required', 'req-err-tool', 400);
    }
    await this.simulateNetwork();
    return {
      ...MOCK_TOOL_EXECUTE_RESPONSE,
      execution_id: `exec-${Date.now()}`,
      tool: req.tool,
      message: `Tool ${req.tool} executed successfully with mock parameters.`,
    };
  }

  public async submitApproval(req: ApprovalRequest): Promise<ApprovalResponse> {
    if (!req.session_id || !req.approval_id || !req.decision) {
      throw new ApiClientError('INVALID_REQUEST', 'session_id, approval_id and decision are required', 'req-err-approval', 400);
    }
    await this.simulateNetwork();
    return {
      approval_id: req.approval_id,
      status: 'confirmed',
      decision: req.decision,
      timestamp: new Date().toISOString(),
    };
  }

  public async getSession(sessionId: string): Promise<SessionInfoResponse> {
    if (!sessionId) {
      throw new ApiClientError('INVALID_REQUEST', 'session_id cannot be empty', 'req-err-session', 400);
    }
    await this.simulateNetwork();
    return getMockSessionResponse(sessionId);
  }
}

// Export singleton instance initialized in Mock Mode as required
export const apiClient = new MockApiClient({ mockMode: true });
