import { useEffect, useRef, useState } from 'react';

/** What the announcer has already said, so it does not repeat itself. */
export interface AnnouncerState {
  streaming: boolean;
  sawContent: boolean;
  message: string;
}

export const initialAnnouncerState: AnnouncerState = {
  streaming: false,
  sawContent: false,
  message: '',
};

export interface StreamSnapshot {
  streaming: boolean;
  /** What the backend says it is doing right now, e.g. a tool name. */
  phase: string;
  /** The reply so far. Only its emptiness matters here, never its text. */
  content: string;
}

/**
 * Decide what, if anything, to announce for a change in the stream.
 *
 * Pure so the decision can be tested without a DOM — the component below is
 * only the wiring.
 */
export function announcerReducer(
  state: AnnouncerState,
  next: StreamSnapshot,
): AnnouncerState {
  if (next.streaming && !state.streaming) {
    // Take the content into account on the very first snapshot too. React can
    // batch the flag and the first token into one render, and a reducer that
    // assumed an empty start would then never notice the reply — announcing a
    // real answer as "finished without a reply", which is worse than silence.
    return {
      streaming: true,
      sawContent: next.content !== '',
      message: next.content ? 'Nira is replying' : 'Nira is thinking',
    };
  }

  if (!next.streaming && state.streaming) {
    // "Complete" rather than the reply itself. Reading the whole answer here
    // would duplicate what is already on the page, and an announcement cannot
    // be paused or re-read.
    return {
      streaming: false,
      sawContent: false,
      message: state.sawContent ? 'Reply complete' : 'Nira finished without a reply',
    };
  }

  if (!next.streaming) return { ...state, streaming: false };

  if (next.content && !state.sawContent) {
    return { ...state, streaming: true, sawContent: true, message: 'Nira is replying' };
  }

  // Phase changes are the slow, meaningful steps of a long run — the part a
  // sighted user watches the activity line for. Content changes are not: a
  // message per token would interrupt and restart the announcement on every
  // one, and the listener would hear a stutter rather than a sentence.
  if (next.phase && next.phase !== state.message) {
    return { ...state, streaming: true, message: next.phase };
  }

  return state;
}

/**
 * Speaks the state of a reply to assistive technology.
 *
 * A streaming reply is a purely visual event: text appears and a screen reader
 * is told nothing at all. The obvious fix — marking the transcript itself as a
 * live region — is worse than the silence, for the reason in
 * [announcerReducer]. So this announces the state instead, and leaves the
 * reply where it is, to be read at the listener's own pace.
 */
export function ChatAnnouncer(snapshot: StreamSnapshot) {
  const [state, setState] = useState(initialAnnouncerState);
  const latest = useRef(state);
  latest.current = state;

  useEffect(() => {
    const next = announcerReducer(latest.current, snapshot);
    if (next !== latest.current) setState(next);
  }, [snapshot.streaming, snapshot.phase, snapshot.content]);

  return (
    <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {state.message}
    </div>
  );
}
