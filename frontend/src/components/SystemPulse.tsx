import { useCallback, useEffect, useState } from 'react';
import { useAppStore } from '../lib/store';
import { fetchManagedAgents } from '../lib/api';
import { useAllAgentEvents, type AgentEvent } from '../lib/useAgentEvents';

type PulseState = 'idle' | 'inferencing' | 'agent-active' | 'hidden';

const PULSE_CONFIG: Record<Exclude<PulseState, 'hidden'>, { color: string; animation: string }> = {
  idle: {
    color: 'color-mix(in srgb, var(--color-accent) 22%, transparent)',
    animation: 'none',
  },
  inferencing: {
    color: 'var(--color-accent)',
    animation: 'pulse-glow 2s ease-in-out infinite',
  },
  'agent-active': {
    color: 'var(--color-accent-purple)',
    animation: 'pulse-travel 3s linear infinite',
  },
};

export function SystemPulse({ apiReachable }: { apiReachable: boolean | null }) {
  const isStreaming = useAppStore((s) => s.streamState.isStreaming);
  const [hasRunningAgent, setHasRunningAgent] = useState(false);

  // One fetch to learn the current state — an agent may already have been
  // running before this mounted, and the event stream only reports changes.
  useEffect(() => {
    if (apiReachable === false) return;
    fetchManagedAgents()
      .then((agents) => setHasRunningAgent(agents.some((a) => a.status === 'running')))
      .catch(() => {});
  }, [apiReachable]);

  // After that, follow the events. This used to poll every 30 seconds, so the
  // most visible "something is happening" indicator in the app could be up to
  // half a minute behind the thing it indicates — long enough for a short
  // agent run to start and finish without the bar ever moving.
  const onEvent = useCallback((event: AgentEvent) => {
    if (event.type === 'agent_tick_start') {
      setHasRunningAgent(true);
      return;
    }
    if (event.type === 'agent_tick_end' || event.type === 'agent_tick_error') {
      // Re-read rather than assume idle: another agent may still be working,
      // and this stream is unfiltered.
      fetchManagedAgents()
        .then((agents) => setHasRunningAgent(agents.some((a) => a.status === 'running')))
        .catch(() => setHasRunningAgent(false));
    }
  }, []);

  useAllAgentEvents(
    onEvent,
    ['agent_tick_start', 'agent_tick_end', 'agent_tick_error'],
    apiReachable !== false,
  );

  if (apiReachable === false) return null;

  // Priority: agent-active > inferencing > idle
  let state: PulseState = 'idle';
  if (isStreaming) state = 'inferencing';
  if (hasRunningAgent) state = 'agent-active';

  const config = PULSE_CONFIG[state];
  const isTravel = state === 'agent-active';

  return (
    <div
      className="fixed top-0 left-0 right-0 h-[3px] z-50"
      style={{
        background: isTravel
          ? `linear-gradient(90deg, transparent, ${config.color}, transparent)`
          : `linear-gradient(90deg, transparent 5%, ${config.color} 30%, ${config.color} 70%, transparent 95%)`,
        backgroundSize: isTravel ? '200% 100%' : '100% 100%',
        animation: config.animation,
      }}
    />
  );
}
