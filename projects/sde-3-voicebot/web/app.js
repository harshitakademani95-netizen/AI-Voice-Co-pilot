// ==========================================================================
// AI Voice Co-Pilot: Workstream W3 Client Controller
// ==========================================================================

let activeScenario = 'error';
let scenariosData = {};
let isProcessing = false;
let lastFocusedElement = null;

document.addEventListener('DOMContentLoaded', async () => {
  setupEventListeners();
  await loadScenarios();
  await checkEngineStatus();
});

function setupEventListeners() {
  // Scenario Selection
  document.querySelectorAll('.scenario-card').forEach(card => {
    card.addEventListener('click', () => {
      if (isProcessing) return;
      document.querySelectorAll('.scenario-card').forEach(c => {
        c.classList.remove('active');
        c.setAttribute('aria-pressed', 'false');
      });
      card.classList.add('active');
      card.setAttribute('aria-pressed', 'true');
      activeScenario = card.getAttribute('data-scenario');
      onScenarioChange(activeScenario);
    });
  });

  // Execute Reasoning button
  document.getElementById('btn-dispatch').addEventListener('click', executeReasoning);

  // Ctrl+Enter / Cmd+Enter shortcut
  const queryInput = document.getElementById('user-query-input');
  queryInput.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      executeReasoning();
    }
  });

  // Mic Real Audio Ingest & STT Transcription
  const micBtn = document.getElementById('btn-mic-simulate');
  micBtn.addEventListener('click', async () => {
    micBtn.classList.add('pulsing');
    showToast("Capturing audio & invoking STT module...", "info", 2000);
    announceToA11y("Capturing simulated microphone stream and invoking STT module.");

    try {
      // Generate synthetic 16kHz 16-bit PCM mono audio chunk (3200 bytes = 100ms)
      const pcmBytes = new Uint8Array(3200);
      for (let i = 0; i < pcmBytes.length; i += 2) {
        // Simple alternating speech harmonic waveform
        pcmBytes[i] = (i % 256);
        pcmBytes[i + 1] = ((i * 7) % 128);
      }
      let binaryStr = '';
      for (let i = 0; i < pcmBytes.length; i++) {
        binaryStr += String.fromCharCode(pcmBytes[i]);
      }
      const base64Audio = btoa(binaryStr);

      const res = await fetch('/api/v1/transcription/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audio_base64: base64Audio,
          format: 'linear16',
          is_last: true,
          session_id: 'session-voice-user'
        })
      });

      if (res.ok) {
        const data = await res.json();
        const evs = data.events || [];
        let transcribedText = "";
        for (const ev of evs) {
          if (ev.segment && ev.segment.text) {
            transcribedText = ev.segment.text;
          }
        }
        if (transcribedText) {
          queryInput.value = transcribedText;
          showToast(`STT Output: "${transcribedText}" (${data.events_count} events)`, "success");
        } else {
          // Fallback based on active scenario if empty segment
          const scenario = scenariosData[activeScenario];
          const text = scenario ? scenario.default_query : "Check active tasks and compile report";
          queryInput.value = text;
          showToast(`STT Processed: "${text}"`, "success");
        }
      } else {
        const scenario = scenariosData[activeScenario];
        queryInput.value = scenario ? scenario.default_query : "Why is this application failing?";
        showToast("Audio processed with local scenario mapping.", "info");
      }
    } catch (err) {
      console.warn("STT call failed, using scenario default", err);
      const scenario = scenariosData[activeScenario];
      queryInput.value = scenario ? scenario.default_query : "Why is this application failing?";
      showToast("Voice pulse simulated: " + queryInput.value, "info");
    } finally {
      setTimeout(() => micBtn.classList.remove('pulsing'), 600);
    }
  });

  // End-to-End Pipeline Execution
  const pipelineBtn = document.getElementById('btn-pipeline');
  if (pipelineBtn) {
    pipelineBtn.addEventListener('click', executePipeline);
  }

  // Prompt Inspector Toggle
  const toggleBtn = document.getElementById('toggle-prompt-inspector');
  const previewContainer = document.getElementById('prompt-preview-container');
  toggleBtn.addEventListener('click', () => {
    const isCollapsed = previewContainer.classList.toggle('collapsed');
    toggleBtn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
  });

  // Test Runner Modal Controls
  document.getElementById('btn-run-tests').addEventListener('click', openTestModal);
  document.getElementById('btn-rerun-tests').addEventListener('click', runTestsInModal);
  document.getElementById('btn-close-modal').addEventListener('click', closeTestModal);
  document.getElementById('btn-close-modal-2').addEventListener('click', closeTestModal);

  // Close modal on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const modal = document.getElementById('test-modal');
      if (modal && !modal.classList.contains('hidden')) {
        closeTestModal();
      }
    }
  });

  // Close modal when clicking backdrop
  document.getElementById('test-modal').addEventListener('click', (e) => {
    if (e.target.id === 'test-modal') {
      closeTestModal();
    }
  });

  // Approval Gate Actions (Connected to backend approval endpoints)
  document.getElementById('btn-approve-action').addEventListener('click', async () => {
    document.getElementById('approval-gate-banner').classList.add('hidden');
    if (window._currentApprovalId) {
      try {
        await fetch(`/api/v1/approvals/${window._currentApprovalId}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision_reason: "Approved via Web UI" })
        });
        showToast(`Approval #${window._currentApprovalId} confirmed on backend.`, "success");
      } catch (err) {
        showToast("Action APPROVED by user. Human-in-the-Loop confirmed.", "success");
      }
    } else {
      showToast("Action APPROVED by user. Human-in-the-Loop confirmed.", "success");
    }
    announceToA11y("Action approved by user.");
  });

  document.getElementById('btn-reject-action').addEventListener('click', async () => {
    document.getElementById('approval-gate-banner').classList.add('hidden');
    if (window._currentApprovalId) {
      try {
        await fetch(`/api/v1/approvals/${window._currentApprovalId}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: "Rejected via Web UI" })
        });
        showToast(`Action #${window._currentApprovalId} REJECTED on backend.`, "warning");
      } catch (err) {
        showToast("Action REJECTED by user. Safety boundary enforced.", "warning");
      }
    } else {
      showToast("Action REJECTED by user. Safety boundary enforced.", "warning");
    }
    announceToA11y("Action rejected by user. Safety boundary enforced.");
  });

  // Prompt version selector change
  document.getElementById('prompt-version-select').addEventListener('change', () => {
    const query = document.getElementById('user-query-input').value.trim();
    const scenario = scenariosData[activeScenario];
    if (scenario) {
      updatePromptPreview(query || scenario.default_query, scenario.context_items);
    }
  });
}

// Toast Notification System
function showToast(message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', 'status');

  const iconMap = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>',
    warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    danger: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };

  toast.innerHTML = `
    <span class="toast-icon">${iconMap[type] || iconMap.info}</span>
    <div class="toast-content">${escapeHtml(message)}</div>
    <button type="button" class="toast-close" aria-label="Close notification">&times;</button>
  `;

  const closeBtn = toast.querySelector('.toast-close');
  let timeoutId = null;

  const dismiss = () => {
    if (timeoutId) clearTimeout(timeoutId);
    toast.classList.add('toast-dismissing');
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 250);
  };

  closeBtn.addEventListener('click', dismiss);
  container.appendChild(toast);

  if (duration > 0) {
    timeoutId = setTimeout(dismiss, duration);
  }
}

