/**
 * Turning an agent's raw fields into something a person reads.
 *
 * Extracted from AgentsPage.tsx, where it sat among four thousand lines of
 * JSX. None of it needs React, all of it has branches worth checking — a cron
 * expression rendered as "Daily at 9:00 AM" is obviously right until the hour
 * is midnight.
 */

import type { ManagedAgent } from './api';
import { getAgentSchedule } from './agent-schedule';

export type AgentStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'error'
  | 'archived'
  | 'needs_attention'
  | 'budget_exceeded'
  | 'stalled';

export const STATUS_COLOR: Record<AgentStatus, string> = {
  idle: 'var(--color-success)',
  running: 'var(--color-accent)',
  paused: 'var(--color-text-tertiary)',
  error: 'var(--color-error)',
  archived: 'var(--color-text-tertiary)',
  needs_attention: 'var(--color-warning)',
  budget_exceeded: 'var(--color-warning)',
  stalled: 'var(--color-warning)',
};

export function statusColor(s: string): string {
  return STATUS_COLOR[s as AgentStatus] || 'var(--color-text-tertiary)';
}

export function formatCost(cost?: number): string {
  if (cost === undefined || cost === null) return '—';
  return `$${cost.toFixed(4)}`;
}

export function formatRelativeTime(ts?: number | null): string {
  if (!ts) return 'Never';
  const diff = Date.now() - ts * 1000;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function formatSchedule(type?: string, value?: string): string {
  if (!type || type === 'manual') return 'Manual';
  if (type === 'cron' && value) {
    // Try to display human-readable for common cron patterns
    const parts = value.trim().split(/\s+/);
    if (parts.length === 5) {
      const [min, hour, , , dow] = parts;
      const hourNum = parseInt(hour, 10);
      const formatHour = (h: number) => {
        if (h === 0) return '12:00 AM';
        if (h < 12) return `${h}:00 AM`;
        if (h === 12) return '12:00 PM';
        return `${h - 12}:00 PM`;
      };
      // Daily pattern: 0 H * * *
      if (min === '0' && !isNaN(hourNum) && parts[2] === '*' && parts[3] === '*' && dow === '*') {
        return `Daily at ${formatHour(hourNum)}`;
      }
      // Weekly pattern: 0 H * * days
      if (min === '0' && !isNaN(hourNum) && parts[2] === '*' && parts[3] === '*' && dow !== '*') {
        const DAY_NAMES: Record<string, string> = { '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun' };
        const dayList = dow.split(',').map(d => DAY_NAMES[d] || d).join(', ');
        return `Weekly on ${dayList} at ${formatHour(hourNum)}`;
      }
    }
    return `Cron: ${value}`;
  }
  if (type === 'cron') return 'Cron';
  if (type === 'interval' && value) {
    const total = parseInt(value);
    if (!isNaN(total) && total > 0) {
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      const parts: string[] = [];
      if (h > 0) parts.push(`${h}h`);
      if (m > 0) parts.push(`${m}m`);
      if (s > 0) parts.push(`${s}s`);
      return `Every ${parts.join(' ') || '0s'}`;
    }
    return `Every ${value}`;
  }
  return type || 'Manual';
}

export function formatAgentSchedule(agent: ManagedAgent): string {
  const { type, value } = getAgentSchedule(agent);
  return formatSchedule(type, value);
}

// ---------------------------------------------------------------------------
// Launch Wizard
// ---------------------------------------------------------------------------

