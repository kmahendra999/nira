import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  ChatAnnouncer,
  announcerReducer,
  initialAnnouncerState,
  type AnnouncerState,
  type StreamSnapshot,
} from './ChatAnnouncer';

const idle: StreamSnapshot = { streaming: false, phase: '', content: '' };

/** Feed a sequence of snapshots and collect everything that got announced. */
function announcements(steps: StreamSnapshot[]): string[] {
  let state = initialAnnouncerState;
  const said: string[] = [];
  for (const step of steps) {
    const next = announcerReducer(state, step);
    if (next.message !== state.message && next.message) said.push(next.message);
    state = next;
  }
  return said;
}

describe('announcerReducer', () => {
  it('says nothing while nothing is happening', () => {
    expect(announcements([idle, idle, idle])).toEqual([]);
  });

  it('announces that a reply has started', () => {
    expect(
      announcements([idle, { streaming: true, phase: '', content: '' }]),
    ).toEqual(['Nira is thinking']);
  });

  it('does not announce every token', () => {
    // The whole reason this is a status region and not a live transcript. One
    // message per token would interrupt and restart the announcement on each
    // one, and the listener hears a stutter instead of a sentence.
    const typing = ['H', 'He', 'Hel', 'Hell', 'Hello'].map((content) => ({
      streaming: true,
      phase: '',
      content,
    }));
    // Five tokens, one announcement. The count is the assertion.
    expect(
      announcements([idle, { streaming: true, phase: '', content: '' }, ...typing]),
    ).toEqual(['Nira is thinking', 'Nira is replying']);
  });

  it('announces each step of a long run', () => {
    // Tool changes are slow and meaningful — the thing a sighted user watches
    // the activity line for.
    expect(
      announcements([
        idle,
        { streaming: true, phase: '', content: '' },
        { streaming: true, phase: 'Searching the web', content: '' },
        { streaming: true, phase: 'Searching the web', content: '' },
        { streaming: true, phase: 'Reading results', content: '' },
      ]),
    ).toEqual([
      'Nira is thinking',
      'Searching the web',
      'Reading results',
    ]);
  });

  it('announces completion', () => {
    expect(
      announcements([
        idle,
        { streaming: true, phase: '', content: '' },
        { streaming: true, phase: '', content: 'Hello' },
        idle,
      ]),
    ).toEqual(['Nira is thinking', 'Nira is replying', 'Reply complete']);
  });

  it('distinguishes an empty reply from a finished one', () => {
    // Silence here would be indistinguishable from the request still running.
    expect(
      announcements([idle, { streaming: true, phase: '', content: '' }, idle]),
    ).toEqual(['Nira is thinking', 'Nira finished without a reply']);
  });

  it('starts fresh on the next reply', () => {
    expect(
      announcements([
        idle,
        { streaming: true, phase: '', content: '' },
        { streaming: true, phase: '', content: 'a' },
        idle,
        { streaming: true, phase: '', content: '' },
      ]),
    ).toEqual([
      'Nira is thinking',
      'Nira is replying',
      'Reply complete',
      'Nira is thinking',
    ]);
  });

  it('notices a reply that arrives in the same tick it starts', () => {
    // React can batch the streaming flag and the first token into one render.
    // Treating that as an empty start would report a real answer as "finished
    // without a reply".
    expect(
      announcements([
        idle,
        { streaming: true, phase: '', content: 'Hello' },
        idle,
      ]),
    ).toEqual(['Nira is replying', 'Reply complete']);
  });

  it('never puts the reply text into the announcement', () => {
    // It is already on the page, and an announcement cannot be paused or
    // re-read — hearing the whole answer read over is worse than not.
    const state: AnnouncerState = {
      streaming: true,
      sawContent: false,
      message: '',
    };
    const next = announcerReducer(state, {
      streaming: true,
      phase: '',
      content: 'a long answer about quantum mechanics',
    });
    expect(next.message).not.toContain('quantum');
  });
});

describe('ChatAnnouncer', () => {
  it('renders a polite status region that is not shown on screen', () => {
    const html = renderToStaticMarkup(
      <ChatAnnouncer streaming={false} phase="" content="" />,
    );
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
    // atomic, so the whole message is read rather than only the changed words.
    expect(html).toContain('aria-atomic="true"');
    expect(html).toContain('sr-only');
  });
});
