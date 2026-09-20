/**
 * Talking to one agent, and watching a run as it happens.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import {
  askAgent,
  fetchAgentTraces,
  fetchAgentTrace,
  fetchManagedAgent,
  fetchModels,
  updateManagedAgent,
} from '../../lib/api';
import type { ManagedAgent, AgentTraceDetail } from '../../lib/api';
import { useAgentEvents } from '../../lib/useAgentEvents';
import type { AgentEvent } from '../../lib/useAgentEvents';
import { Activity, X, Send, Loader2 } from 'lucide-react';
import type { ToolCallInfo } from '../../types';
import { ToolCallCard } from '../../components/Chat/ToolCallCard';
import {
  formatAgentSchedule,
  formatCost,
  formatRelativeTime,
} from '../../lib/agent-format';

type LiveItem =
  | { kind: 'note'; id: string; label: string }
  | { kind: 'tool'; id: string; tool: ToolCallInfo };

/** Convert a persisted trace step into a ToolCallInfo for ToolCallCard. */
export function stepToToolCall(
  step: AgentTraceDetail['steps'][number],
  idx: number,
): ToolCallInfo {
  const input = (step.input ?? {}) as { tool?: string; args?: unknown };
  const out = step.output as unknown;
  const result =
    typeof out === 'string'
      ? out
      : out && typeof out === 'object' && 'result' in out
        ? String((out as { result: unknown }).result ?? '')
        : out != null
          ? JSON.stringify(out)
          : '';
  const args = input.args;
  return {
    id: `step-${idx}`,
    tool: input.tool || step.step_type || 'step',
    arguments:
      typeof args === 'string' ? args : args != null ? JSON.stringify(args) : '',
    status: 'success',
    result,
    latency: step.duration ? step.duration * 1000 : undefined,
  };
}

