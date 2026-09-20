/**
 * One agent in the list: status, schedule, cost, and the actions on it.
 */

import { useEffect, useState, useRef } from 'react';
import type { ManagedAgent } from '../../lib/api';
import {
  Bot,
  Pause,
  Play,
  Trash2,
  Zap,
  MoreHorizontal,
  AlertTriangle,
  DollarSign,
  Activity,
  MessageSquare,
  Pencil,
} from 'lucide-react';
import {
  formatAgentSchedule,
  formatCost,
  formatRelativeTime,
  statusColor,
} from '../../lib/agent-format';

export function StatusBadge({ status }: { status: string }) {
  const color = statusColor(status);
  return (
    <span
      className="px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: color + '20', color }}
    >
      {status.replace('_', ' ')}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const color = statusColor(status);
  return (
    <span
      className="w-2 h-2 rounded-full inline-block flex-shrink-0"
      style={{ background: color }}
      title={status}
    />
  );
}

export function OverflowMenu({
  agentId,
  onDelete,
}: {
  agentId: string;
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="p-1 rounded cursor-pointer"
        style={{ color: 'var(--color-text-tertiary)' }}
        title="More actions"
      >
        <MoreHorizontal size={14} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-6 z-20 rounded-lg py-1 min-w-[120px]"
          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', boxShadow: '0 4px 12px rgba(0,0,0,0.15)' }}
        >
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(agentId);
              setOpen(false);
            }}
            className="w-full text-left px-3 py-1.5 text-xs cursor-pointer flex items-center gap-2"
            style={{ color: 'var(--color-error)' }}
          >
            <Trash2 size={12} /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent List Card
// ---------------------------------------------------------------------------

export function AgentCard({
  agent,
  onClick,
  onPause,
  onResume,
  onRun,
  onRecover,
  onDelete,
  onChat,
  onEdit,
}: {
  agent: ManagedAgent;
  onClick: () => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onRun: (id: string) => void;
  onRecover: (id: string) => void;
  onDelete: (id: string) => void;
  onChat: (id: string) => void;
  onEdit: (id: string) => void;
}) {
  const canPause = agent.status === 'running' || agent.status === 'idle';
  const canResume = agent.status === 'paused';
  const canRecover = agent.status === 'error' || agent.status === 'stalled' || agent.status === 'needs_attention';

  return (
    // A div with onClick and nothing else is invisible to the keyboard: no
    // focus, no Enter, no announcement that it does anything. It cannot simply
    // become a <button> because it contains its own pause/edit buttons and
    // nesting those is invalid, so it takes the ARIA equivalent instead.
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        // Space scrolls the page by default, which is wrong for a control.
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
      className="p-4 rounded-lg cursor-pointer transition-colors bg-bg-secondary
        border border-border hover:border-accent"
    >
      {/* Row 1: Name + status dot */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Bot size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span className="font-medium text-sm truncate" style={{ color: 'var(--color-text)' }}>
            {agent.name}
          </span>
        </div>
        <StatusDot status={agent.status} />
      </div>

      {/* Row 2: Schedule + last run */}
      <div className="text-xs mb-2 flex items-center gap-3" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>{formatAgentSchedule(agent)}</span>
        <span>·</span>
        <span>Last run: {formatRelativeTime(agent.last_run_at)}</span>
      </div>

      {/* Row 3: Stats */}
      <div className="flex items-center gap-4 mb-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        <span className="flex items-center gap-1">
          <Activity size={11} />
          {agent.total_runs ?? 0} runs
        </span>
        <span className="flex items-center gap-1">
          <DollarSign size={11} />
          {formatCost(agent.total_cost)}
        </span>
      </div>

      {/* Budget progress bar */}
      {(agent.config?.max_cost as number) > 0 && (
        <div className="mb-3">
          <div className="flex justify-between text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
            <span>Budget</span>
            <span>
              {formatCost(agent.total_cost)} / ${(agent.config?.max_cost as number).toFixed(0)}
            </span>
          </div>
          <div className="w-full rounded-full h-1.5" style={{ background: 'var(--color-bg)' }}>
            <div
              className="h-1.5 rounded-full transition-all"
              style={{
                width: `${Math.min(100, ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) * 100)}%`,
                background:
                  ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) > 0.9
                    ? 'var(--color-error)'
                    : ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) > 0.75
                      ? 'var(--color-warning)'
                      : 'var(--color-success)',
              }}
            />
          </div>
        </div>
      )}

      {/* Row 4: Actions */}
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={(e) => { e.stopPropagation(); onChat(agent.id); }}
          className="p-1.5 rounded cursor-pointer transition-colors"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
          title="Chat with agent"
        >
          <MessageSquare size={13} />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onEdit(agent.id); }}
          className="p-1.5 rounded cursor-pointer transition-colors"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
          title="Edit agent"
        >
          <Pencil size={13} />
        </button>
        <button
          onClick={() => onRun(agent.id)}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer transition-colors"
          style={{ background: 'var(--color-accent)' + '15', color: 'var(--color-accent)' }}
          title="Run now"
        >
          <Zap size={11} /> Run Now
        </button>
        {canPause && (
          <button
            onClick={() => onPause(agent.id)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            title="Pause"
          >
            <Pause size={13} />
          </button>
        )}
        {canResume && (
          <button
            onClick={() => onResume(agent.id)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-success)' }}
            title="Resume"
          >
            <Play size={13} />
          </button>
        )}
        {canRecover && (
          <button
            onClick={() => onRecover(agent.id)}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer"
            style={{ background: 'var(--color-error)20', color: 'var(--color-error)' }}
            title="Recover agent"
          >
            <AlertTriangle size={11} /> Recover
          </button>
        )}
        <div className="ml-auto">
          <OverflowMenu agentId={agent.id} onDelete={onDelete} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail view — Configuration grid with editable model
// ---------------------------------------------------------------------------

