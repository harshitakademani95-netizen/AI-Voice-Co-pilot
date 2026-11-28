import { TimelineEvent } from '../api/types';

/**
 * Fixture events representing the core end-to-end user journeys defined in the PRD:
 * - UC-02: Explain Technical Error (Student developer in VS Code)
 * - UC-07: Multi-Step Task with Tool Execution & Human Approval (Safety Level C)
 */

export const INITIAL_FIXTURE_EVENTS: TimelineEvent[] = [
  {
    id: 'evt-001',
    timestamp: '10:04:15 AM',
    type: 'system_notification',
    actor: 'assistant',
    title: 'Session Initialized',
    content: 'Co-Pilot session session-001 started in Mock Mode. Context engine monitoring active workspace.',
    metadata: {
      application: 'VS Code',
    },
  },
  {
    id: 'evt-002',
    timestamp: '10:04:22 AM',
    type: 'user_voice',
    actor: 'user',
    title: 'User Voice Input',
    content: 'Why is my FastAPI backend failing with this error?',
    metadata: {
      confidence: 0.98,
      audio_duration_seconds: 3.2,
    },
  },
  {
    id: 'evt-003',
    timestamp: '10:04:23 AM',
    type: 'system_context',
    actor: 'context_engine',
    title: 'Context Captured: VS Code',
    content: 'Terminal error: ModuleNotFoundError: No module named \'fastapi\'. Active file: main.py:12. Window: VS Code - AI Voice Co-Pilot.',
    metadata: {
      application: 'VS Code',
      window_title: 'main.py - AI Voice Co-Pilot - Visual Studio Code',
    },
  },
  {
    id: 'evt-004',
    timestamp: '10:04:24 AM',
    type: 'ai_thought',
    actor: 'assistant',
    title: 'Multimodal AI Reasoning',
    content: 'Correlating user query with captured terminal error. Virtual environment active: false; missing dependency fastapi detected in requirements.txt.',
  },
  {
    id: 'evt-005',
    timestamp: '10:04:25 AM',
    type: 'ai_response',
    actor: 'assistant',
    title: 'Co-Pilot Answer',
    content: 'The error indicates that FastAPI is not installed in your current Python environment. You can resolve this by activating your virtual environment or running `pip install fastapi uvicorn`. Would you like me to inspect your requirements.txt file?',
  },
  {
    id: 'evt-006',
    timestamp: '10:04:26 AM',
    type: 'voice_output',
    actor: 'assistant',
    title: 'Text-to-Speech Output',
    content: 'FastAPI is not installed in your active Python environment. Would you like me to inspect requirements.txt?',
    metadata: {
      audio_duration_seconds: 4.8,
    },
  },
  {
    id: 'evt-007',
    timestamp: '10:05:01 AM',
    type: 'user_voice',
    actor: 'user',
    title: 'User Voice Input',
    content: 'Yes, find requirements.txt, update it, and create a setup script.',
    metadata: {
      confidence: 0.96,
      audio_duration_seconds: 4.1,
    },
  },
  {
    id: 'evt-008',
    timestamp: '10:05:03 AM',
    type: 'agent_plan',
    actor: 'assistant',
    title: 'Agentic Task Plan Generated',
    content: 'Orchestrating multi-step workflow across 3 tools: Search, Inspect, and Controlled File Modification.',
    metadata: {
      plan_steps: [
        {
          step_number: 1,
          description: 'Search workspace for requirements.txt',
          tool: 'workspace_file_search',
          parameters: { query: 'requirements.txt' },
          risk_level: 'B',
          requires_approval: false,
        },
        {
          step_number: 2,
          description: 'Read existing requirements.txt contents',
          tool: 'read_file',
          parameters: { path: './requirements.txt' },
          risk_level: 'A',
          requires_approval: false,
        },
        {
          step_number: 3,
          description: 'Append fastapi and uvicorn to requirements.txt',
          tool: 'write_file',
          parameters: { path: './requirements.txt', append: true, content: 'fastapi>=0.110.0\nuvicorn[standard]>=0.28.0\n' },
          risk_level: 'C',
          requires_approval: true,
        },
      ],
    },
  },
  {
    id: 'evt-009',
    timestamp: '10:05:04 AM',
    type: 'tool_execution',
    actor: 'tool',
    title: 'Tool Executed: workspace_file_search',
    content: 'Found requirements.txt at workspace root (c:\\Users\\vbshy\\OneDrive\\Desktop\\AI voice bot\\requirements.txt)',
    metadata: {
      tool_name: 'workspace_file_search',
      tool_params: { query: 'requirements.txt' },
      tool_result: { matches: 1, path: './requirements.txt' },
      risk_level: 'B',
    },
  },
  {
    id: 'evt-010',
    timestamp: '10:05:05 AM',
    type: 'approval_request',
    actor: 'safety_gate',
    title: 'Human-in-the-Loop Approval Required',
    content: 'Tool `write_file` requires user permission before modifying `./requirements.txt`. Action classified as Risk Category C (Sensitive File Modification).',
    metadata: {
      approval_id: 'appr-901',
      risk_level: 'C',
      approval_status: 'pending',
      tool_name: 'write_file',
      tool_params: {
        target: './requirements.txt',
        change_summary: 'Append dependencies: fastapi>=0.110.0, uvicorn>=0.28.0',
      },
    },
  },
];
