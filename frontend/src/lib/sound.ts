/**
 * The console's voice.
 *
 * Synthesised, not sampled. Five oscillators and a filter weigh nothing in
 * the bundle, tune by editing a number, and — the actual reason — a recorded
 * blip always sounds like a recording of somebody else's machine. An
 * instrument that makes its own tones sounds like the instrument.
 *
 * Three rules this follows, because UI audio is easy to get wrong:
 *
 *   1. Nothing plays until the reader has interacted with the page. Browsers
 *      enforce this for autoplay anyway; doing it deliberately means the
 *      AudioContext is only ever created on a real gesture, so a tab that is
 *      opened and never touched allocates no audio hardware.
 *   2. Everything is short and quiet. These are acknowledgements, not
 *      notifications — under 120ms, peaking around -24dBFS.
 *   3. It can always be turned off, in one click, and that choice persists.
 *
 * Sound is on by default because it is the point of the feature, and off is
 * one obvious control away.
 */

export type Cue =
  /** A control was pressed. */
  | 'tap'
  /** A value changed / data arrived. */
  | 'blip'
  /** A panel opened, a view swept in. */
  | 'sweep'
  /** Something completed successfully. */
  | 'confirm'
  /** Something needs attention. */
  | 'alert'
  /** Pointer crossed an interactive edge. Deliberately almost inaudible. */
  | 'hover';

const STORAGE_KEY = 'nira-sound';

/** Served from frontend/public, so it lands beside index.html in the build. */
const SAMPLE_URL = '/sfx/console.wav';

interface Voice {
  /** Start frequency in Hz. */
  from: number;
  /** End frequency; a glide reads as movement where a flat tone reads as a beep. */
  to: number;
  duration: number;
  type: OscillatorType;
  /** Peak gain. Everything here is far below 1 on purpose. */
  gain: number;
}

/**
 * How the one sample is shaped per cue.
 *
 * A single 0.36s recording covers all six by varying playback rate and gain:
 * rate shortens *and* brightens together, which is exactly how these cues
 * differ from each other — a hover wants to be quick and thin, an alert slow
 * and heavy. Six separate files would be six things to keep in tune.
 */
const SAMPLED: Record<Cue, { rate: number; gain: number }> = {
  // Fast and faint. This fires on every pointer crossing, so it has to sit
  // just at the edge of noticing.
  hover: { rate: 2.6, gain: 0.1 },
  tap: { rate: 1.6, gain: 0.22 },
  blip: { rate: 2.0, gain: 0.16 },
  sweep: { rate: 0.85, gain: 0.14 },
  // Full length and unhurried: the only cue that means "that worked".
  confirm: { rate: 1.0, gain: 0.26 },
  // Slowest, so it reads as lower and more serious without being louder.
  alert: { rate: 0.7, gain: 0.26 },
};

const VOICES: Record<Cue, Voice> = {
  // A short downward tick: the sound of a switch, not a chime.
  tap: { from: 880, to: 520, duration: 0.05, type: 'triangle', gain: 0.05 },
  // Upward, so arriving data feels like arriving rather than departing.
  blip: { from: 1180, to: 1560, duration: 0.045, type: 'sine', gain: 0.035 },
  // Longer glide for a panel or view transition.
  sweep: { from: 320, to: 900, duration: 0.14, type: 'sawtooth', gain: 0.03 },
  // A rising interval — the only one that reads as "good".
  confirm: { from: 660, to: 990, duration: 0.11, type: 'sine', gain: 0.05 },
  // Falling and harsher. Not a klaxon; this still has to be usable at 2am.
  alert: { from: 540, to: 300, duration: 0.16, type: 'square', gain: 0.045 },
  // At the threshold of noticing. Any louder and moving the mouse is torture.
  hover: { from: 2100, to: 2100, duration: 0.018, type: 'sine', gain: 0.012 },
};

function readStored(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === null ? true : raw === 'on';
  } catch {
    // Private windows throw on access. Default to on rather than silently
    // disabling a feature because storage is unavailable.
    return true;
  }
}