// ---------------------------------------------------------------------------
// Interact tab — trace viewer (top) + follow-up chat (bottom).
//
// The chat input doesn't open a side-channel chat; it triggers a real ad-hoc
// agent run (execute_tick) with the user's question as input. The trace area
// shows that run live (tick + tool calls over the events WebSocket) and, when
// idle, the last run's trace steps plus the agent's resulting findings — so
// users can interrogate the agent about its work ("tell me more about X").
// ---------------------------------------------------------------------------
export function InteractTab({ agentId, agentStatus, onRunStateChange }: { agentId: string; agentStatus: string; onRunStateChange?: () => void }) {
  const [agent, setAgent] = useState<ManagedAgent | null>(null);
  const [activity, setActivity] = useState('');
  const [running, setRunning] = useState(agentStatus === 'running');
  const [liveItems, setLiveItems] = useState<LiveItem[]>([]);
  const [lastTrace, setLastTrace] = useState<AgentTraceDetail | null>(null);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [question, setQuestion] = useState(''); // question driving the current/last run
  const [elapsedMs, setElapsedMs] = useState(0);

  const startRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runningRef = useRef(running);
  runningRef.current = running;
  const bottomRef = useRef<HTMLDivElement>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Load idle snapshot: agent record (status + findings) and the latest trace.
  const loadIdle = useCallback(async () => {
    try {
      const a = await fetchManagedAgent(agentId);
      setAgent(a);
      setActivity(a.current_activity || '');
      try {
        const traces = await fetchAgentTraces(agentId, 1);
        if (traces.length > 0) {
          const detail = await fetchAgentTrace(agentId, traces[0].id);
          setLastTrace(detail);
        }
      } catch {
        /* trace store may be empty */
      }
    } catch {
      /* ignore */
    }
  }, [agentId]);

  useEffect(() => {
    loadIdle();
  }, [loadIdle]);

  // Tick the elapsed timer while running.
  useEffect(() => {
    if (!running) {
      clearTimer();
      return;
    }
    if (!startRef.current) startRef.current = Date.now();
    timerRef.current = setInterval(
      () => setElapsedMs(Date.now() - startRef.current),
      100,
    );
    return clearTimer;
  }, [running, clearTimer]);

  const finishRun = useCallback(() => {
    setRunning(false);
    startRef.current = 0;
    clearTimer();
    // Give the backend a beat to persist summary_memory + trace, then refresh
    // both this tab and the parent (so the detail/list status badge flips back
    // from "running" to "idle" without waiting for the slow background poll).
    setTimeout(() => {
      loadIdle();
      onRunStateChange?.();
    }, 500);
  }, [clearTimer, loadIdle, onRunStateChange]);

  // Live trace: assemble events from the agent events WebSocket.
  const onEvent = useCallback(
    (ev: AgentEvent) => {
      const data = ev.data || {};
      switch (ev.type) {
        case 'agent_tick_start': {
          startRef.current = Date.now();
          setElapsedMs(0);
          setRunning(true);
          setErrorMsg('');
          setLiveItems([{ kind: 'note', id: `start-${ev.timestamp}`, label: 'Run started' }]);
          break;
        }
        case 'tool_call_start': {
          const id = `tc-${ev.timestamp}-${Math.random().toString(36).slice(2, 6)}`;
          const args = data.arguments;
          const tc: ToolCallInfo = {
            id,
            tool: String(data.tool || 'tool'),
            arguments:
              typeof args === 'string' ? args : args != null ? JSON.stringify(args) : '',
            status: 'running',
          };
          setLiveItems((prev) => [...prev, { kind: 'tool', id, tool: tc }]);
          break;
        }
        case 'tool_call_end': {
          setLiveItems((prev) => {
            const next = [...prev];
            for (let i = next.length - 1; i >= 0; i--) {
              const it = next[i];
              if (
                it.kind === 'tool' &&
                it.tool.tool === String(data.tool) &&
                it.tool.status === 'running'
              ) {
                next[i] = {
                  ...it,
                  tool: {
                    ...it.tool,
                    status: data.success === false ? 'error' : 'success',
                    result:
                      typeof data.result === 'string' ? data.result : it.tool.result,
                    latency:
                      typeof data.latency === 'number'
                        ? data.latency * 1000
                        : it.tool.latency,
                  },
                };
                break;
              }
            }
            return next;
          });
          break;
        }
        case 'agent_tick_end':
        case 'agent_tick_error': {
          if (ev.type === 'agent_tick_error') {
            setErrorMsg(String(data.error || 'The run failed.'));
          }
          finishRun();
          break;
        }
      }
    },
    [finishRun],
  );

  useAgentEvents(agentId, onEvent, [
    'agent_tick_start',
    'tool_call_start',
    'tool_call_end',
    'agent_tick_end',
    'agent_tick_error',
  ]);

  // Fallback poll — WS is primary, but this catches missed tick_end events and
  // runs started elsewhere (e.g. the scheduler or the Overview "Run" button).
  useEffect(() => {
    const iv = setInterval(async () => {
      try {
        const a = await fetchManagedAgent(agentId);
        setActivity(a.current_activity || '');
        if (a.status === 'running' && !runningRef.current) {
          setRunning(true);
        } else if (a.status !== 'running' && runningRef.current) {
          finishRun();
        }
      } catch {
        /* ignore */
      }
    }, 3000);
    return () => clearInterval(iv);
  }, [agentId, finishRun]);

  // Keep pinned to the newest live item.
  useEffect(() => {
    if (running) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [liveItems, running]);

  async function handleAsk() {
    const q = input.trim();
    if (!q || running || sending) return;
    setInput('');
    setQuestion(q);
    setErrorMsg('');
    setSending(true);
    setLiveItems([{ kind: 'note', id: 'queued', label: 'Starting run…' }]);
    startRef.current = Date.now();
    setElapsedMs(0);
    try {
      // immediate, non-streamed → triggers a real agent run that consumes the
      // question as input. tick_start over the WS confirms; poll is the backstop.
      await askAgent(agentId, q);
      setRunning(true);
      onRunStateChange?.(); // flip the parent status badge to "running" now
    } catch {
      setErrorMsg('Could not start the agent run.');
      setLiveItems([]);
    } finally {
      setSending(false);
    }
  }

  const isBusy = running || sending;
  const findings = agent?.summary_memory?.trim() || '';
  const traceSteps = lastTrace?.steps ?? [];

  return (
    <div className="flex flex-col" style={{ minHeight: 360 }}>
      {/* ── Trace area header ──────────────────────────────── */}
      <div className="flex items-center justify-between mb-2">
        <div
          className="flex items-center gap-2 text-sm font-medium"
          style={{ color: 'var(--color-text)' }}
        >
          <Activity size={14} style={{ color: 'var(--color-accent)' }} />
          Activity trace
        </div>
        <div
          className="flex items-center gap-2 text-xs"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {isBusy ? (
            <>
              <span
                className="inline-block w-2 h-2 rounded-full animate-pulse"
                style={{ background: 'var(--color-accent)' }}
              />
              Running{elapsedMs > 0 ? ` · ${(elapsedMs / 1000).toFixed(1)}s` : ''}
            </>
          ) : (
            <>
              {agent?.last_run_at
                ? `Last run ${new Date(agent.last_run_at * 1000).toLocaleString()}`
                : 'Idle'}
              {lastTrace && ` · ${lastTrace.outcome}`}
            </>
          )}
        </div>
      </div>

      {/* ── Trace area body ────────────────────────────────── */}
      <div
        className="flex-1 overflow-y-auto rounded-lg p-3 space-y-3"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
          maxHeight: 'calc(100vh - 360px)',
          minHeight: 200,
        }}
      >
        {question && (
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            <span style={{ color: 'var(--color-text-secondary)' }}>Question:</span> {question}
          </div>
        )}

        {errorMsg && (
          <div
            className="text-sm px-3 py-2 rounded-lg"
            style={{
              background: 'rgba(255,80,80,0.08)',
              border: '1px solid var(--color-error)',
              color: 'var(--color-error)',
            }}
          >
            {errorMsg}
          </div>
        )}

        {isBusy ? (
          /* LIVE view — current tick */
          <>
            {liveItems.map((it) =>
              it.kind === 'tool' ? (
                <ToolCallCard key={it.id} toolCall={it.tool} />
              ) : (
                <div
                  key={it.id}
                  className="flex items-center gap-2 text-sm"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full animate-pulse"
                    style={{ background: 'var(--color-accent)' }}
                  />
                  {it.label}
                </div>
              ),
            )}
            <div
              className="flex items-center gap-2 text-sm"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
              {activity || 'Agent is working…'}
            </div>
          </>
        ) : (
          /* IDLE view — last run's trace + findings */
          <>
            {traceSteps.length > 0 && (
              <div className="space-y-2">
                {traceSteps.map((s, i) => (
                  <ToolCallCard key={i} toolCall={stepToToolCall(s, i)} />
                ))}
              </div>
            )}
            {findings ? (
              <div
                className="px-3 py-2 rounded-lg text-sm"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              >
                <div className="text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                  Result
                </div>
                <div className="prose prose-sm prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{findings}</ReactMarkdown>
                </div>
              </div>
            ) : (
              traceSteps.length === 0 && (
                <div
                  className="text-sm text-center py-8"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  No runs yet. Ask a question below to run the agent.
                </div>
              )
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Follow-up chat input ───────────────────────────── */}
      <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleAsk();
            }
          }}
          placeholder={isBusy ? 'Agent is running…' : "Ask a follow-up about this agent's work…"}
          disabled={isBusy}
          className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
          style={{
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
            minHeight: 64,
            opacity: isBusy ? 0.6 : 1,
          }}
        />
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Sends your question as an ad-hoc run — results appear in the trace above.
          </span>
          <button
            onClick={handleAsk}
            disabled={isBusy || !input.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer font-medium"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-on-accent)',
              opacity: isBusy || !input.trim() ? 0.5 : 1,
            }}
          >
            {isBusy ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
            {isBusy ? 'Running' : 'Ask'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channels tab component (data sources)
// ---------------------------------------------------------------------------

export function AgentInstructionSection({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const currentInstruction = (agent.config?.instruction as string) || '';

  async function save() {
    try {
      const newConfig = { ...(agent.config || {}), instruction: draft.trim() };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
    } catch { /* ignore */ }
    setEditing(false);
  }

  return (
    <div
      className="p-3 rounded-lg"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Instruction</h3>
        {!editing && (
          <button
            onClick={() => { setDraft(currentInstruction); setEditing(true); }}
            className="text-xs px-2 py-0.5 rounded cursor-pointer"
            style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)', opacity: 0.8 }}
          >
            Edit
          </button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
          <div className="flex gap-2">
            <button onClick={save} className="text-xs px-3 py-1 rounded font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>Save</button>
            <button onClick={() => setEditing(false)} className="text-xs px-3 py-1 rounded cursor-pointer" style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}>Cancel</button>
          </div>
        </div>
      ) : (
        <p className="text-sm" style={{ color: currentInstruction ? 'var(--color-text)' : 'var(--color-text-tertiary)' }}>
          {currentInstruction || '(No instruction set — click Edit to add one)'}
        </p>
      )}
    </div>
  );
}

export function AgentConfigGrid({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editingModel, setEditingModel] = useState(false);
  const [changingModel, setChangingModel] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const currentModel = (agent.config?.model as string) || '(default)';

  // Model availability status: 'available' | 'unavailable' | 'unknown'
  const [modelAvailable, setModelAvailable] = useState<'available' | 'unavailable' | 'unknown'>('unknown');
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function checkModel() {
      try {
        // Ask the backend which models are installed rather than hitting
        // Ollama directly from the browser: the backend always knows where
        // Ollama lives (incl. remote) and there's no cross-origin/CORS issue,
        // which is what made the check spuriously report "Not available".
        const installed = (await fetchModels()).map((m) => m.id);
        if (cancelled) return;
        setOllamaModels(installed);
        if (currentModel === '(default)') {
          setModelAvailable(installed.length > 0 ? 'available' : 'unknown');
        } else {
          const isInstalled = installed.some(
            (n) => n === currentModel || n.startsWith(currentModel + ':') || currentModel.startsWith(n.split(':')[0])
          );
          setModelAvailable(isInstalled ? 'available' : 'unavailable');
        }
      } catch {
        if (!cancelled) setModelAvailable('unknown');
      }
    }
    checkModel();
    return () => { cancelled = true; };
  }, [currentModel]);

  async function startEditingModel() {
    try {
      const fetched = (await fetchModels()).map((m) => m.id);
      setModels(fetched);
      // Same backend list drives both the dropdown and the availability dots.
      setOllamaModels(fetched);
    } catch { /* ignore */ }
    setEditingModel(true);
  }

  function isModelInstalled(modelId: string): boolean {
    return ollamaModels.some(
      (n) => n === modelId || n.startsWith(modelId + ':') || modelId.startsWith(n.split(':')[0])
    );
  }

  async function changeModel(newModel: string) {
    setChangingModel(true);
    try {
      const newConfig = { ...(agent.config || {}), model: newModel };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
      toast.success(`Model changed to ${newModel}`);
    } catch { /* ignore */ }
    setEditingModel(false);
    setChangingModel(false);
  }

  const modelStatusDot = modelAvailable === 'available'
    ? 'var(--color-success)'
    : modelAvailable === 'unavailable'
      ? 'var(--color-error)'
      : 'var(--color-text-tertiary)';

  const rows: [string, React.ReactNode][] = [
    ['Intelligence', editingModel ? (
      changingModel ? (
        <span className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>Switching model...</span>
      ) : (
        <select
          autoFocus
          defaultValue={currentModel}
          onChange={(e) => changeModel(e.target.value)}
          onBlur={() => setEditingModel(false)}
          className="text-sm rounded px-1 py-0.5"
          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        >
          {models.map((m) => {
            const installed = isModelInstalled(m);
            return (
              <option key={m} value={m} style={!installed ? { color: 'var(--color-text-tertiary)' } : undefined}>
                {m}{!installed ? ' (not installed)' : ''}
              </option>
            );
          })}
        </select>
      )
    ) : (
      <span className="flex items-center gap-2">
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: modelStatusDot,
            display: 'inline-block',
            flexShrink: 0,
          }}
          title={
            modelAvailable === 'available' ? 'Model running'
              : modelAvailable === 'unavailable' ? 'Model not available'
                : 'Could not check model status'
          }
        />
        <span style={{ color: 'var(--color-text)' }}>{currentModel}</span>
        {modelAvailable === 'unavailable' && (
          <span className="text-xs" style={{ color: 'var(--color-error)' }}>Not available</span>
        )}
        <button
          onClick={startEditingModel}
          className="text-xs px-2 py-0.5 rounded cursor-pointer"
          style={{
            color: modelAvailable === 'unavailable' ? 'var(--color-error)' : 'var(--color-accent)',
            border: `1px solid ${modelAvailable === 'unavailable' ? 'var(--color-error)' : 'var(--color-accent)'}`,
            opacity: 0.8,
          }}
        >
          Change
        </button>
      </span>
    )],
    ['Agent Type', <span key="at">{agent.agent_type}</span>],
    ['Schedule', <span key="sc">{formatAgentSchedule(agent)}</span>],
    ['Last Run', <span key="lr">{formatRelativeTime(agent.last_run_at)}</span>],
    ['Budget', <span key="bg">{agent.budget ? formatCost(agent.budget) : 'Unlimited'}</span>],
    ['Learning', <span key="le">{agent.learning_enabled ? 'Enabled' : 'Disabled'}</span>],
  ];

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
      {rows.map(([label, value]) => (
        <div key={label as string} className="flex gap-2 items-center text-sm">
          <span className="font-medium" style={{ color: 'var(--color-text-secondary)', minWidth: 110 }}>{label}</span>
          <span style={{ color: 'var(--color-text)' }}>{value}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail view — Interact tab
// ---------------------------------------------------------------------------

/** One entry in the live activity feed assembled from agent events. */
