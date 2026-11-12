import { describe, it, expect, beforeEach } from 'vitest';
import { MockApiClient, ApiClientError } from '../api/apiClient';

describe('MockApiClient & Contract Testing', () => {
  let client: MockApiClient;

  beforeEach(() => {
    client = new MockApiClient({ mockMode: true, simulatedLatencyMs: 0 });
  });

  it('checks service health endpoint GET /api/v1/health', async () => {
    const res = await client.checkHealth();
    expect(res.status).toBe('ok');
    expect(res.service).toContain('Gateway');
    expect(res.version).toBe('1.0.0-mock');
  });

  it('transcribes voice audio POST /api/v1/voice/transcribe', async () => {
    const res = await client.transcribeAudio({
      session_id: 'session-001',
      format: 'pcm',
    });
    expect(res.transcript).toBeDefined();
    expect(res.confidence).toBeGreaterThan(0.9);
    expect(res.is_final).toBe(true);
  });

  it('submits workspace application context POST /api/v1/context', async () => {
    const res = await client.submitContext({
      session_id: 'session-001',
      application: 'VS Code',
      visible_code: 'import fastapi',
    });
    expect(res.context_id).toBeDefined();
    expect(res.application).toBe('VS Code');
    expect(res.relevant_context).toContain('VS Code');
  });

  it('sends chat request to AI reasoning engine POST /api/v1/ai/chat', async () => {
    const res = await client.sendChatMessage({
      session_id: 'session-001',
      message: 'Explain this error',
    });
    expect(res.status).toBe('completed');
    expect(res.response).toBeDefined();
    expect(res.requires_approval).toBe(false);
  });

  it('flags sensitive actions for human approval in POST /api/v1/ai/chat', async () => {
    const res = await client.sendChatMessage({
      session_id: 'session-001',
      message: 'Please update requirements.txt and delete old log files',
    });
    expect(res.requires_approval).toBe(true);
    expect(res.approval_id).toBeDefined();
  });

  it('generates agentic action plan POST /api/v1/agent/plan', async () => {
    const res = await client.generateAgentPlan({
      session_id: 'session-001',
      user_request: 'Find requirements.txt and add fastapi',
    });
    expect(res.plan_id).toBeDefined();
    expect(res.steps.length).toBeGreaterThan(0);
    expect(res.steps[2].risk_level).toBe('C');
    expect(res.steps[2].requires_approval).toBe(true);
  });

  it('executes controlled tool POST /api/v1/tools/execute', async () => {
    const res = await client.executeTool({
      session_id: 'session-001',
      tool: 'write_file',
      parameters: { path: './requirements.txt' },
    });
    expect(res.status).toBe('success');
    expect(res.tool).toBe('write_file');
  });

  it('submits user approval decision POST /api/v1/approvals', async () => {
    const res = await client.submitApproval({
      session_id: 'session-001',
      approval_id: 'appr-901',
      decision: 'approved',
    });
    expect(res.status).toBe('confirmed');
    expect(res.decision).toBe('approved');
  });

  it('retrieves session details GET /api/v1/sessions/{session_id}', async () => {
    const res = await client.getSession('session-001');
    expect(res.session_id).toBe('session-001');
    expect(res.status).toBe('active');
  });

  it('enforces standardized error format on invalid request', async () => {
    try {
      await client.transcribeAudio({ session_id: '' });
      expect.fail('Should have thrown ApiClientError');
    } catch (err: any) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect(err.code).toBe('INVALID_REQUEST');
      expect(err.toJSON()).toEqual({
        error: {
          code: 'INVALID_REQUEST',
          message: expect.any(String),
          request_id: expect.any(String),
        },
      });
    }
  });

  it('handles simulated server and permission errors', async () => {
    client.setSimulatedError('PERMISSION_DENIED');
    try {
      await client.checkHealth();
      expect.fail('Should have thrown PERMISSION_DENIED');
    } catch (err: any) {
      expect(err.code).toBe('PERMISSION_DENIED');
      expect(err.statusCode).toBe(403);
    }
  });
});