class Console {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private sample: AudioBuffer | null = null;
  private sampleFailed = false;
  private on = readStored();
  private unlocked = false;
  private listeners = new Set<(on: boolean) => void>();
  /** Coalesces hover cues so sweeping a list is one tick, not forty. */
  private lastHover = 0;

  get enabled(): boolean {
    return this.on;
  }

  setEnabled(next: boolean): void {
    this.on = next;
    try {
      localStorage.setItem(STORAGE_KEY, next ? 'on' : 'off');
    } catch {
      /* the setting is still live for this session */
    }
    if (!next) this.ctx?.suspend();
    else void this.ctx?.resume();
    this.listeners.forEach((fn) => fn(next));
  }

  subscribe(fn: (on: boolean) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Call from a real user gesture. Idempotent. */
  unlock(): void {
    if (this.unlocked) return;
    this.unlocked = true;
    void this.context();
    void this.loadSample();
  }

  /**
   * Fetch and decode the console sample once.
   *
   * Failure is not an error: `play` falls back to the synthesised voices, so
   * a missing or undecodable file costs the character of the sound and
   * nothing else. Decoding here rather than on first use means the first
   * hover is not the one that pays for it.
   */
  private async loadSample(): Promise<void> {
    if (this.sample || this.sampleFailed) return;
    const ctx = this.context();
    if (!ctx) return;
    try {
      const res = await fetch(SAMPLE_URL);
      if (!res.ok) throw new Error(String(res.status));
      this.sample = await ctx.decodeAudioData(await res.arrayBuffer());
    } catch {
      this.sampleFailed = true;
    }
  }

  private context(): AudioContext | null {
    if (this.ctx) return this.ctx;
    const Ctor: typeof AudioContext | undefined =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctor) return null;
    try {
      this.ctx = new Ctor();
      this.master = this.ctx.createGain();
      // A ceiling the individual cues sit under, so no combination of them
      // can add up to something startling.
      this.master.gain.value = 0.6;
      this.master.connect(this.ctx.destination);
    } catch {
      return null;
    }
    return this.ctx;
  }

  play(cue: Cue): void {
    if (!this.on || !this.unlocked) return;

    if (cue === 'hover') {
      const now = Date.now();
      if (now - this.lastHover < 90) return;
      this.lastHover = now;
    }

    const ctx = this.context();
    if (!ctx || !this.master) return;
    if (ctx.state === 'suspended') void ctx.resume();

    const t = ctx.currentTime;

    if (this.sample) {
      const shape = SAMPLED[cue];
      const src = ctx.createBufferSource();
      src.buffer = this.sample;
      src.playbackRate.value = shape.rate;
      const gain = ctx.createGain();
      gain.gain.value = shape.gain;
      src.connect(gain).connect(this.master);
      src.start(t);
      src.onended = () => {
        src.disconnect();
        gain.disconnect();
      };
      return;
    }

    // No sample: the synthesised voices, which is also what the tests drive.
    const voice = VOICES[cue];
    const osc = ctx.createOscillator();
    osc.type = voice.type;
    osc.frequency.setValueAtTime(voice.from, t);
    if (voice.to !== voice.from) {
      osc.frequency.exponentialRampToValueAtTime(voice.to, t + voice.duration);
    }

    // A lowpass takes the edge off the square and sawtooth voices; without it
    // `alert` is genuinely unpleasant through laptop speakers.
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 2600;

    const gain = ctx.createGain();
    // Attack over 8ms rather than instantly: a hard start is a click, and a
    // click is what a broken audio path sounds like.
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(voice.gain, t + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + voice.duration);

    osc.connect(filter).connect(gain).connect(this.master);
    osc.start(t);
    osc.stop(t + voice.duration + 0.02);
    // Let the graph be collected rather than leaking a node per cue.
    osc.onended = () => {
      osc.disconnect();
      filter.disconnect();
      gain.disconnect();
    };
  }
}

export const sound = new Console();

/** Convenience for JSX: `onClick={cue('tap', handler)}`. */
export function cue<T extends unknown[]>(
  name: Cue,
  then?: (...args: T) => void,
): (...args: T) => void {
  return (...args: T) => {
    sound.play(name);
    then?.(...args);
  };
}
