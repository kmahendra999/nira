import { useEffect, useRef } from 'react';
import { getApiKey, getBase } from './api';

export interface AgentEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
  /** Monotonic cursor, used to resume after a dropped connection. */
  seq?: number;
  /** Present on `replay_start`: whether the backlog is complete. */
  gap?: boolean;
  /** Present on `replay_start`: how many events are about to be replayed. */
  count?: number;
}

/** Control frames the server sends around a replay; not agent activity. */
export const REPLAY_START = 'replay_start';
export const REPLAY_END = 'replay_end';

const WS_AUTH_PROTOCOL = 'nira.auth.v1';
const WS_KEY_PROTOCOL_PREFIX = 'nira.key.b64url.';

function utf8ToBase64Url(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

export function buildWsUrl(agentId?: string, since?: number): string {
  const base = getBase();
  const url = new URL('/v1/agents/events', base || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';

  if (agentId) url.searchParams.set('agent_id', agentId);
  // Only on a reconnect. A first connection wants what happens next, not the
  // server's whole backlog.
  if (since !== undefined) url.searchParams.set('since', String(since));

  return url.toString();
}

/**
 * WebSocket auth protocols carrying the API key, if configured. The key is
 * UTF-8/base64url encoded so every value satisfies browser subprotocol syntax.
 * This keeps the key out of the request URL and request-line access logs; the
 * encoding is transport-safe, not encryption.
 */
export function buildWsProtocols(): string[] | undefined {
  const apiKey = getApiKey();
  return apiKey
    ? [
        WS_AUTH_PROTOCOL,
        `${WS_KEY_PROTOCOL_PREFIX}${utf8ToBase64Url(apiKey)}`,
      ]
    : undefined;
}

/**
 * Subscribe to agent events over WebSocket.
 *
 * Auto-reconnects with backoff, and resumes from the last event seen so a
 * dropped connection does not leave a hole in the trace. That matters most
 * on a phone, where the socket drops on every cell handover and screen lock;
 * without a cursor each reconnect silently lost whatever happened in the gap
 * and progress appeared to stall.
 */
export function useAgentEvents(
  agentId: string | undefined,
  onEvent: (event: AgentEvent) => void,
  eventTypes?: readonly string[],
): void {
  // An absent agentId means "no agent selected, do not subscribe" for this
  // hook's callers. useAllAgentEvents is the way to watch every agent.
  useAgentEventStream(agentId, Boolean(agentId), onEvent, eventTypes);
}

/**
 * Subscribe to events from every agent, unfiltered.
 *
 * For anything that reflects "is Nira doing something right now" rather than
 * one agent's trace. Polling for that answers late by however long the
 * interval is, which on the most visible activity indicator in the app is the
 * difference between live and decorative.
 */
export function useAllAgentEvents(
  onEvent: (event: AgentEvent) => void,
  eventTypes?: readonly string[],
  enabled = true,
): void {
  useAgentEventStream(undefined, enabled, onEvent, eventTypes);
}

function useAgentEventStream(
  agentId: string | undefined,
  enabled: boolean,
  onEvent: (event: AgentEvent) => void,
  eventTypes?: readonly string[],
): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const typesRef = useRef(eventTypes);
  typesRef.current = eventTypes;

  useEffect(() => {
    if (!enabled) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let lastSeq: number | undefined;

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(buildWsUrl(agentId, lastSeq), buildWsProtocols());
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        retry = 0;
      };
      ws.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data) as AgentEvent;
          // Advance the cursor before filtering: an event this consumer does
          // not care about still moves the stream on, and skipping it would
          // make us ask for it again on every future reconnect.
          if (typeof payload.seq === 'number') lastSeq = payload.seq;

          const allowed = typesRef.current;
          // Replay control frames are always delivered, whatever the filter:
          // they are how a consumer learns the backlog was incomplete.
          const isControl =
            payload.type === REPLAY_START || payload.type === REPLAY_END;
          if (!isControl && allowed && !allowed.includes(payload.type)) return;
          onEventRef.current(payload);
        } catch {
          // ignore malformed payload
        }
      };
      ws.onclose = () => {
        if (!closed) schedule();
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    const schedule = () => {
      if (closed) return;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(retry, 5));
      retry += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [agentId, enabled]);
}
