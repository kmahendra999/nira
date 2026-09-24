import { sound } from './sound';

/**
 * One listener instead of six hundred handlers.
 *
 * Wiring a cue into every button would mean touching every component that
 * has one, and then remembering to do it in every component written
 * afterwards — which is the failure mode that left this codebase with 68
 * hand-written `onMouseEnter` handlers assigning to `e.currentTarget.style`.
 * Delegation puts it in one place and covers things that do not exist yet.
 *
 * Interactive is decided by role, not by looks: anything focusable and
 * clickable gets a cue, anything inert does not. `[data-quiet]` opts an
 * element out — for controls that fire continuously, like a slider, where a
 * tone per step would be unbearable.
 */

const INTERACTIVE = [
  'button',
  '[role="button"]',
  'a[href]',
  'summary',
  '[role="tab"]',
  '[role="menuitem"]',
  '[role="option"]',
  'input[type="checkbox"]',
  'input[type="radio"]',
].join(',');

function target(event: Event): Element | null {
  const node = event.target;
  if (!(node instanceof Element)) return null;
  const hit = node.closest(INTERACTIVE);
  if (!hit) return null;
  // Disabled controls do nothing, so they should sound like nothing.
  if (hit.hasAttribute('disabled') || hit.getAttribute('aria-disabled') === 'true') {
    return null;
  }
  if (hit.closest('[data-quiet]')) return null;
  return hit;
}

export function installSoundDelegate(): () => void {
  // pointerover rather than mouseover: it also covers pen, and it does not
  // fire on touch, where a hover cue would play on every tap alongside the
  // tap cue.
  const onOver = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return;
    if (target(event)) sound.play('hover');
  };

  const onDown = (event: PointerEvent) => {
    // On pointerdown, not click: the sound should land with the press, the
    // way a real switch does. On click it arrives after the release and
    // feels detached from the finger.
    if (target(event)) sound.play('tap');
  };

  // Keyboard activation deserves the same acknowledgement as a click; without
  // this, navigating by keyboard is silent while the mouse is not.
  const onKey = (event: KeyboardEvent) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    if (event.repeat) return;
    const node = document.activeElement;
    if (node instanceof Element && node.matches(INTERACTIVE)) sound.play('tap');
  };

  document.addEventListener('pointerover', onOver, { passive: true });
  document.addEventListener('pointerdown', onDown, { passive: true });
  document.addEventListener('keydown', onKey, { passive: true });

  return () => {
    document.removeEventListener('pointerover', onOver);
    document.removeEventListener('pointerdown', onDown);
    document.removeEventListener('keydown', onKey);
  };
}
