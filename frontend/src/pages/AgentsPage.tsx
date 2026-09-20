import { useEffect, useState, useCallback, useRef } from 'react';
import { toast } from 'sonner';
import { useAppStore } from '../lib/store';
import {
  fetchManagedAgents,
  fetchAgentTasks,
  fetchAgentChannels,
  fetchTemplates,
  pauseManagedAgent,
  resumeManagedAgent,
  deleteManagedAgent,
  runManagedAgent,
  recoverManagedAgent,
  fetchManagedAgent,
} from '../lib/api';
import type { AgentTask, ChannelBinding, AgentTemplate } from '../lib/api';
import {
  Plus,
  Bot,
  Pause,
  Play,
  Trash2,
  ChevronLeft,
  ListTodo,
  Brain,
  Zap,
  AlertTriangle,
  Activity,
  MessageSquare,
  Settings,
  FileText,
  Wifi,
  Database,
} from 'lucide-react';
import { AgentCard, StatusBadge } from './agents/AgentCard';
import {
  AgentConfigGrid,
  AgentInstructionSection,
  InteractTab,
} from './agents/InteractTab';
import { ChannelsTab, MessagingTab } from './agents/MessagingTab';
import { LaunchWizard } from './agents/LaunchWizard';
import { LearningTab } from './agents/LearningTab';
import { LogsTab } from './agents/LogsTab';
import { statusColor } from '../lib/agent-format';

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