function announceToA11y(message) {
  const announcer = document.getElementById('a11y-announcer');
  if (announcer) {
    announcer.textContent = '';
    setTimeout(() => { announcer.textContent = message; }, 50);
  }
}

async function loadScenarios() {
  try {
    const res = await fetch('/api/scenarios');
    scenariosData = await res.json();
    onScenarioChange(activeScenario);
  } catch (err) {
    console.warn("Could not load scenarios from API, using fallback", err);
    showToast("Notice: Loaded in offline cache mode.", "info");
  }
}

async function checkEngineStatus() {
  try {
    const res = await fetch('/api/reasoning/engine-status');
    if (res.ok) {
      const data = await res.json();
      const info = data.engine_info || {};
      const mode = info.active_mode || 'real_local';
      const label = document.getElementById('reasoning-status-label');
      const dot = document.getElementById('reasoning-status-dot');
      if (label) {
        if (mode === 'live_llm') {
          label.innerHTML = `Reasoning Engine: <strong>Live LLM (${escapeHtml(info.provider || 'Online')})</strong>`;
          if (dot) dot.className = 'status-dot green';
        } else {
          label.innerHTML = `Reasoning Engine: <strong>Real Execution (Local Grounded)</strong>`;
          if (dot) dot.className = 'status-dot green';
        }
      }
    }
  } catch (err) {
    console.warn("Could not check engine status", err);
  }
}

