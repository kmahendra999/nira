/**
 * The log stream for one agent. Takes an id, talks to the log endpoints.
 */

import { useEffect, useState, useCallback } from 'react';
import { fetchLearningLog, fetchAgentTraces } from '../../lib/api';
import type { LearningLogEntry, AgentTrace } from '../../lib/api';
import { useAgentEvents } from '../../lib/useAgentEvents';
import { Activity, Send } from 'lucide-react';
import { formatRelativeTime } from '../../lib/agent-format';

export function LogsTab({ agentId }: { agentId: string }) {
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [learningEntries, setLearningEntries] = useState<LearningLogEntry[]>([]);
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [t, l] = await Promise.all([
        fetchAgentTraces(agentId),
        fetchLearningLog(agentId),
      ]);
      setTraces(t);
      setLearningEntries(l);
    } catch {
      // ignore
    }
  }, [agentId]);

  useEffect(() => {
    loadData();
    // Fallback slow poll — WS is primary, this catches missed events
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Event-driven refresh — trace/learning entries are created by tick + tool events
  useAgentEvents(agentId, loadData, [
    'agent_tick_end',
    'agent_tick_error',
    'tool_call_end',
    'inference_end',
    'agent_learning_completed',
  ]);

  // Merge traces and learning entries into a unified timeline
  type TimelineEntry =
    | { kind: 'trace'; data: AgentTrace; ts: number }
    | { kind: 'learning'; data: LearningLogEntry; ts: number };

  const timeline: TimelineEntry[] = [
    ...traces.map((t): TimelineEntry => ({ kind: 'trace', data: t, ts: t.started_at })),
    ...learningEntries.map((e): TimelineEntry => ({ kind: 'learning', data: e, ts: e.created_at })),
  ].sort((a, b) => b.ts - a.ts);

  const learningEventColor = (eventType: string) => {
    if (eventType === 'query_start') return 'var(--color-accent)';
    if (eventType === 'query_complete') return 'var(--color-success)';
    if (eventType === 'tool_call') return 'var(--color-warning)';
    if (eventType === 'tool_result') return 'var(--color-accent-purple)';
    if (eventType === 'query_error') return 'var(--color-error)';
    return 'var(--color-text-secondary)';
  };

  const learningEventLabel = (eventType: string) => {
    if (eventType === 'query_start') return 'Query';
    if (eventType === 'query_complete') return 'Complete';
    if (eventType === 'tool_call') return 'Tool Call';
    if (eventType === 'tool_result') return 'Tool Result';
    if (eventType === 'query_error') return 'Error';
    return eventType;
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          Activity Log
        </span>
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {timeline.length} entr{timeline.length !== 1 ? 'ies' : 'y'} (auto-refreshing)
        </span>
      </div>
      {timeline.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No activity yet. Send a message or run the agent to generate logs.
        </div>
      ) : (
        <div className="space-y-2">
          {timeline.map((entry) => {
            if (entry.kind === 'learning') {
              const e = entry.data;
              return (
                <div
                  key={`learn-${e.id}`}
                  className="rounded-lg p-3 text-sm"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2 h-2 rounded-full inline-block"
                        style={{ background: learningEventColor(e.event_type) }}
                      />
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          background: `${learningEventColor(e.event_type)}20`,
                          color: learningEventColor(e.event_type),
                        }}
                      >
                        {learningEventLabel(e.event_type)}
                      </span>
                    </div>
                    <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                      {formatRelativeTime(e.created_at)}
                    </span>
                  </div>
                  <div className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {e.description}
                  </div>
                </div>
              );
            }

            // Trace entry
            const t = entry.data;
            const errorDetail = t.metadata?.error_detail as
              | { error_type: string; error_message: string; suggested_action: string }
              | undefined;
            const isError = t.outcome !== 'success';
            const isExpanded = expandedTrace === t.id;

            return (
              <div
                key={`trace-${t.id}`}
                role={isError && errorDetail ? 'button' : undefined}
                tabIndex={isError && errorDetail ? 0 : undefined}
                aria-expanded={isError && errorDetail ? isExpanded : undefined}
                onKeyDown={(e) => {
                  if (!(isError && errorDetail)) return;
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setExpandedTrace(isExpanded ? null : t.id);
                  }
                }}
                className={`rounded-lg p-3 text-sm ${
                  isError && errorDetail ? 'cursor-pointer' : ''
                }`}
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                onClick={() => isError && errorDetail && setExpandedTrace(isExpanded ? null : t.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ background: t.outcome === 'success' ? 'var(--color-success)' : 'var(--color-error)' }}
                    />
                    <span style={{ color: 'var(--color-text)' }}>{t.outcome}</span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                      style={{ background: 'var(--color-bg)', color: 'var(--color-text-secondary)' }}
                    >
                      Trace
                    </span>
                    {errorDetail && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          background: errorDetail.error_type === 'fatal' ? 'var(--color-error)20' :
                            errorDetail.error_type === 'escalate' ? 'var(--color-warning)20' : 'var(--color-accent)20',
                          color: errorDetail.error_type === 'fatal' ? 'var(--color-error)' :
                            errorDetail.error_type === 'escalate' ? 'var(--color-warning)' : 'var(--color-accent)',
                        }}
                      >
                        {errorDetail.error_type}
                      </span>
                    )}
                  </div>
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {formatRelativeTime(t.started_at)}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  <span>{t.duration.toFixed(1)}s</span>
                  <span>{t.steps} step{t.steps !== 1 ? 's' : ''}</span>
                </div>
                {isExpanded && errorDetail && (
                  <div className="mt-2 pt-2 space-y-1.5 text-xs" style={{ borderTop: '1px solid var(--color-border)' }}>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Error: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.error_message}</span>
                    </div>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Action: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.suggested_action}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