export function AgentsPage() {
  const managedAgents = useAppStore((s) => s.managedAgents);
  const setManagedAgents = useAppStore((s) => s.setManagedAgents);
  const selectedAgentId = useAppStore((s) => s.selectedAgentId);
  const setSelectedAgentId = useAppStore((s) => s.setSelectedAgentId);
  const savings = useAppStore((s) => s.savings);
  const [loading, setLoading] = useState(true);
  const [agentManagerAvailable, setAgentManagerAvailable] = useState<boolean | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [channels, setChannels] = useState<ChannelBinding[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [showWizard, setShowWizard] = useState(false);
  const [detailTab, setDetailTab] = useState<'overview' | 'interact' | 'channels' | 'messaging' | 'tasks' | 'memory' | 'learning' | 'logs'>('interact');

  const refresh = useCallback(async () => {
    try {
      const agents = await fetchManagedAgents();
      setManagedAgents(agents);
      setAgentManagerAvailable(true);
    } catch (err: any) {
      if (err.message?.includes('404')) {
        setAgentManagerAvailable(false);
      }
      setManagedAgents([]);
    } finally {
      setLoading(false);
    }
  }, [setManagedAgents]);

  useEffect(() => {
    refresh();
    fetchTemplates().then(setTemplates).catch(() => {});
  }, [refresh]);

  const selectedAgent = managedAgents.find((a) => a.id === selectedAgentId);

  useEffect(() => {
    if (selectedAgentId) {
      fetchAgentTasks(selectedAgentId).then(setTasks).catch(() => setTasks([]));
      fetchAgentChannels(selectedAgentId).then(setChannels).catch(() => setChannels([]));
    }
  }, [selectedAgentId]);

  const handlePause = async (id: string) => {
    await pauseManagedAgent(id).catch(() => {});
    await refresh();
  };

  const handleResume = async (id: string) => {
    await resumeManagedAgent(id).catch(() => {});
    await refresh();
  };

  const handleDelete = async (id: string) => {
    await deleteManagedAgent(id).catch(() => {});
    if (selectedAgentId === id) setSelectedAgentId(null);
    await refresh();
  };

  const handleRun = async (id: string) => {
    try {
      await runManagedAgent(id);
    } catch (err: any) {
      toast.error('Failed to start agent', {
        description: err.message || 'Unknown error',
      });
      await refresh();
      return;
    }
    await refresh();
    setTimeout(async () => {
      try {
        const agent = await fetchManagedAgent(id);
        if (agent.status === 'error') {
          toast.error(`Agent "${agent.name}" failed`, {
            description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
          });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'error', category: 'model',
            message: `Agent "${agent.name}" failed: ${agent.summary_memory || 'Unknown error'}`,
          });
        }
      } catch {}
      await refresh();
    }, 3000);
  };

  const handleRecover = async (id: string) => {
    try {
      const result = await recoverManagedAgent(id);
      if (result.checkpoint) {
        toast.success('Agent recovered from checkpoint');
      } else {
        toast.success('Agent reset to idle (no checkpoint available)');
      }
      setDetailTab('overview');
    } catch (err: any) {
      toast.error('Recovery failed', {
        description: err.message || 'Unknown error',
      });
    }
    await refresh();
  };

  const prevStatuses = useRef<Record<string, string>>({});
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const agents = await fetchManagedAgents();
        for (const agent of agents) {
          const prev = prevStatuses.current[agent.id];
          if (prev && prev !== 'error' && agent.status === 'error') {
            toast.error(`Agent "${agent.name}" failed`, {
              description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
            });
          }
          prevStatuses.current[agent.id] = agent.status;
        }
        // Keep the agent list — and the derived selectedAgent status badge —
        // live. This poll previously fetched statuses only to fire error
        // toasts and threw the result away, so a detail header could stay
        // stuck on "running" after a tick finished on the backend.
        setManagedAgents(agents);
      } catch {}
    }, 5000);
    return () => clearInterval(interval);
  }, [setManagedAgents]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
        Loading agents...
      </div>
    );
  }

  // ── Detail View ─────────────────────────────────────────────────────────

  if (selectedAgent) {
    const successRate =
      tasks.length > 0
        ? Math.round((tasks.filter((t) => t.status === 'completed').length / tasks.length) * 100)
        : null;

    const DETAIL_TABS = [
      { id: 'interact', label: 'Interact', icon: MessageSquare },
      { id: 'overview', label: 'Overview', icon: Activity },
      { id: 'channels', label: 'Data Sources', icon: Database },
      { id: 'messaging', label: 'Messaging Channels', icon: Wifi },
      { id: 'tasks', label: 'Tasks', icon: ListTodo },
      { id: 'memory', label: 'Memory', icon: Brain },
      { id: 'learning', label: 'Learning', icon: Settings },
      { id: 'logs', label: 'Logs', icon: FileText },
    ] as const;

    return (
      <div className="flex-1 overflow-y-auto px-6 py-10">
        <div className="max-w-5xl mx-auto">
        {/* Back button */}
        <button
          onClick={() => setSelectedAgentId(null)}
          className="flex items-center gap-1 mb-4 text-sm cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <ChevronLeft size={16} /> Back to agents
        </button>

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-3">
            <Bot size={24} style={{ color: 'var(--color-accent)' }} />
            <div>
              <h1 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
                {selectedAgent.name}
              </h1>
              <div className="flex items-center gap-2 mt-1">
                <StatusBadge status={selectedAgent.status} />
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {selectedAgent.agent_type}
                </span>
              </div>
            </div>
          </div>
          {/* Header actions */}
          <div className="flex items-center gap-2">
            {detailTab === 'interact' ? (
              <span
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
                style={{ background: 'var(--color-success)20', color: 'var(--color-success)', border: '1px solid var(--color-success)40' }}
              >
                <MessageSquare size={13} /> Chat ready — just type below
              </span>
            ) : (
              <button
                onClick={() => handleRun(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer font-medium"
                style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
              >
                <Zap size={13} /> Run Now
              </button>
            )}
            {(selectedAgent.status === 'running' || selectedAgent.status === 'idle') && (
              <button
                onClick={() => handlePause(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <Pause size={13} /> Pause
              </button>
            )}
            {selectedAgent.status === 'paused' && (
              <button
                onClick={() => handleResume(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-success)20', color: 'var(--color-success)', border: '1px solid var(--color-success)40' }}
              >
                <Play size={13} /> Resume
              </button>
            )}
            {(selectedAgent.status === 'error' || selectedAgent.status === 'stalled' || selectedAgent.status === 'needs_attention') && (
              <button
                onClick={() => handleRecover(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-error)20', color: 'var(--color-error)', border: '1px solid var(--color-error)40' }}
              >
                <AlertTriangle size={13} /> Recover
              </button>
            )}
            <button
              onClick={async () => {
                if (window.confirm(`Delete ${selectedAgent.name}? This cannot be undone.`)) {
                  await deleteManagedAgent(selectedAgent.id);
                  setSelectedAgentId(null);
                  await refresh();
                }
              }}
              className="p-1.5 rounded-lg cursor-pointer transition-colors"
              style={{ color: 'var(--color-error)', background: 'var(--color-error)15' }}
              title="Delete agent"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 p-1 rounded-lg overflow-x-auto" style={{ background: 'var(--color-bg-secondary)' }}>
          {DETAIL_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setDetailTab(id)}
              className="px-3 py-2 rounded-md text-xs flex items-center gap-1.5 whitespace-nowrap cursor-pointer transition-colors"
              style={{
                background: detailTab === id ? 'var(--color-bg)' : 'transparent',
                color: detailTab === id ? 'var(--color-text)' : 'var(--color-text-secondary)',
                fontWeight: detailTab === id ? 500 : 400,
              }}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        {/* Tab: Overview */}
        {detailTab === 'overview' && (
          <div className="space-y-3">
            {/* Instruction */}
            <AgentInstructionSection agent={selectedAgent} onAgentUpdated={refresh} />

            {/* Configuration */}
            <div
              className="p-3 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--color-text)' }}>
                Configuration
              </h3>
              <AgentConfigGrid agent={selectedAgent} onAgentUpdated={refresh} />
              <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
                <span className="text-xs font-mono" style={{ color: 'var(--color-text-tertiary)' }}>
                  ID: {selectedAgent.id}
                </span>
              </div>
            </div>

            {/* Hint for deep research agents */}
            {selectedAgent.agent_type === 'deep_research' && (
              <div
                className="flex items-start gap-3 p-3 rounded-lg text-sm"
                style={{
                  background: 'var(--color-accent-subtle)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0, marginTop: 2 }} />
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  <strong>Tip:</strong> Connect your personal data in the{' '}
                  <button
                    onClick={() => setDetailTab('channels')}
                    className="cursor-pointer underline"
                    style={{ color: 'var(--color-accent)', background: 'none', border: 'none', padding: 0, font: 'inherit' }}
                  >Data Sources</button>{' '}
                  tab, then set up{' '}
                  <button
                    onClick={() => setDetailTab('messaging')}
                    className="cursor-pointer underline"
                    style={{ color: 'var(--color-accent)', background: 'none', border: 'none', padding: 0, font: 'inherit' }}
                  >Messaging Channels</button>{' '}
                  to talk to this agent from your phone.
                </div>
              </div>
            )}

            {/* Usage stats + savings — single compact row */}
            {(() => {
              const inTok = selectedAgent.input_tokens ?? 0;
              const outTok = selectedAgent.output_tokens ?? 0;
              const modelName = (selectedAgent.config?.model as string) || '';
              const paramMatch = modelName.match(/:(\d+(?:\.\d+)?)b/i);
              const paramsB = paramMatch ? parseFloat(paramMatch[1]) : 9;
              const flops = 2 * paramsB * 1e9 * (inTok + outTok);
              const providers = [
                { label: 'GPT-5.6 Sol', inPer1M: 5.0, outPer1M: 30.0 },
                { label: 'Claude Fable 5', inPer1M: 10.0, outPer1M: 50.0 },
                { label: 'Gemini 3.1 Pro', inPer1M: 2.0, outPer1M: 12.0 },
              ];
              const energyWh = (inTok + outTok) / 1000 * 0.4;
              const energyKj = energyWh * 3.6;
              const fmtFlops = flops >= 1e15 ? `${(flops / 1e15).toFixed(1)} PFLOPs` : `${(flops / 1e12).toFixed(1)} TFLOPs`;
              const hasSavings = inTok + outTok > 0;
              const sectionTitle = { fontSize: 11, fontWeight: 600, color: 'var(--color-text-tertiary)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 8 };
              return (
                <div className="p-4 rounded-xl" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                  <div className="flex gap-0 flex-wrap items-stretch">
                    {/* Agent Statistics */}
                    <div className="pr-5">
                      <p style={sectionTitle}>Agent Statistics</p>
                      <div className="flex gap-5">
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{selectedAgent.total_runs ?? 0}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Total Queries</p>
                        </div>
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{inTok.toLocaleString()}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Input Tokens</p>
                        </div>
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{outTok.toLocaleString()}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Output Tokens</p>
                        </div>
                      </div>
                    </div>
                    {hasSavings && (<>
                      <div style={{ width: 1, background: 'var(--color-border)' }} />
                      {/* Local Utilization */}
                      <div className="px-5">
                        <p style={sectionTitle}>Local Utilization</p>
                        <div className="flex gap-5">
                          <div>
                            <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-success)' }}>{fmtFlops}</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Compute</p>
                          </div>
                          <div>
                            <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-success)' }}>{energyKj.toFixed(2)} kJ</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Energy</p>
                          </div>
                        </div>
                      </div>
                      <div style={{ width: 1, background: 'var(--color-border)' }} />
                      {/* Dollars Saved */}
                      <div className="pl-5">
                        <p style={sectionTitle}>Dollars Saved vs.</p>
                        <div className="flex gap-5">
                          {providers.map((p) => {
                            const cost = (inTok / 1e6) * p.inPer1M + (outTok / 1e6) * p.outPer1M;
                            return (
                              <div key={p.label}>
                                <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-success)' }}>${cost.toFixed(4)}</p>
                                <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{p.label}</p>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </>)}
                  </div>
                </div>);
            })()}

            {/* Channels summary */}
            {channels.length > 0 && (
              <div
                className="p-4 rounded-lg"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Messaging Channels
                </h3>
                {channels.map((b) => (
                  <div key={b.id} className="text-sm py-1" style={{ color: 'var(--color-text)' }}>
                    {b.channel_type}: {b.routing_mode}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab: Interact */}
        {detailTab === 'interact' && <InteractTab agentId={selectedAgent.id} agentStatus={selectedAgent.status} onRunStateChange={refresh} />}

        {/* Tab: Channels */}
        {detailTab === 'channels' && (
          <ChannelsTab agentId={selectedAgent.id} />
        )}

        {/* Tab: Messaging */}
        {detailTab === 'messaging' && (
          <MessagingTab agentId={selectedAgent.id} />
        )}

        {/* Tab: Tasks */}
        {detailTab === 'tasks' && (
          <div className="space-y-2">
            {tasks.map((t) => (
              <div
                key={t.id}
                className="p-3 rounded-lg"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex justify-between items-start gap-3">
                  <span className="text-sm" style={{ color: 'var(--color-text)' }}>
                    {t.description}
                  </span>
                  <span
                    className="text-xs px-2 py-0.5 rounded flex-shrink-0"
                    style={{
                      background: statusColor(t.status) + '20',
                      color: statusColor(t.status),
                    }}
                  >
                    {t.status}
                  </span>
                </div>
              </div>
            ))}
            {tasks.length === 0 && (
              <div className="text-sm py-8 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
                No tasks assigned.
              </div>
            )}
          </div>
        )}

        {/* Tab: Memory */}
        {detailTab === 'memory' && (
          <div
            className="p-4 rounded-lg"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <h3 className="text-sm font-medium mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-secondary)' }}>
              <Brain size={14} /> Summary Memory
            </h3>
            <p className="whitespace-pre-wrap text-sm" style={{ color: 'var(--color-text)' }}>
              {selectedAgent.summary_memory || 'Agent has no stored memory yet.'}
            </p>
          </div>
        )}

        {/* Tab: Learning */}
        {detailTab === 'learning' && (
          <LearningTab agentId={selectedAgent.id} learningEnabled={!!selectedAgent.learning_enabled} />
        )}

        {/* Tab: Logs */}
        {detailTab === 'logs' && (
          <LogsTab agentId={selectedAgent.id} />
        )}
        </div>
      </div>
    );
  }

  // ── List View ───────────────────────────────────────────────────────────

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
      {/* Launch wizard modal */}
      {showWizard && (
        <LaunchWizard
          templates={templates}
          onClose={() => setShowWizard(false)}
          onLaunched={() => {
            setShowWizard(false);
            refresh();
          }}
        />
      )}

      <header className="mb-6">
        <div className="flex justify-between items-center">
          <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
            Agents
          </h1>
          <button
            onClick={() => agentManagerAvailable && setShowWizard(true)}
            disabled={agentManagerAvailable === false}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: agentManagerAvailable === false ? 'var(--color-bg-tertiary)' : 'var(--color-accent)',
              color: agentManagerAvailable === false ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
            }}
          >
            <Plus size={15} /> New Agent
          </button>
        </div>
        <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
          Long-running autonomous agents that can monitor sources, run tasks on a schedule, and message you through connected channels.
        </p>
      </header>

      {agentManagerAvailable === false && (
        <div
          className="mx-4 mt-2 px-4 py-3 rounded-lg flex items-center gap-3 text-sm"
          style={{
            background: 'var(--color-accent-amber-subtle)',
            border: '1px solid color-mix(in srgb, var(--color-warning) 20%, transparent)',
            color: 'var(--color-accent-amber)',
          }}
        >
          <AlertTriangle size={16} />
          <span>Agent manager is not enabled. Set <code className="font-mono text-xs">agent_manager.enabled = true</code> in your config.</span>
        </div>
      )}

      {/* Agent cards grid */}
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
        {managedAgents.map((a) => (
          <AgentCard
            key={a.id}
            agent={a}
            onClick={() => {
              setSelectedAgentId(a.id);
              setDetailTab('overview');
            }}
            onPause={handlePause}
            onResume={handleResume}
            onRun={handleRun}
            onRecover={handleRecover}
            onDelete={handleDelete}
            onChat={(id) => {
              setSelectedAgentId(id);
              setDetailTab('interact');
            }}
            onEdit={(id) => {
              setSelectedAgentId(id);
              setDetailTab('overview');
            }}
          />
        ))}
      </div>

      {managedAgents.length === 0 && (
        <div className="text-center py-16" style={{ color: 'var(--color-text-tertiary)' }}>
          <Bot size={48} className="mx-auto mb-4 opacity-30" />
          <p className="mb-2 font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            No agents yet
          </p>
          <p className="text-sm mb-6">Create your first agent to get started with autonomous task management.</p>
          <button
            onClick={() => agentManagerAvailable && setShowWizard(true)}
            disabled={agentManagerAvailable === false}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: agentManagerAvailable === false ? 'var(--color-bg-tertiary)' : 'var(--color-accent)',
              color: agentManagerAvailable === false ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
            }}
          >
            <Plus size={15} /> Launch your first agent
          </button>
        </div>
      )}
      </div>
    </div>
  );
}