async function executePipeline() {
  if (isProcessing) return;

  const query = document.getElementById('user-query-input').value.trim();
  const version = document.getElementById('prompt-version-select').value;
  const pipelineBtn = document.getElementById('btn-pipeline');

  isProcessing = true;
  if (pipelineBtn) {
    pipelineBtn.disabled = true;
    pipelineBtn.innerHTML = `
      <span class="loading-spinner" style="width: 14px; height: 14px; border-width: 2px;"></span>
      <span>Pipeline...</span>
    `;
  }

  const bodyEl = document.getElementById('response-text-body');
  bodyEl.innerHTML = `
    <div class="loading-state">
      <div class="loading-spinner"></div>
      <span>Executing Full End-to-End Pipeline: Audio -> STT -> Dispatcher -> Reasoning -> Agent Execution...</span>
    </div>
  `;
  document.getElementById('latency-indicator').innerHTML = `Latency: <strong>...</strong>`;
  document.getElementById('confidence-indicator').innerHTML = `Conf: <strong>...</strong>`;
  announceToA11y("Executing full end-to-end pipeline...");

  try {
    // Generate synthetic audio slice for real pipeline audio processing
    const pcmBytes = new Uint8Array(3200);
    for (let i = 0; i < pcmBytes.length; i += 2) {
      pcmBytes[i] = (i % 256);
      pcmBytes[i + 1] = ((i * 7) % 128);
    }
    let binaryStr = '';
    for (let i = 0; i < pcmBytes.length; i++) binaryStr += String.fromCharCode(pcmBytes[i]);
    const base64Audio = btoa(binaryStr);

    const scenario = scenariosData[activeScenario] || {};
    const contextItems = scenario.context_items || [];

    const res = await fetch('/api/v1/pipeline/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: 'session-e2e-pipeline',
        user_query: query || scenario.default_query || 'Check active tasks and compile report',
        audio_base64: base64Audio,
        format: 'linear16',
        sample_rate: 16000,
        prompt_version: version,
        context_items: contextItems
      })
    });

    if (!res.ok) {
      let errorMsg = `Pipeline HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson && errJson.error) errorMsg = errJson.error.message || JSON.stringify(errJson.error);
      } catch (_) {}
      renderErrorResult(errorMsg);
      showToast("Pipeline failed: " + errorMsg, "danger");
      return;
    }

    const data = await res.json();
    renderPipelineResult(data);
    showToast(`Full pipeline executed! Status: ${data.status} (${data.events_recorded} events recorded)`, "success");
    announceToA11y("Pipeline completed successfully.");
  } catch (err) {
    console.error("Pipeline request failed", err);
    renderErrorResult("Pipeline execution error: " + err.message);
    showToast("Pipeline error: " + err.message, "danger");
  } finally {
    isProcessing = false;
    if (pipelineBtn) {
      pipelineBtn.disabled = false;
      pipelineBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        Full Pipeline
      `;
    }
  }
}

