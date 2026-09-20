/**
 * What an agent has learned, and whether learning is on for it.
 */

import { useEffect, useState } from 'react';
import { fetchLearningLog, triggerLearning } from '../../lib/api';
import type { LearningLogEntry } from '../../lib/api';
import { RefreshCw } from 'lucide-react';
import { formatRelativeTime } from '../../lib/agent-format';

export function LearningTab({ agentId, learningEnabled }: { agentId: string; learningEnabled: boolean }) {
  const [logs, setLogs] = useState<LearningLogEntry[]>([]);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    fetchLearningLog(agentId).then(setLogs).catch(() => {});
  }, [agentId]);

  async function handleTrigger() {
    setTriggering(true);
    try {
      await triggerLearning(agentId);
      // Refresh after a short delay
      setTimeout(() => fetchLearningLog(agentId).then(setLogs).catch(() => {}), 1000);
    } catch {
      // ignore
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>Learning</span>
          <span
            className="text-xs px-2 py-0.5 rounded-full"
            style={{
              background: learningEnabled ? 'var(--color-success)20' : 'var(--color-bg-secondary)',
              color: learningEnabled ? 'var(--color-success)' : 'var(--color-text-tertiary)',
            }}
          >
            {learningEnabled ? 'Enabled' : 'Disabled'}
          </span>
        </div>
        <button
          onClick={handleTrigger}
          disabled={triggering}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer font-medium"
          style={{
            background: 'var(--color-accent)',
            color: 'var(--color-on-accent)',
            opacity: triggering ? 0.6 : 1,
          }}
        >
          <RefreshCw size={12} className={triggering ? 'animate-spin' : ''} />
          Run Learning
        </button>
      </div>
      {logs.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No learning events yet. Run the agent or trigger learning manually.
        </div>
      ) : (
        <div className="space-y-2">
          {logs.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg p-3 text-sm"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className="text-xs px-2 py-0.5 rounded"
                  style={{ background: 'var(--color-accent)' + '20', color: 'var(--color-accent)' }}
                >
                  {entry.event_type}
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {formatRelativeTime(entry.created_at)}
                </span>
              </div>
              {entry.description && (
                <p style={{ color: 'var(--color-text-secondary)' }}>{entry.description}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Logs tab component
// ---------------------------------------------------------------------------

