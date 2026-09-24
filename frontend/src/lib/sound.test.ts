import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The rules that keep UI audio from being hostile.
 *
 * Every one of these is a way sound goes wrong in an app: it plays before
 * anyone has touched the page, it ignores the off switch, it forgets the off
 * switch on reload, or it fires forty times while a pointer crosses a list.
 */

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(k: string) { return this.store.has(k) ? (this.store.get(k) as string) : null; }
  setItem(k: string, v: string) { this.store.set(k, String(v)); }
  removeItem(k: string) { this.store.delete(k); }
  clear() { this.store.clear(); }
}

/** Counts oscillators started, which is the only observable "it made a sound". */
function stubAudio() {
  const started: number[] = [];
  const node = () => ({ connect: vi.fn(function (this: unknown, n: unknown) { return n; }), disconnect: vi.fn() });
  class FakeContext {
    state = 'running';
    currentTime = 0;
    destination = {};
    resume = vi.fn();
    suspend = vi.fn();
    createGain() { return { ...node(), gain: { value: 0, setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() } }; }
    createBiquadFilter() { return { ...node(), type: '', frequency: { value: 0 } }; }
    createOscillator() {
      return {
        ...node(),
        type: '' as OscillatorType,
        frequency: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
        start: (t: number) => started.push(t),
        stop: vi.fn(),
        onended: null,
      };
    }
  }
  (globalThis as unknown as { window: Record<string, unknown> }).window = {
    AudioContext: FakeContext as unknown as typeof AudioContext,
  };
  return started;
}

let started: number[];

beforeEach(() => {
  vi.resetModules();
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage = new MemoryStorage();
  started = stubAudio();
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

async function fresh() {
  return await import('./sound');
}

describe('before any user gesture', () => {
  it('plays nothing', async () => {
    const { sound } = await fresh();

    sound.play('tap');
    sound.play('alert');

    // Browsers block autoplay anyway; doing it deliberately means no
    // AudioContext is allocated for a tab nobody touched.
    expect(started).toHaveLength(0);
  });

  it('plays once unlocked', async () => {
    const { sound } = await fresh();

    sound.unlock();
    sound.play('tap');

    expect(started).toHaveLength(1);
  });
});

describe('the off switch', () => {
  it('is on by default', async () => {
    const { sound } = await fresh();
    expect(sound.enabled).toBe(true);
  });

  it('silences everything when off', async () => {
    const { sound } = await fresh();
    sound.unlock();

    sound.setEnabled(false);
    sound.play('tap');
    sound.play('confirm');

    expect(started).toHaveLength(0);
  });

  it('persists across a reload', async () => {
    const first = await fresh();
    first.sound.setEnabled(false);

    // A new module instance, same storage — what a page reload looks like.
    vi.resetModules();
    const second = await import('./sound');

    expect(second.sound.enabled).toBe(false);
  });

  it('notifies subscribers so a toggle can reflect it', async () => {
    const { sound } = await fresh();
    const seen: boolean[] = [];
    const stop = sound.subscribe((on) => seen.push(on));

    sound.setEnabled(false);
    sound.setEnabled(true);
    stop();
    sound.setEnabled(false);

    expect(seen).toEqual([false, true]);
  });

  it('survives storage that throws', async () => {
    // Private windows throw on access. Losing the setting is acceptable;
    // crashing on a button press is not.
    (globalThis as unknown as { localStorage: unknown }).localStorage = {
      getItem() { throw new Error('denied'); },
      setItem() { throw new Error('denied'); },
    };
    const { sound } = await fresh();

    expect(sound.enabled).toBe(true);
    expect(() => sound.setEnabled(false)).not.toThrow();
    expect(sound.enabled).toBe(false);
  });
});

describe('hover', () => {
  it('coalesces, so crossing a list is not a machine-gun', async () => {
    const { sound } = await fresh();
    sound.unlock();

    for (let i = 0; i < 40; i += 1) sound.play('hover');

    expect(started).toHaveLength(1);
  });

  it('does not throttle the deliberate cues', async () => {
    const { sound } = await fresh();
    sound.unlock();

    sound.play('tap');
    sound.play('tap');
    sound.play('tap');

    // A person clicking three times means it three times.
    expect(started).toHaveLength(3);
  });
});

describe('cue()', () => {
  it('plays and still calls the handler', async () => {
    const { sound, cue } = await fresh();
    sound.unlock();
    const handler = vi.fn();

    cue('tap', handler)('arg');

    expect(started).toHaveLength(1);
    expect(handler).toHaveBeenCalledWith('arg');
  });

  it('works with no handler', async () => {
    const { sound, cue } = await fresh();
    sound.unlock();

    expect(() => cue('blip')()).not.toThrow();
    expect(started).toHaveLength(1);
  });
});