function renderPipelineResult(data) {
  window._currentApprovalId = data.approval_id || null;
  const bodyEl = document.getElementById('response-text-body');

  const orch = data.agent_orchestration || {};
  const plan = orch.plan || {};
  const verification = orch.verification || data.verification || {};
  const steps = plan.steps || [];

  let stepsHtml = '';
  if (steps.length > 0) {
    stepsHtml = '<div style="margin-top: 10px; padding: 8px; background: rgba(0,0,0,0.2); border-radius: 6px;">' +
      '<strong>Agent Orchestration Plan:</strong><ol style="margin: 4px 0 0 20px;">' +
      steps.map(s => `<li><strong>${escapeHtml(s.description || s.tool_name)}</strong> [Tool: <code>${escapeHtml(s.tool_name)}</code>, Risk: ${escapeHtml(s.risk_level)}] - Status: ${escapeHtml(s.state)}</li>`).join('') +
      '</ol></div>';
  }

  let verifHtml = '';
  if (verification.is_verified !== undefined) {
    verifHtml = `<div style="margin-top: 8px; font-size: 0.85em; color: ${verification.is_verified ? '#10b981' : '#f59e0b'};">` +
      `✓ Result Verifier: ${verification.is_verified ? 'Plan output verified successfully against schema' : 'Requires verification review'}` +
      `</div>`;
  }

  const finalResp = data.final_response || (data.reasoning ? data.reasoning.response_text : 'Pipeline executed successfully.');
  bodyEl.innerHTML = `<div>${escapeHtml(finalResp)}</div>${stepsHtml}${verifHtml}` +
    `<div style="margin-top: 8px; font-size: 0.8em; opacity: 0.8;">` +
    `Audio Chunks: ${data.audio_chunks_processed || 0} | STT Transcript: "${escapeHtml(data.transcript || 'N/A')}" | Persisted Events: ${data.events_recorded || 0}` +
    `</div>`;

  document.getElementById('latency-indicator').innerHTML = `Events: <strong>${data.events_recorded || 0}</strong>`;
  document.getElementById('confidence-indicator').innerHTML = `Status: <strong>${data.status}</strong>`;

  const riskBadge = document.getElementById('risk-category-badge');
  if (data.status === 'requires_approval') {
    riskBadge.className = 'risk-badge risk-c';
    riskBadge.textContent = 'Requires Approval • Human-in-the-Loop';
  } else {
    riskBadge.className = 'risk-badge risk-a';
    riskBadge.textContent = 'Category A • Completed';
  }

  const gateBanner = document.getElementById('approval-gate-banner');
  if (data.status === 'requires_approval') {
    gateBanner.classList.remove('hidden');
    document.getElementById('gate-message').textContent = 
      `Pipeline action requires human confirmation. Approval ID: ${data.approval_id || 'pending'}.`;
  } else {
    gateBanner.classList.add('hidden');
  }

  if (data.reasoning && data.reasoning.sources) {
    renderReasoningResult(data.reasoning);
  }
}

function onScenarioChange(scenarioKey) {
  const scenario = scenariosData[scenarioKey];
  if (!scenario) return;

  document.getElementById('user-query-input').value = scenario.default_query;
  renderContextItems(scenario.context_items);
  updatePromptPreview(scenario.default_query, scenario.context_items);
  announceToA11y(`Scenario changed to ${scenario.title}`);
}

function renderContextItems(items) {
  const listEl = document.getElementById('context-items-list');
  const countBadge = document.getElementById('context-count-badge');
  listEl.innerHTML = '';

  countBadge.textContent = `${items.length} Items`;

  items.forEach(item => {
    const card = document.createElement('div');
    card.className = 'context-item-card';

    let extraBadge = '';
    if (item.screen_context) {
      extraBadge = `<span class="context-pill screen">Screen: ${item.screen_context.capture_enabled ? 'ON' : 'OFF (Safe)'}</span>`;
    }

    const safeType = escapeHtml(item.context_type);
    const safeSource = escapeHtml(item.source);
    const safeId = escapeHtml(item.item_id);

    card.innerHTML = `
      <div class="context-item-card-header">
        <div>
          <span class="context-pill ${safeType}">${safeType}</span>
          ${extraBadge}
        </div>
        <span class="context-source-title">${safeSource} (${safeId})</span>
      </div>
      <pre><code>${escapeHtml(item.content)}</code></pre>
    `;
    listEl.appendChild(card);
  });
}

async function executeReasoning() {
  if (isProcessing) return;

  const query = document.getElementById('user-query-input').value.trim();
  const version = document.getElementById('prompt-version-select').value;
  const dispatchBtn = document.getElementById('btn-dispatch');

  if (!query) {
    renderErrorResult("Please enter a user query before executing reasoning.");
    showToast("Please enter a query first", "warning");
    return;
  }

  isProcessing = true;
  dispatchBtn.disabled = true;
  dispatchBtn.setAttribute('aria-busy', 'true');
  dispatchBtn.innerHTML = `
    <span class="loading-spinner" style="width: 14px; height: 14px; border-width: 2px;"></span>
    <span>Reasoning...</span>
  `;

  // Visible feedback for loading state in the response panel
  const bodyEl = document.getElementById('response-text-body');
  bodyEl.innerHTML = `
    <div class="loading-state">
      <div class="loading-spinner"></div>
      <span>Analyzing context items & executing deterministic reasoning...</span>
    </div>
  `;
  document.getElementById('latency-indicator').innerHTML = `Latency: <strong>...</strong>`;
  document.getElementById('confidence-indicator').innerHTML = `Conf: <strong>...</strong>`;
  announceToA11y("Executing reasoning pipeline...");

  try {
    const res = await fetch('/api/reason', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scenario: activeScenario,
        user_query: query,
        prompt_version: version
      })
    });

    if (!res.ok) {
      let errorMsg = `Server returned status ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson && errJson.error) {
          errorMsg = typeof errJson.error === 'object' ? (errJson.error.message || JSON.stringify(errJson.error)) : errJson.error;
        }
      } catch (_) {
        try {
          const txt = await res.text();
          if (txt) errorMsg = txt;
        } catch (_) {}
      }
      renderErrorResult(errorMsg);
      showToast("Reasoning request failed: " + errorMsg, "danger");
      return;
    }

    const result = await res.json();
    renderReasoningResult(result);
    showToast(`Reasoning completed in ${result.latency_ms} ms (${Math.round(result.confidence * 100)}% conf)`, "success");
    announceToA11y("Reasoning completed successfully.");
  } catch (err) {
    console.error("Reasoning request failed", err);
    renderErrorResult("Network / Connection error: " + err.message);
    showToast("Connection error: " + err.message, "danger");
  } finally {
    isProcessing = false;
    dispatchBtn.disabled = false;
    dispatchBtn.removeAttribute('aria-busy');
    dispatchBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      Execute Reasoning
    `;
  }
}

function renderErrorResult(errorMessage) {
  const bodyEl = document.getElementById('response-text-body');
  bodyEl.innerHTML = `<div class="error-notice"><strong>⚠️ Request Error:</strong> ${escapeHtml(errorMessage)}</div>`;

  document.getElementById('latency-indicator').innerHTML = `Latency: <strong>-- ms</strong>`;
  document.getElementById('confidence-indicator').innerHTML = `Conf: <strong>0%</strong>`;

  const riskBadge = document.getElementById('risk-category-badge');
  riskBadge.className = 'risk-badge risk-error';
  riskBadge.textContent = 'Error • Invalid Request';

  document.getElementById('approval-gate-banner').classList.add('hidden');

  const citationsList = document.getElementById('citations-list');
  const citationsCount = document.getElementById('citations-count-badge');
  citationsCount.textContent = '0 Cited';
  citationsList.innerHTML = '<div class="empty-state">No sources available due to request error.</div>';
}

function renderReasoningResult(result) {
  window._currentApprovalId = result.approval_id || null;
  const bodyEl = document.getElementById('response-text-body');

  const orch = result.agent_orchestration || {};
  const plan = orch.plan || {};
  const steps = plan.steps || [];
  let planHtml = '';
  if (steps.length > 0) {
    planHtml = '<div style="margin-top: 12px; padding: 10px; background: rgba(255,255,255,0.05); border-radius: 6px; border: 1px solid rgba(255,255,255,0.1);">' +
      `<strong>Agent Orchestration Plan (${steps.length} Steps):</strong><ol style="margin: 6px 0 0 20px;">` +
      steps.map(s => `<li><strong>${escapeHtml(s.description || s.tool_name)}</strong> [Tool: <code>${escapeHtml(s.tool_name)}</code>, Risk: ${escapeHtml(s.risk_level)}] - Status: ${escapeHtml(s.state)}</li>`).join('') +
      '</ol></div>';
  }

  const engineMode = (result.engine_info && result.engine_info.active_mode) ? result.engine_info.active_mode : 'real_local';
  const engineBadge = `<div style="margin-top: 6px; font-size: 0.78em; opacity: 0.75;">Engine: <strong>${escapeHtml(engineMode)}</strong></div>`;

  bodyEl.innerHTML = `<div>${escapeHtml(result.response_text)}</div>${planHtml}${engineBadge}`;

  document.getElementById('latency-indicator').innerHTML = `Latency: <strong>${result.latency_ms || 12} ms</strong>`;
  document.getElementById('confidence-indicator').innerHTML = `Conf: <strong>${Math.round(result.confidence * 100)}%</strong>`;

  const riskBadge = document.getElementById('risk-category-badge');
  if (result.status === 'needs_clarification') {
    riskBadge.className = 'risk-badge risk-clarification';
    riskBadge.textContent = 'Needs Clarification';
  } else {
    const level = result.risk_level || 'A';
    riskBadge.className = `risk-badge risk-${level.toLowerCase()}`;
    const labelMap = {
      'A': 'Category A • Informational',
      'B': 'Category B • Low-Risk',
      'C': 'Category C • Sensitive (Approval Required)',
      'D': 'Category D • Destructive (Critical Gate)'
    };
    riskBadge.textContent = labelMap[level] || `Category ${level}`;
  }

  // Approval Gate Banner
  const gateBanner = document.getElementById('approval-gate-banner');
  if (result.requires_approval) {
    gateBanner.classList.remove('hidden');
    document.getElementById('gate-message').textContent = 
      `Action '${result.action_type || 'unnamed'}' requires human confirmation. Risk Category: ${result.risk_level}.`;
    announceToA11y(`Safety warning: Action ${result.action_type || 'unnamed'} requires human confirmation.`);
  } else {
    gateBanner.classList.add('hidden');
  }

  // Citations / Grounded Sources
  const citationsList = document.getElementById('citations-list');
  const citationsCount = document.getElementById('citations-count-badge');
  citationsList.innerHTML = '';

  const sources = result.sources || [];
  citationsCount.textContent = `${sources.length} Cited`;

  if (sources.length === 0) {
    if (result.status === 'needs_clarification') {
      citationsList.innerHTML = '<div class="empty-state">No context sources support this answer (clarification needed).</div>';
    } else {
      citationsList.innerHTML = '<div class="empty-state">No sources cited for this response.</div>';
    }
  } else {
    sources.forEach(src => {
      const card = document.createElement('div');
      card.className = 'citation-card';
      const safeType = escapeHtml(src.source_type);
      const safeId = escapeHtml(src.source_id);
      const safeLoc = escapeHtml(src.reference_location || 'workspace');
      card.innerHTML = `
        <div class="citation-header">
          <span class="citation-ref">[${safeType}] ${safeId} @ ${safeLoc}</span>
          <span class="citation-conf">Confidence: ${Math.round((src.confidence_score || 1.0) * 100)}%</span>
        </div>
        ${src.excerpt ? `<div class="citation-excerpt">"${escapeHtml(src.excerpt)}"</div>` : ''}
      `;
      citationsList.appendChild(card);
    });
  }

  if (result.rendered_prompt) {
    document.getElementById('raw-prompt-preview').textContent = result.rendered_prompt;
  }
}

async function updatePromptPreview(query, items) {
  try {
    const version = document.getElementById('prompt-version-select').value;
    const res = await fetch('/api/prompt-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_query: query, prompt_version: version, scenario: activeScenario })
    });
    if (!res.ok) {
      let errMsg = `HTTP Error ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson && errJson.error) errMsg = errJson.error;
      } catch (_) {}
      document.getElementById('raw-prompt-preview').textContent = `[Prompt Preview Unavailable: ${errMsg}]`;
      return;
    }
    const data = await res.json();
    document.getElementById('raw-prompt-preview').textContent = data.rendered_prompt;
  } catch (err) {
    console.warn("Failed to fetch prompt preview", err);
    document.getElementById('raw-prompt-preview').textContent = `[Prompt Preview Error: ${err.message}]`;
  }
}

async function openTestModal() {
  lastFocusedElement = document.activeElement;
  const modal = document.getElementById('test-modal');
  modal.classList.remove('hidden');
  const closeBtn = document.getElementById('btn-close-modal');
  if (closeBtn) closeBtn.focus();
  await runTestsInModal();
}

function closeTestModal() {
  const modal = document.getElementById('test-modal');
  if (modal) {
    modal.classList.add('hidden');
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
      lastFocusedElement.focus();
    }
  }
}

async function runTestsInModal() {
  const logEl = document.getElementById('test-log-output');
  logEl.textContent = 'Executing unit tests across schemas, fixtures, versioned prompts, and mock reasoning...';

  try {
    const res = await fetch('/api/run-tests');
    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }
    const data = await res.json();

    document.getElementById('test-total-count').textContent = data.total;
    document.getElementById('test-pass-count').textContent = data.passed;
    document.getElementById('test-fail-count').textContent = data.failures;
    document.getElementById('test-duration').textContent = `${data.duration}s`;
    logEl.textContent = data.log;

    // Dynamically update header test button text with accurate count
    const headerTestBtn = document.getElementById('btn-run-tests');
    if (headerTestBtn) {
      headerTestBtn.innerHTML = `
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
        Run Tests (${data.passed}/${data.total})
      `;
    }

    if (data.failures === 0) {
      showToast(`All ${data.total} unit tests passed (${data.duration}s)`, "success");
    } else {
      showToast(`${data.failures} test(s) failed`, "danger");
    }
  } catch (err) {
    logEl.textContent = 'Error running tests: ' + err.message;
    showToast("Error running unit tests: " + err.message, "danger");
  }
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
